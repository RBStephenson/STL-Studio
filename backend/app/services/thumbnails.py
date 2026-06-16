"""Server-side thumbnail download.

Remote thumbnail URLs (MMF/Gumroad/Cults CDNs) routinely block hot-linking
from <img> tags, so the frontend can't display them directly. Instead we
fetch the image here — with browser-like headers, the same trick the
scrapers use — and store it locally next to the DB, setting thumbnail_path.
"""
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
}

MAX_BYTES = 15 * 1024 * 1024
# Cap on how much of an HTML page we read while hunting for its preview image,
# so a pathologically large page can't exhaust memory.
HTML_MAX_BYTES = 3 * 1024 * 1024
_HTML_TYPES = {"text/html", "application/xhtml+xml"}

_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_URL_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class ThumbnailDownloadError(Exception):
    """User-readable reason an image URL couldn't be saved as a thumbnail."""


def thumbnails_dir() -> Path:
    """Return (and create) the captured-thumbnails directory next to the DB."""
    db_url = settings.database_url
    if "sqlite:///" in db_url:
        db_file = Path(db_url.split("sqlite:///", 1)[1])
    else:
        db_file = Path(db_url.split("sqlite://", 1)[1])
    if db_file.name == ":memory:":
        d = Path(tempfile.gettempdir()) / "stl_inventory_thumbnails"
    else:
        d = db_file.parent / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pick_extension(content_type: str, url: str) -> str:
    ct = content_type.split(";")[0].strip().lower()
    if ct in _CONTENT_TYPE_EXT:
        return _CONTENT_TYPE_EXT[ct]
    # Some CDNs serve images with a generic or unusual content type — fall
    # back to the URL's own extension when it looks like an image.
    url_ext = Path(urlparse(url).path).suffix.lower()
    generic = not ct or ct == "application/octet-stream" or ct.startswith("image/")
    if generic and url_ext in _URL_EXTS:
        return ".jpg" if url_ext == ".jpeg" else url_ext
    raise ThumbnailDownloadError(
        f"URL did not return an image (content type: {content_type or 'unknown'})"
    )


def _extract_og_image(html: str, base_url: str) -> str | None:
    """Pull a page's preview-image URL from its social meta tags.

    Checks og:image / twitter:image (and a couple of common variants), then
    falls back to <link rel="image_src">. Relative URLs are resolved against
    the page's own (post-redirect) URL.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates = (
        ("property", "og:image"),
        ("property", "og:image:url"),
        ("property", "og:image:secure_url"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    )
    for attr, value in candidates:
        tag = soup.find("meta", attrs={attr: value})
        content = tag.get("content") if tag else None
        if content and content.strip():
            return urljoin(base_url, content.strip())

    link = soup.find("link", rel="image_src")
    href = link.get("href") if link else None
    if href and href.strip():
        return urljoin(base_url, href.strip())
    return None


async def fetch_image_bytes(url: str, *, _follow_html: bool = True) -> tuple[str, bytes]:
    """Fetch `url` and return its `(extension, image_bytes)`.

    If `url` returns an HTML page (e.g. a Gumroad/MMF/Cults product page), its
    preview image (og:image / twitter:image) is extracted and downloaded
    instead — one level only, guarded by `_follow_html`.

    Raises ThumbnailDownloadError on any failure. Storing the bytes is the
    caller's job (see download_thumbnail), so one fetch can fan out to many
    models without re-downloading (group image, #184).
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ThumbnailDownloadError("Only http(s) URLs are supported")

    og_image_url: str | None = None
    try:
        async with httpx.AsyncClient(
            timeout=20, headers=_HEADERS, follow_redirects=True
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise ThumbnailDownloadError(
                        f"Server returned HTTP {resp.status_code}"
                    )
                content_type = resp.headers.get("content-type", "")
                ctype = content_type.split(";")[0].strip().lower()

                if ctype in _HTML_TYPES:
                    if not _follow_html:
                        raise ThumbnailDownloadError(
                            f"URL did not return an image (content type: {content_type})"
                        )
                    html = await _read_capped(resp, HTML_MAX_BYTES, stop_at_limit=True)
                    og_image_url = _extract_og_image(
                        html.decode("utf-8", errors="replace"), str(resp.url)
                    )
                    if not og_image_url:
                        raise ThumbnailDownloadError(
                            "That looks like a web page, not an image, and it has no "
                            "preview image to use. Paste a direct image link instead."
                        )
                else:
                    ext = _pick_extension(content_type, str(resp.url))
                    data = await _read_capped(resp, MAX_BYTES, stop_at_limit=False)
                    if not data:
                        raise ThumbnailDownloadError("Server returned an empty response")
                    return ext, data
    except ThumbnailDownloadError:
        raise
    except httpx.HTTPError as e:
        raise ThumbnailDownloadError(f"Could not fetch the image: {e}") from e

    # HTML page → download the preview image it points to (no further following).
    return await fetch_image_bytes(og_image_url, _follow_html=False)


async def download_thumbnail(model_id: int, url: str) -> Path:
    """Fetch `url` and store it as the local thumbnail file for `model_id`.

    Returns the saved path. Raises ThumbnailDownloadError on any failure.
    """
    ext, data = await fetch_image_bytes(url)
    return store_thumbnail(model_id, ext, data)


async def _read_capped(resp: httpx.Response, limit: int, *, stop_at_limit: bool) -> bytes:
    """Collect the response body up to `limit` bytes.

    For images (`stop_at_limit=False`) exceeding the cap is an error — we won't
    store a truncated file. For HTML (`stop_at_limit=True`) we just stop reading
    once we have enough to find the meta tags.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > limit:
            if stop_at_limit:
                chunks.append(chunk)
                break
            raise ThumbnailDownloadError("Image is too large (over 15 MB)")
        chunks.append(chunk)
    return b"".join(chunks)


def store_thumbnail(model_id: int, ext: str, data: bytes) -> Path:
    """Write thumbnail bytes to the canonical per-model file.

    Drops any previous thumbnail saved with a different extension so it can't
    be picked up again or leak disk space.
    """
    out_dir = thumbnails_dir()
    out = out_dir / f"{model_id}{ext}"
    for stale in out_dir.glob(f"{model_id}.*"):
        if stale != out:
            try:
                stale.unlink()
            except OSError:
                pass
    out.write_bytes(data)
    return out

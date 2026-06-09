"""Server-side thumbnail download.

Remote thumbnail URLs (MMF/Gumroad/Cults CDNs) routinely block hot-linking
from <img> tags, so the frontend can't display them directly. Instead we
fetch the image here — with browser-like headers, the same trick the
scrapers use — and store it locally next to the DB, setting thumbnail_path.
"""
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

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


async def download_thumbnail(model_id: int, url: str) -> Path:
    """Fetch `url` and store it as the local thumbnail file for `model_id`.

    Returns the saved path. Raises ThumbnailDownloadError on any failure.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ThumbnailDownloadError("Only http(s) URLs are supported")

    try:
        async with httpx.AsyncClient(
            timeout=20, headers=_HEADERS, follow_redirects=True
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise ThumbnailDownloadError(
                        f"Server returned HTTP {resp.status_code}"
                    )
                ext = _pick_extension(resp.headers.get("content-type", ""), str(resp.url))
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ThumbnailDownloadError("Image is too large (over 15 MB)")
                    chunks.append(chunk)
    except ThumbnailDownloadError:
        raise
    except httpx.HTTPError as e:
        raise ThumbnailDownloadError(f"Could not fetch the image: {e}") from e

    if total == 0:
        raise ThumbnailDownloadError("Server returned an empty response")

    return store_thumbnail(model_id, ext, b"".join(chunks))


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

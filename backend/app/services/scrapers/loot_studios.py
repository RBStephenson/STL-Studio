"""
Loot Studios scraper.

Two public WordPress AJAX endpoints power this:

  GetMyLootsCache   — returns the full bundle catalog as JSON (no auth required).
                      Used when the user pastes the bundle-store URL; returns one
                      StorefrontProduct per bundle for top-level folder matching.

  Load_ObjectExplorer — returns all miniatures in one bundle as an HTML fragment.
                        Used when the user pastes a specific bundle URL; returns
                        one StorefrontProduct per miniature for file-level matching.
"""
import re
import logging
import httpx
from app.services.url_guard import guarded_async_client
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Optional

from app.services.scrapers.base import ScrapedModel, SearchResult, MAX_REDIRECTS

logger = logging.getLogger(__name__)

SITE = "loot-studios"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Matches both app.lootstudios.com/bundle/slug and lootstudios.com/bundle/slug
_URL_RE = re.compile(r"lootstudios\.com/bundle/([\w-]+)", re.I)

# Extracts the WordPress post ID embedded in the page:
# AsyncObjectExplorer('#Async_ObjectExplorer',{"user":0,"bndId":878194,...});
_BND_ID_RE = re.compile(r'"bndId"\s*:\s*(\d+)')

_AJAX_URL = "https://app.lootstudios.com/wp-admin/admin-ajax.php"


@dataclass
class BundleMiniature:
    """A single miniature within a Loot Studios bundle."""
    name: str
    thumbnail_url: str
    bundle_slug: str


def extract_id(url: str) -> Optional[str]:
    m = _URL_RE.search(url)
    return m.group(1) if m else None


def _extract_bnd_id(html: str) -> Optional[str]:
    m = _BND_ID_RE.search(html)
    return m.group(1) if m else None


def _parse_miniatures(html: str, bundle_slug: str) -> list[BundleMiniature]:
    """Parse the Load_ObjectExplorer HTML fragment into individual miniatures.

    Miniature names are in img[alt]; images are on the assets.loot-studios.com
    CDN.  Tab navigation images (HEROES.png etc. from wp-content/uploads) are
    naturally excluded because they don't match the CDN domain filter.
    """
    soup = BeautifulSoup(html, "html.parser")
    minis: list[BundleMiniature] = []
    seen: set[str] = set()
    for img in soup.find_all("img", alt=True):
        src = img.get("src") or ""
        name = img.get("alt", "").strip()
        if not name or "assets.loot-studios.com/app/" not in src:
            continue
        # Strip tracking query params from CDN URLs
        clean_src = src.split("?")[0]
        if clean_src in seen:
            continue
        seen.add(clean_src)
        minis.append(BundleMiniature(name=name, thumbnail_url=clean_src, bundle_slug=bundle_slug))
    return minis


def _parse_bundle(html: str, url: str) -> Optional[ScrapedModel]:
    """Parse the bundle landing page for bundle-level metadata."""
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else None
    if not title:
        return None

    # Cover thumbnail: first wp-content/uploads image
    thumbnail_url: Optional[str] = None
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "wp-content/uploads" in src:
            thumbnail_url = src
            break

    # Tags from chip/tag elements
    tags: list[str] = []
    for el in soup.select("a.tag, span.tag, .tags a, .tag-list a, [class*='tag'] a"):
        text = el.get_text(strip=True)
        if text and text not in tags:
            tags.append(text)

    return ScrapedModel(
        title=title,
        source_url=url,
        source_site=SITE,
        external_id=extract_id(url),
        creator_name="Loot Studios",
        thumbnail_url=thumbnail_url,
        tags=tags,
    )


async def fetch_miniatures(bnd_id: str, client: httpx.AsyncClient) -> list[BundleMiniature]:
    """Call the WordPress AJAX endpoint to get all miniatures in a bundle."""
    try:
        r = await client.post(
            _AJAX_URL,
            data={"action": "Load_ObjectExplorer", "bndId": bnd_id, "user": "0", "mntId": "0", "objType": "bundle"},
        )
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Loot Studios Load_ObjectExplorer(bndId={bnd_id}) failed: {e}")
        return []

    # Extract bundle slug from the CDN URLs in the response so miniatures carry it
    slug_match = re.search(r"assets\.loot-studios\.com/app/([^/]+)/", r.text)
    bundle_slug = slug_match.group(1) if slug_match else ""
    return _parse_miniatures(r.text, bundle_slug)


async def fetch(url: str) -> Optional[ScrapedModel]:
    """Fetch bundle-level metadata for a single Loot Studios bundle URL."""
    async with guarded_async_client(timeout=20, headers=_HEADERS, follow_redirects=True, max_redirects=MAX_REDIRECTS) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Loot Studios fetch({url}) failed: {e}")
            return None
    return _parse_bundle(r.text, str(r.url))


def _mini_external_id(mini: BundleMiniature) -> str:
    """Mirrors storefront.py's per-mini external_id derivation (filename stem
    of the mini's own thumbnail URL, on the CDN it's served from) — kept in
    one place so match-time and fetch-time IDs can never drift apart."""
    return mini.thumbnail_url.split("/")[-1].split(".")[0]


async def fetch_mini(bundle_url: str, external_id: str) -> Optional[ScrapedModel]:
    """Fetch a single miniature's own detail (name + own thumbnail) within a
    bundle (STUDIO-303).

    A bundle-level fetch on ``bundle_url`` returns bundle-wide metadata (the
    bundle's own title/cover), which is wrong for a mini match — every mini
    in the bundle shares that same URL, so applying the bundle record to each
    one clobbered its own title and thumbnail with the bundle's. This re-walks
    the bundle's miniature list and returns only the one matching
    ``external_id``, so title/thumbnail overwrite is safe again.
    """
    minis = await fetch_bundle_products(bundle_url)
    for mini in minis:
        if _mini_external_id(mini) == external_id:
            return ScrapedModel(
                title=mini.name,
                source_url=bundle_url,
                source_site=SITE,
                external_id=external_id,
                creator_name="Loot Studios",
                thumbnail_url=mini.thumbnail_url,
            )
    logger.warning(f"Loot Studios: mini {external_id!r} not found in bundle {bundle_url}")
    return None


async def fetch_store_catalog() -> list[dict]:
    """Call GetMyLootsCache to get all published bundles without authentication.

    Returns a filtered list of bundle dicts with keys: obj_slug, obj_title,
    obj_image.  Excludes bundles that are hidden from the library or not yet
    available (upcoming releases, loot-coin rewards, etc.).
    """
    async with guarded_async_client(timeout=30, headers=_HEADERS) as client:
        try:
            r = await client.post(_AJAX_URL, data={"action": "GetMyLootsCache"})
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error(f"Loot Studios GetMyLootsCache failed: {e}")
            return []

    return [
        b for b in (data.get("bundleObjs") or [])
        if b.get("obj_type") == "bundle"
        and b.get("hide_library") == "false"
        and b.get("obj_available") == "true"
        and b.get("obj_slug")
    ]


async def fetch_bundle_products(url: str) -> list[BundleMiniature]:
    """Fetch all individual miniatures from a bundle page (for storefront enrichment)."""
    async with guarded_async_client(timeout=30, headers=_HEADERS, follow_redirects=True, max_redirects=MAX_REDIRECTS) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            page_html = r.text
        except Exception as e:
            logger.error(f"Loot Studios page fetch({url}) failed: {e}")
            return []

        bnd_id = _extract_bnd_id(page_html)
        if not bnd_id:
            logger.warning(f"Loot Studios: could not find bndId in {url}")
            return []

        return await fetch_miniatures(bnd_id, client)


async def search(query: str, limit: int = 12) -> list[SearchResult]:
    """Loot Studios has no public search API; URL-paste is the primary path."""
    return []

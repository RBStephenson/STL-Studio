"""
Anvilrage Studios scraper (experimental).

anvilrage.com runs an Ecwid-powered storefront embedded in a WordPress site.
Ecwid itself is a client-rendered JS widget with no public read API without a
per-store token, so the usual API-based approach (like mmf.py) isn't
available here. But the WordPress/Ecwid SEO integration server-renders a
schema.org ``Product`` JSON-LD block into the initial page HTML for search
engines — that block already carries everything we need (title, description,
full-size + thumbnail image URLs, SKU, seller name), so this scrapes that
directly. No JS execution, no API key, no browser automation.
"""
import json
import logging
import re
from typing import Optional

from app.services.scrapers.base import MAX_REDIRECTS, ScrapedModel, SearchResult
from app.services.url_guard import guarded_async_client

logger = logging.getLogger(__name__)

SITE = "anvilrage"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# https://anvilrage.com/store/Rebellious-Standard-Bearer-p484076777 — the
# trailing p<digits> is the Ecwid product id, stable across title edits.
_URL_RE = re.compile(r"anvilrage\.com/store/[\w-]+-p(\d+)", re.I)

_JSONLD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I
)


def extract_id(url: str) -> Optional[str]:
    m = _URL_RE.search(url)
    return m.group(1) if m else None


def _parse_product(html: str, url: str) -> Optional[ScrapedModel]:
    """Parse the page's schema.org Product JSON-LD block.

    A product page can carry more than one JSON-LD script (e.g. a separate
    BreadcrumbList block) — scan all of them rather than assuming the first
    match is the Product one.
    """
    product: Optional[dict] = None
    for match in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            product = data
            break
    if product is None:
        return None

    title = product.get("name")
    if not title:
        return None

    # Full-size images only, deduped in document order — each entry also
    # carries a smaller nested "thumbnail" variant we don't want in the
    # gallery (matches the mmf.py/cults3d.py convention: thumbnail_url is
    # images[0], image_urls is the full list, not the remainder).
    images: list[str] = []
    seen: set[str] = set()
    for img in product.get("image") or []:
        src = (img or {}).get("contentUrl")
        if src and src not in seen:
            seen.add(src)
            images.append(src)

    seller_name = ((product.get("offers") or {}).get("seller") or {}).get("name")

    return ScrapedModel(
        title=title,
        description=product.get("description"),
        source_url=url,
        source_site=SITE,
        external_id=extract_id(url) or product.get("sku"),
        creator_name=seller_name,
        thumbnail_url=images[0] if images else None,
        image_urls=images,
    )


async def fetch(url: str) -> Optional[ScrapedModel]:
    async with guarded_async_client(
        timeout=20, headers=_HEADERS, follow_redirects=True, max_redirects=MAX_REDIRECTS
    ) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Anvilrage fetch({url}) failed: {e}")
            return None
    return _parse_product(r.text, str(r.url))


async def search(query: str, limit: int = 12) -> list[SearchResult]:
    """No public search endpoint discovered — URL-paste is the only path."""
    return []

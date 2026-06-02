"""
Gumroad scraper — no public API, parse product page HTML.

Gumroad product pages are server-rendered and expose metadata in:
  - Open Graph meta tags (most reliable)
  - JSON-LD structured data (sometimes present)
  - Page HTML elements (fallback)
"""
import re
import json
import logging
import httpx
from bs4 import BeautifulSoup
from typing import Optional

from app.services.scrapers.base import ScrapedModel, SearchResult

logger = logging.getLogger(__name__)

SITE = "gumroad"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# gumroad.com/l/PRODUCTID  or  creator.gumroad.com/l/PRODUCTID
_URL_RE = re.compile(r"gumroad\.com/l/([\w-]+)", re.I)


def extract_id(url: str) -> Optional[str]:
    m = _URL_RE.search(url)
    return m.group(1) if m else None


async def fetch(url: str) -> Optional[ScrapedModel]:
    # Follow short-link redirects
    async with httpx.AsyncClient(
        timeout=20,
        headers=_HEADERS,
        follow_redirects=True,
    ) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            html = r.text
            final_url = str(r.url)
        except Exception as e:
            logger.error(f"Gumroad fetch({url}) failed: {e}")
            return None

    return _parse(html, final_url)


def _parse(html: str, url: str) -> Optional[ScrapedModel]:
    soup = BeautifulSoup(html, "html.parser")

    # --- Open Graph (most reliable on Gumroad) ---
    def og(prop: str) -> Optional[str]:
        tag = soup.find("meta", property=f"og:{prop}")
        return tag["content"].strip() if tag and tag.get("content") else None

    title = og("title") or _text(soup, ["h1.product-name", "h1"])
    description = og("description") or _text(soup, [".product-description", ".description"])
    thumbnail_url = og("image")

    # Try JSON-LD for richer data
    images = []
    tags: list[str] = []
    creator_name: Optional[str] = None

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            if isinstance(ld, list):
                ld = ld[0]
            if ld.get("@type") in ("Product", "CreativeWork"):
                title = title or ld.get("name")
                description = description or ld.get("description")
                creator_name = (
                    ld.get("author", {}).get("name")
                    or ld.get("brand", {}).get("name")
                )
                for img in ld.get("image", []):
                    if isinstance(img, str):
                        images.append(img)
                    elif isinstance(img, dict):
                        images.append(img.get("url", ""))
        except Exception:
            pass

    # Creator from page if not in LD
    if not creator_name:
        creator_name = _text(soup, [
            ".creator-profile-name",
            ".seller-name",
            '[class*="creator"] h2',
            '[class*="creator"] h3',
        ])

    if thumbnail_url and thumbnail_url not in images:
        images.insert(0, thumbnail_url)
    images = [i for i in images if i]

    if not title:
        return None

    return ScrapedModel(
        title=title,
        description=description,
        source_url=url,
        source_site=SITE,
        external_id=extract_id(url),
        creator_name=creator_name,
        thumbnail_url=images[0] if images else None,
        image_urls=images,
        tags=tags,
    )


async def search(query: str, limit: int = 12) -> list[SearchResult]:
    """
    Gumroad has no search API. We do a best-effort search via their
    discover page. Results are limited and not great — URL-paste is
    the primary path for Gumroad.
    """
    async with httpx.AsyncClient(
        timeout=20,
        headers=_HEADERS,
        follow_redirects=True,
    ) as client:
        try:
            r = await client.get(
                "https://gumroad.com/discover",
                params={"query": query, "from": "0", "max_price": ""},
            )
            r.raise_for_status()
            html = r.text
        except Exception as e:
            logger.error(f"Gumroad search({query!r}) failed: {e}")
            return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for card in soup.select("[data-permalink]")[:limit]:
        fallback = card.select_one("a[href*='/l/']")
        href = card.get("data-permalink") or (fallback.get("href", "") if fallback else "")
        if not href:
            continue
        product_url = f"https://gumroad.com{href}" if href.startswith("/") else href
        title_el = card.select_one("h3, h2, .name")
        results.append(SearchResult(
            title=title_el.get_text(strip=True) if title_el else product_url,
            source_url=product_url,
            source_site=SITE,
            external_id=extract_id(product_url),
            thumbnail_url=card.select_one("img[src]") and card.select_one("img[src]")["src"],
        ))
    return results


def _text(soup: BeautifulSoup, selectors: list[str]) -> Optional[str]:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True) or None
    return None

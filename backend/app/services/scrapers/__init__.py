"""
Scraper dispatcher — routes URLs and search queries to the right site adapter.
"""
from typing import Optional
from app.services.scrapers.base import ScrapedModel, SearchResult, detect_site
from app.services.scrapers import mmf, gumroad, cults3d, loot_studios, anvilrage

SITE_PATTERNS = [
    ("myminifactory", mmf),
    ("gumroad",       gumroad),
    ("cults3d",       cults3d),
    ("loot-studios",  loot_studios),
    ("anvilrage",     anvilrage),
]

__all__ = ["detect_site", "ScrapedModel", "SearchResult"]


async def fetch_url(url: str, mmf_api_key: Optional[str] = None) -> Optional[ScrapedModel]:
    """Detect site from URL and fetch metadata.

    ``mmf_api_key`` (DB secret or env fallback, resolved by the caller) enables
    the MyMiniFactory API path; other sites ignore it.
    """
    site = detect_site(url)
    if site == "myminifactory":
        return await mmf.fetch(url, api_key=mmf_api_key)
    if site == "gumroad":
        return await gumroad.fetch(url)
    if site == "cults3d":
        return await cults3d.fetch(url)
    if site == "loot-studios":
        return await loot_studios.fetch(url)
    if site == "anvilrage":
        return await anvilrage.fetch(url)
    return None


async def search_site(
    site: str, query: str, limit: int = 12, mmf_api_key: Optional[str] = None
) -> list[SearchResult]:
    """Search a specific site by name."""
    if site == "myminifactory":
        return await mmf.search(query, limit, api_key=mmf_api_key)
    if site == "gumroad":
        return await gumroad.search(query, limit)
    if site == "cults3d":
        return await cults3d.search(query, limit)
    if site == "loot-studios":
        return await loot_studios.search(query, limit)
    if site == "anvilrage":
        return await anvilrage.search(query, limit)
    return []

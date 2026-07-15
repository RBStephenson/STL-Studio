"""
Shared result type and base class for all site scrapers.
"""
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse


# Cap redirect chains on every outbound scraper request. Unbounded redirect
# following (httpx default is 20) lets a malicious storefront response bounce us
# through a long chain — or toward localhost / internal addresses — as an SSRF
# vector (STUDIO-31). Five hops covers legitimate http→https / trailing-slash /
# CDN redirects with margin; anything longer is aborted with TooManyRedirects.
MAX_REDIRECTS = 5


_SITE_DOMAINS = {
    "myminifactory.com": "myminifactory",
    "gumroad.com": "gumroad",
    "cults3d.com": "cults3d",
    "lootstudios.com": "loot-studios",
    "anvilrage.com": "anvilrage",
}


def detect_site(url: str) -> Optional[str]:
    """Return the storefront key for a URL, or None if unsupported.

    Matches on the actual hostname (exact domain or sub-domain) rather than a
    substring, so a URL that merely *contains* a known domain — e.g.
    ``https://cults3d.com.evil.com/`` or ``https://evil.com/?x=cults3d.com`` — is
    rejected instead of being fetched server-side (open-fetch / SSRF guard).
    """
    parsed = urlparse(url if "//" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    for domain, site in _SITE_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return site
    return None


@dataclass
class ScrapedModel:
    """Normalised metadata returned by any scraper."""
    # Core
    title: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None
    source_site: Optional[str] = None
    external_id: Optional[str] = None

    # Creator
    creator_name: Optional[str] = None
    creator_url: Optional[str] = None

    # Media
    thumbnail_url: Optional[str] = None
    image_urls: list[str] = field(default_factory=list)

    # Taxonomy
    tags: list[str] = field(default_factory=list)
    category: Optional[str] = None
    license: Optional[str] = None

    # Stats
    like_count: Optional[int] = None
    download_count: Optional[int] = None
    make_count: Optional[int] = None


@dataclass
class SearchResult:
    """One item in a search results list."""
    title: str
    source_url: str
    source_site: str
    external_id: Optional[str] = None
    creator_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    like_count: Optional[int] = None

"""Cults3D metadata via the official GraphQL API.

Auth: HTTP Basic with base64(username:api_key).
Endpoint: https://cults3d.com/graphql
Credentials are stored encrypted in the DB via app.services.secrets.
"""
import re
import base64
import logging
from typing import Optional

from app.services.url_guard import guarded_async_client

from app.services.scrapers.base import ScrapedModel, SearchResult, MAX_REDIRECTS

logger = logging.getLogger(__name__)

SITE = "cults3d"
_GRAPHQL_URL = "https://cults3d.com/graphql"

# https://cults3d.com/en/3d-model/game/my-slug
# The slug is the last path segment after the category.
_URL_RE = re.compile(
    r"cults3d\.com/[^/]+/3d-(?:model|printing-file|modelling)/[^/]+/([^/?#]+)",
    re.I,
)

# Cults "short URL" form, e.g. https://cults3d.com/:899311 — a numeric creation
# id, not a slug. The GraphQL API keys on slug, so we resolve the redirect to the
# canonical page and pull the slug from there.
_SHORT_RE = re.compile(r"cults3d\.com/:(\d+)", re.I)

_FETCH_QUERY = """
query FetchCreation($slug: String!) {
  creation(slug: $slug) {
    name
    description
    shortUrl
    illustrationImageUrl
    tags(locale: EN)
    license { name code }
    category { name }
    likesCount
    downloadsCount
    creator {
      nick
    }
    illustrations {
      imageUrl
    }
    blueprints {
      imageUrl
    }
  }
}
"""

_SEARCH_QUERY = """
query SearchCreations($query: String!, $limit: Int!) {
  creationsSearchBatch(query: $query, limit: $limit) {
    total
    results {
      name
      shortUrl
      illustrationImageUrl
      creator {
        nick
      }
    }
  }
}
"""


def extract_id(url: str) -> Optional[str]:
    m = _URL_RE.search(url)
    return m.group(1) if m else None


async def _resolve_short_url(url: str) -> Optional[str]:
    """Resolve a Cults `:<id>` short URL to its canonical page URL by following the
    redirect. Returns the canonical URL (slug-bearing), or None if the URL isn't a
    short form or the redirect can't be resolved."""
    if not _SHORT_RE.search(url):
        return None
    try:
        async with guarded_async_client(timeout=20, follow_redirects=True, max_redirects=MAX_REDIRECTS) as client:
            r = await client.get(url)
            canonical = str(r.url)
            return canonical if extract_id(canonical) else None
    except Exception as e:
        logger.warning(f"Cults3D: could not resolve short URL {url}: {e}")
        return None


def _auth_header(username: str, api_key: str) -> str:
    token = base64.b64encode(f"{username}:{api_key}".encode()).decode()
    return f"Basic {token}"


def _get_credentials() -> Optional[tuple[str, str]]:
    """Fetch Cults3D credentials from the DB. Returns (username, api_key) or None."""
    try:
        from app.database import SessionLocal
        from app.services import secrets
        db = SessionLocal()
        try:
            return secrets.get_cults_credentials(db)
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Could not load Cults3D credentials: {e}")
        return None


async def fetch(url: str) -> Optional[ScrapedModel]:
    canonical = url
    slug = extract_id(url)
    if not slug:
        # A `:<id>` short URL (e.g. what older enrich runs persisted) — resolve
        # its redirect to the canonical slug page before querying the API.
        resolved = await _resolve_short_url(url)
        if resolved:
            canonical = resolved
            slug = extract_id(resolved)
    if not slug:
        logger.warning(f"Could not extract slug from Cults3D URL: {url}")
        return None

    creds = _get_credentials()
    if not creds:
        logger.info("Cults3D API credentials not configured")
        return None

    username, api_key = creds
    headers = {
        "Authorization": _auth_header(username, api_key),
        "Content-Type": "application/json",
    }

    try:
        async with guarded_async_client(timeout=20) as client:
            r = await client.post(
                _GRAPHQL_URL,
                headers=headers,
                json={"query": _FETCH_QUERY, "variables": {"slug": slug}},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.error(f"Cults3D fetch({url}) failed: {e}")
        return None

    errors = data.get("errors")
    if errors:
        logger.error(f"Cults3D GraphQL errors for {slug}: {errors}")
        return None

    creation = (data.get("data") or {}).get("creation")
    if not creation:
        logger.warning(f"Cults3D: no creation found for slug {slug!r}")
        return None

    return _to_scraped_model(creation, canonical, slug)


def _to_scraped_model(creation: dict, source_url: str, slug: str) -> ScrapedModel:
    title = creation.get("name") or ""
    description = creation.get("description")
    thumbnail = creation.get("illustrationImageUrl")
    tags = creation.get("tags") or []
    license_name = (creation.get("license") or {}).get("name")
    category = (creation.get("category") or {}).get("name")
    likes = creation.get("likesCount")
    downloads = creation.get("downloadsCount")
    creator_nick = (creation.get("creator") or {}).get("nick")

    # Collect all images: cover first, then gallery illustrations, then blueprint previews.
    seen: set[str] = set()
    images: list[str] = []

    def _add(url: str | None) -> None:
        if url and url.startswith("http") and url not in seen:
            seen.add(url)
            images.append(url)

    _add(thumbnail)
    for ill in creation.get("illustrations") or []:
        _add((ill or {}).get("imageUrl"))
    for bp in creation.get("blueprints") or []:
        _add((bp or {}).get("imageUrl"))

    return ScrapedModel(
        # Store the canonical slug URL (the page we fetched), NOT creation.shortUrl
        # — the `:<id>` short form can't be re-parsed by our slug-keyed fetch (#637).
        title=title,
        description=description,
        source_url=source_url,
        source_site=SITE,
        external_id=slug,
        creator_name=creator_nick,
        thumbnail_url=thumbnail,
        image_urls=images,
        tags=tags,
        category=category,
        license=license_name,
        like_count=likes,
        download_count=downloads,
    )


async def search(query: str, limit: int = 12) -> list[SearchResult]:
    creds = _get_credentials()
    if not creds:
        logger.info("Cults3D API credentials not configured — search skipped")
        return []

    username, api_key = creds
    headers = {
        "Authorization": _auth_header(username, api_key),
        "Content-Type": "application/json",
    }

    try:
        async with guarded_async_client(timeout=20) as client:
            r = await client.post(
                _GRAPHQL_URL,
                headers=headers,
                json={
                    "query": _SEARCH_QUERY,
                    "variables": {"query": query, "limit": limit},
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.error(f"Cults3D search({query!r}) failed: {e}")
        return []

    errors = data.get("errors")
    if errors:
        logger.error(f"Cults3D GraphQL search errors: {errors}")
        return []

    batch = (data.get("data") or {}).get("creationsSearchBatch") or {}
    results = batch.get("results") or []

    out: list[SearchResult] = []
    for item in results:
        product_url = item.get("shortUrl") or ""
        slug = extract_id(product_url) or product_url
        thumb = item.get("illustrationImageUrl")
        creator_nick = (item.get("creator") or {}).get("nick")
        out.append(SearchResult(
            title=item.get("name") or product_url,
            source_url=product_url,
            source_site=SITE,
            external_id=slug,
            creator_name=creator_nick,
            thumbnail_url=thumb,
        ))

    return out

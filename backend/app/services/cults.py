"""Cults3D GraphQL API client (#578).

Auth: HTTP Basic with username + API key from encrypted app_settings.
Endpoint: https://cults3d.com/graphql (single URL, POST only).
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

GRAPHQL_ENDPOINT = "https://cults3d.com/graphql"

_CREATION_QUERY = """
query GetCreation($slug: String!) {
  creation(slug: $slug) {
    name
    shortUrl
    illustrationImageUrl
    license { name code }
    category { name }
    publishedAt
    viewsCount
    likesCount
    downloadsCount
    tags
    price { amount currency }
    creator { nick shortUrl bio imageUrl }
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
      price { amount currency }
      creator { nick shortUrl }
      tags
    }
  }
}
"""


@dataclass
class CultsCreator:
    nick: str
    short_url: str
    bio: Optional[str] = None
    image_url: Optional[str] = None


@dataclass
class CultsCreation:
    name: str
    short_url: str
    illustration_image_url: Optional[str] = None
    license_name: Optional[str] = None
    license_code: Optional[str] = None
    category: Optional[str] = None
    published_at: Optional[str] = None
    views_count: Optional[int] = None
    likes_count: Optional[int] = None
    downloads_count: Optional[int] = None
    tags: list[str] = field(default_factory=list)
    price_amount: Optional[str] = None
    price_currency: Optional[str] = None
    creator: Optional[CultsCreator] = None


class CultsAuthError(Exception):
    pass


class CultsNotFoundError(Exception):
    pass


class CultsApiError(Exception):
    pass


def _auth_header(username: str, api_key: str) -> str:
    token = base64.b64encode(f"{username}:{api_key}".encode()).decode()
    return f"Basic {token}"


def _post(username: str, api_key: str, query: str, variables: dict[str, Any]) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        GRAPHQL_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": _auth_header(username, api_key),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise CultsAuthError("Invalid Cults3D credentials") from e
        raise CultsApiError(f"Cults3D API error: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise CultsApiError(f"Cults3D unreachable: {e.reason}") from e

    if "errors" in data:
        msg = data["errors"][0].get("message", "unknown error")
        raise CultsApiError(f"Cults3D GraphQL error: {msg}")

    return data.get("data", {})


def _parse_creation(raw: dict) -> CultsCreation:
    creator = None
    if c := raw.get("creator"):
        creator = CultsCreator(
            nick=c.get("nick", ""),
            short_url=c.get("shortUrl", ""),
            bio=c.get("bio"),
            image_url=c.get("imageUrl"),
        )
    lic = raw.get("license") or {}
    cat = raw.get("category") or {}
    price = raw.get("price") or {}
    return CultsCreation(
        name=raw.get("name", ""),
        short_url=raw.get("shortUrl", ""),
        illustration_image_url=raw.get("illustrationImageUrl"),
        license_name=lic.get("name"),
        license_code=lic.get("code"),
        category=cat.get("name"),
        published_at=raw.get("publishedAt"),
        views_count=raw.get("viewsCount"),
        likes_count=raw.get("likesCount"),
        downloads_count=raw.get("downloadsCount"),
        tags=raw.get("tags") or [],
        price_amount=str(price["amount"]) if price.get("amount") is not None else None,
        price_currency=price.get("currency"),
        creator=creator,
    )


def get_creation(username: str, api_key: str, slug: str) -> CultsCreation:
    """Fetch a single creation by its Cults slug (last path segment of the URL)."""
    data = _post(username, api_key, _CREATION_QUERY, {"slug": slug})
    raw = data.get("creation")
    if not raw:
        raise CultsNotFoundError(f"No creation found for slug '{slug}'")
    return _parse_creation(raw)


def search_creations(
    username: str, api_key: str, query: str, limit: int = 20
) -> list[CultsCreation]:
    """Search Cults3D by keyword. Returns up to `limit` results."""
    data = _post(username, api_key, _SEARCH_QUERY, {"query": query, "limit": limit})
    batch = data.get("creationsSearchBatch") or {}
    results = batch.get("results") or []
    return [_parse_creation(r) for r in results]


def slug_from_url(url: str) -> str:
    """Extract slug from a full Cults3D URL.

    https://cults3d.com/en/3d-model/game/my-model -> my-model
    Also accepts bare slugs unchanged.
    """
    url = url.strip().rstrip("/")
    return url.split("/")[-1]

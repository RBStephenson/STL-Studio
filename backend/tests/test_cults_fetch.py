"""Cults3D detail mapping: _to_scraped_model carries the full field set.

Regression guard for the gap where category + license were dropped because the
GraphQL fetch query never requested them.
"""
from app.services.scrapers import cults3d


def _creation(**overrides) -> dict:
    c = {
        "name": "Goblin Warband",
        "description": "Ten goblins for the horde.",
        "shortUrl": "https://cults3d.com/en/3d-model/game/goblin-warband",
        "illustrationImageUrl": "https://cults.example/cover.jpg",
        "tags": ["goblin", "fantasy"],
        "license": {"name": "Standard Cults License", "code": "standard"},
        "category": {"name": "Game"},
        "likesCount": 42,
        "downloadsCount": 7,
        "creator": {"nick": "GoblinSmith"},
        "illustrations": [{"imageUrl": "https://cults.example/g1.jpg"}],
        "blueprints": [],
    }
    c.update(overrides)
    return c


def test_maps_category_and_license():
    m = cults3d._to_scraped_model(_creation(), "https://cults3d.com/x", "goblin-warband")
    assert m.category == "Game"
    assert m.license == "Standard Cults License"


def test_maps_core_fields():
    m = cults3d._to_scraped_model(_creation(), "https://cults3d.com/x", "goblin-warband")
    assert m.title == "Goblin Warband"
    assert m.description == "Ten goblins for the horde."
    assert m.tags == ["goblin", "fantasy"]
    assert m.creator_name == "GoblinSmith"
    assert m.like_count == 42
    assert m.download_count == 7
    assert m.source_site == "cults3d"
    assert "https://cults.example/cover.jpg" in m.image_urls


def test_missing_category_and_license_are_none():
    m = cults3d._to_scraped_model(
        _creation(license=None, category=None), "https://cults3d.com/x", "slug"
    )
    assert m.category is None
    assert m.license is None


# ---------------------------------------------------------------------------
# shortUrl round-trip bug (#637)
# ---------------------------------------------------------------------------

import pytest


def test_source_url_is_canonical_not_shorturl():
    # Even though creation.shortUrl is the unparseable ":<id>" form, we persist
    # the canonical page URL we fetched so a later re-fetch round-trips.
    canonical = "https://cults3d.com/en/3d-model/game/goblin-warband"
    m = cults3d._to_scraped_model(
        _creation(shortUrl="https://cults3d.com/:899311"), canonical, "goblin-warband"
    )
    assert m.source_url == canonical


def test_extract_id_handles_canonical_and_short():
    assert cults3d.extract_id("https://cults3d.com/en/3d-model/game/goblin-warband") == "goblin-warband"
    # The ":<id>" short form has no slug → None (resolved via redirect instead).
    assert cults3d.extract_id("https://cults3d.com/:899311") is None


@pytest.mark.anyio
async def test_resolve_short_url_follows_redirect(monkeypatch):
    canonical = "https://cults3d.com/en/3d-model/game/goblin-warband"

    class _Resp:
        url = canonical

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _Resp()

    monkeypatch.setattr(cults3d.httpx, "AsyncClient", _Client)
    assert await cults3d._resolve_short_url("https://cults3d.com/:899311") == canonical


@pytest.mark.anyio
async def test_resolve_short_url_ignores_non_short(monkeypatch):
    # A canonical URL isn't a short form → no network call, returns None.
    assert await cults3d._resolve_short_url("https://cults3d.com/en/3d-model/game/x") is None

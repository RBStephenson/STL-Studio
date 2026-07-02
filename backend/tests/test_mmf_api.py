"""
Tests for the MyMiniFactory API-first adapter path (Phase 1/2).

Covers the pure JSON->ScrapedModel mapping against a captured API fixture, plus
the fetch/search gating: API is used when a key is set, and we fall back to
scraping when there's no key or the API misses.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.scrapers import mmf
from app.services.scrapers.base import ScrapedModel

_FIXTURE = Path(__file__).parent / "fixtures" / "mmf_shuriken_api.json"


_KEY = "test-key"


def _run(coro):
    """Drive a coroutine to completion (project convention — no pytest-asyncio)."""
    return asyncio.run(coro)


@pytest.fixture
def obj() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


# --- _parse_api ------------------------------------------------------------

def test_parse_api_maps_core_fields(obj):
    model = mmf._parse_api(obj)
    assert isinstance(model, ScrapedModel)
    assert model.title == "shuriken"
    assert model.source_site == "myminifactory"
    assert model.external_id == "60156"
    assert model.source_url == "https://www.myminifactory.com/object/3d-print-shuriken-60156"
    assert model.creator_name == "tawatchai arthonkij"
    assert model.creator_url == "https://www.myminifactory.com/users/blueocean"
    assert model.tags == ["japan", "ninja", "toy", "Shuriken"]
    assert model.category == "Props & Cosplay"
    assert "Noncommercial" in (model.license or "")
    assert model.like_count == obj["likes"]


def test_parse_api_picks_largest_image_primary_first(obj):
    model = mmf._parse_api(obj)
    # The fixture's primary image exposes a 1000px 'large' variant — prefer it
    # over the smaller thumbnail/standard sizes.
    assert model.thumbnail_url == "https://dl.myminifactory.com/object-assets/5ab0c650710e2/images/shuriken1.jpg".replace(
        "shuriken1.jpg", "1000X1000-shuriken1.jpg"
    )
    assert model.image_urls
    assert model.thumbnail_url == model.image_urls[0]


def test_parse_api_requires_name(obj):
    obj["name"] = ""
    assert mmf._parse_api(obj) is None


def test_parse_api_uses_fallback_url_when_missing(obj):
    obj.pop("url", None)
    model = mmf._parse_api(obj, fallback_url="https://example.com/object/x-1")
    assert model.source_url == "https://example.com/object/x-1"


def test_image_urls_skips_images_without_sizes():
    assert mmf._image_urls({"images": [{"is_primary": True}]}) == []
    assert mmf._image_urls({}) == []


# --- _parse (HTML/JSON-LD scrape fallback) ----------------------------------

_URL = "https://www.myminifactory.com/object/dragon-123"


def _html_with_ld(image) -> str:
    ld = {"@type": "Product", "name": "Dragon", "image": image}
    return f"""
    <html><head>
    <script type="application/ld+json">{json.dumps(ld)}</script>
    </head><body></body></html>
    """


def test_parse_json_ld_string_image_extracted_as_single_url():
    """#699 2.1: schema.org allows ``image`` to be a plain string. Iterating a
    string (instead of wrapping it) yields individual characters."""
    html = _html_with_ld("https://static.mmf.example/dragon.jpg")
    model = mmf._parse(html, _URL)
    assert model.image_urls == ["https://static.mmf.example/dragon.jpg"]


def test_parse_json_ld_list_image_still_works():
    html = _html_with_ld([
        "https://static.mmf.example/dragon-1.jpg",
        "https://static.mmf.example/dragon-2.jpg",
    ])
    model = mmf._parse(html, _URL)
    assert model.image_urls == [
        "https://static.mmf.example/dragon-1.jpg",
        "https://static.mmf.example/dragon-2.jpg",
    ]


def test_parse_json_ld_missing_image_key_does_not_error():
    ld = {"@type": "Product", "name": "Dragon"}
    html = f"<html><head><script type='application/ld+json'>{json.dumps(ld)}</script></head></html>"
    model = mmf._parse(html, _URL)
    assert model.image_urls == []


# --- fetch gating ----------------------------------------------------------

def test_fetch_uses_api_when_key_set(obj):
    url = "https://www.myminifactory.com/object/3d-print-shuriken-60156"
    with patch.object(mmf, "_api_get", AsyncMock(return_value=obj)) as api, \
         patch.object(mmf, "_parse") as scrape:
        model = _run(mmf.fetch(url, api_key=_KEY))
    api.assert_awaited_once_with("/objects/60156", api_key=_KEY)
    scrape.assert_not_called()
    assert model.title == "shuriken"


def test_fetch_skips_api_without_key():
    url = "https://www.myminifactory.com/object/3d-print-shuriken-60156"
    sentinel = ScrapedModel(title="scraped", source_site="myminifactory")
    with patch.object(mmf, "_api_get", AsyncMock()) as api, \
         patch.object(mmf, "_parse", return_value=sentinel), \
         patch("app.services.scrapers.mmf.httpx.AsyncClient") as client_cls:
        _mock_async_client(client_cls, text="<html></html>")
        model = _run(mmf.fetch(url))  # no api_key
    api.assert_not_called()
    assert model.title == "scraped"


def test_fetch_falls_back_to_scrape_on_api_miss():
    url = "https://www.myminifactory.com/object/3d-print-shuriken-60156"
    sentinel = ScrapedModel(title="scraped", source_site="myminifactory")
    with patch.object(mmf, "_api_get", AsyncMock(return_value=None)) as api, \
         patch.object(mmf, "_parse", return_value=sentinel), \
         patch("app.services.scrapers.mmf.httpx.AsyncClient") as client_cls:
        _mock_async_client(client_cls, text="<html></html>")
        model = _run(mmf.fetch(url, api_key=_KEY))
    api.assert_awaited_once()
    assert model.title == "scraped"


# --- search gating ---------------------------------------------------------

def test_search_uses_api_when_key_set(obj):
    payload = {"total_count": 1, "items": [obj]}
    with patch.object(mmf, "_api_get", AsyncMock(return_value=payload)) as api:
        results = _run(mmf.search("shuriken", limit=5, api_key=_KEY))
    api.assert_awaited_once_with("/search", params={"q": "shuriken", "per_page": 5}, api_key=_KEY)
    assert len(results) == 1
    assert results[0].title == "shuriken"
    assert results[0].external_id == "60156"
    assert results[0].source_site == "myminifactory"


def test_search_skips_api_without_key():
    with patch.object(mmf, "_api_get", AsyncMock()) as api, \
         patch("app.services.scrapers.mmf.httpx.AsyncClient") as client_cls:
        _mock_async_client(client_cls, text="<html></html>")
        results = _run(mmf.search("shuriken"))  # no api_key
    api.assert_not_called()
    assert results == []


def test_search_falls_back_to_scrape_on_api_miss():
    with patch.object(mmf, "_api_get", AsyncMock(return_value=None)), \
         patch("app.services.scrapers.mmf.httpx.AsyncClient") as client_cls:
        _mock_async_client(client_cls, text="<html></html>")
        results = _run(mmf.search("shuriken", api_key=_KEY))
    assert results == []


def _mock_async_client(client_cls, *, text: str):
    """Wire a patched httpx.AsyncClient to return one canned GET response."""
    resp = MagicMock()
    resp.text = text
    resp.url = "https://www.myminifactory.com/"
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client_cls.return_value.__aenter__ = AsyncMock(return_value=client)
    client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

"""
Regression tests for the Gumroad storefront scraper (issue #286).

Gumroad's creator profile switched to an Inertia.js app: the old
`Accept: application/json` -> {"links": [...]} path returns nothing, so
enrichment silently produced an empty list. Products now live in the
HTML-escaped `data-page` JSON on `<div id="app">`. These tests pin that
parsing against a captured fixture and assert clear behaviour on bad input.
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.scrapers import storefront

_FIXTURE = Path(__file__).parent / "fixtures" / "gumroad_carlos_profile.html"


def _run_scrape(html: str) -> list:
    """Run _scrape_gumroad against a single canned profile response."""
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()

    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(storefront.httpx, "AsyncClient", return_value=ctx):
        return asyncio.run(storefront._scrape_gumroad("https://carlosedu.gumroad.com/"))


def test_parses_products_from_inertia_page():
    products = _run_scrape(_FIXTURE.read_text(encoding="utf-8"))

    # Two sections, two products each, one permalink duplicated across them.
    assert [p.title for p in products] == ["Jinx 3D Print", "Cammy 3D Print", "Chun-Li 3D Print"]

    jinx = products[0]
    assert jinx.external_id == "gbifmz"
    assert jinx.source_site == "gumroad"
    assert jinx.source_url == "https://carlosedu.gumroad.com/l/gbifmz?layout=profile"
    assert jinx.thumbnail_url == "https://public-files.gumroad.com/jinxthumb"


def test_falls_back_to_built_url_when_product_url_missing():
    # Chun-Li has url=null in the fixture; we synthesise it from the permalink.
    products = _run_scrape(_FIXTURE.read_text(encoding="utf-8"))
    chunli = products[-1]
    assert chunli.source_url == "https://carlosedu.gumroad.com/l/chunli1"
    assert chunli.thumbnail_url is None


def test_missing_data_page_returns_empty():
    products = _run_scrape("<html><body><div id='app'></div></body></html>")
    assert products == []


def test_malformed_data_page_json_returns_empty():
    products = _run_scrape('<html><body><div id="app" data-page="{not json}"></div></body></html>')
    assert products == []

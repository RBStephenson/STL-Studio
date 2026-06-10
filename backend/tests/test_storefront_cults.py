"""
Tests for the Cults3D storefront scraper's pagination bound (issue #218).

The ?page=N walk previously ran `while True`; a markup change that keeps the
"next" selector matching would loop (and politely sleep) forever, hanging the
enrichment request. Now it stops at _CULTS_MAX_PAGES with a warning.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.scrapers import storefront


def _page_html(slug: str, with_next: bool) -> str:
    next_html = '<span class="paginate next"><a href="?page=2">Next</a></span>' if with_next else ""
    return f"""
    <html><body>
      <article class="crea">
        <a href="/3d-model/figure/{slug}" title="{slug}"></a>
        <strong class="drawer-title">{slug}</strong>
        <img data-src="https://files.cults3d.com/{slug}.jpg">
      </article>
      {next_html}
    </body></html>
    """


def _run_scrape(pages: list[str]) -> tuple[list, int]:
    """Run _scrape_cults against canned page HTML; returns (products, pages_fetched)."""
    calls = {"n": 0}

    async def fake_get(url, params=None):
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        resp = MagicMock()
        resp.text = pages[idx]
        resp.raise_for_status = MagicMock()
        return resp

    client = MagicMock()
    client.get = AsyncMock(side_effect=fake_get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(storefront.httpx, "AsyncClient", return_value=ctx), \
         patch.object(storefront.asyncio, "sleep", AsyncMock()):
        products = asyncio.run(storefront._scrape_cults("https://cults3d.com/en/users/someone/3d-models"))
    return products, calls["n"]


def test_stops_when_next_link_absent():
    pages = [_page_html("model-a", with_next=True), _page_html("model-b", with_next=False)]
    products, fetched = _run_scrape(pages)
    assert fetched == 2
    assert [p.title for p in products] == ["model-a", "model-b"]


def test_page_cap_bounds_runaway_pagination(monkeypatch):
    # Every page claims to have a next page — pre-#218 this never returned.
    monkeypatch.setattr(storefront, "_CULTS_MAX_PAGES", 5)
    pages = [_page_html("model-x", with_next=True)]
    products, fetched = _run_scrape(pages)
    assert fetched == 5
    assert len(products) == 5

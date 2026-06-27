"""
MMF storefront listing now resolves each object through the MMF adapter
(mmf.fetch — API-first), instead of regex-scraping each object's HTML JSON-LD.

The store page (which embeds the object IDs) and mmf.fetch are both mocked here;
the adapter itself is tested in test_mmf_api.py.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.scrapers import storefront
from app.services.scrapers.base import ScrapedModel

_STORE_URL = "https://www.myminifactory.com/users/someone/store"
# The store page embeds object IDs in `"objects":[...]` blocks.
_STORE_HTML = '<script>var x = {"objects":[111,222],"objects":[222,333]}</script>'


def _store_page_client(html: str):
    """A patched httpx.AsyncClient whose .get returns one canned store page."""
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    cls = MagicMock()
    cls.return_value.__aenter__ = AsyncMock(return_value=client)
    cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return cls


def _scraped(oid: int) -> ScrapedModel:
    return ScrapedModel(
        title=f"Object {oid}",
        source_url=f"https://www.myminifactory.com/object/3d-print-{oid}",
        source_site="myminifactory",
        external_id=str(oid),
        thumbnail_url=f"https://img/{oid}.jpg",
        description=f"desc {oid}",
        tags=["a", "b"],
    )


def test_lists_via_mmf_adapter_with_key():
    fetch = AsyncMock(side_effect=lambda url, api_key=None: _scraped(
        int(url.rsplit("-", 1)[1])
    ))
    with patch("app.services.scrapers.mmf.fetch", fetch), \
         patch("app.services.scrapers.storefront.httpx.AsyncClient", _store_page_client(_STORE_HTML)):
        products = asyncio.run(storefront.scrape_storefront(_STORE_URL, mmf_api_key="k"))

    # Unique IDs 111, 222, 333 (deduped across the two blocks).
    assert {p.external_id for p in products} == {"111", "222", "333"}
    titles = {p.title for p in products}
    assert titles == {"Object 111", "Object 222", "Object 333"}
    # Deep fields carried through.
    sample = next(p for p in products if p.external_id == "111")
    assert sample.description == "desc 111"
    assert sample.tags == ["a", "b"]
    # The key was threaded into every adapter call.
    assert all(c.kwargs.get("api_key") == "k" for c in fetch.call_args_list)


def test_drops_objects_the_adapter_cant_resolve():
    fetch = AsyncMock(side_effect=lambda url, api_key=None: (
        _scraped(111) if url.endswith("111") else None
    ))
    with patch("app.services.scrapers.mmf.fetch", fetch), \
         patch("app.services.scrapers.storefront.httpx.AsyncClient", _store_page_client(_STORE_HTML)):
        products = asyncio.run(storefront.scrape_storefront(_STORE_URL, mmf_api_key="k"))

    assert [p.external_id for p in products] == ["111"]


def test_no_object_ids_returns_empty():
    with patch("app.services.scrapers.storefront.httpx.AsyncClient",
               _store_page_client("<script>nothing here</script>")):
        products = asyncio.run(storefront.scrape_storefront(_STORE_URL, mmf_api_key="k"))
    assert products == []

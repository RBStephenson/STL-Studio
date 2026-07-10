"""
MMF storefront listing uses the shallow store-products API for match previews
and keeps the older embedded-ID + mmf.fetch path as fallback.
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


def _store_api_client(pages: list[dict]):
    """Patched AsyncClient returning canned MMF store API pages."""
    calls = {"n": 0}

    async def fake_get(url, params=None):
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=pages[idx])
        return resp

    client = MagicMock()
    client.get = AsyncMock(side_effect=fake_get)
    cls = MagicMock()
    cls.return_value.__aenter__ = AsyncMock(return_value=client)
    cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return cls, calls


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


def _api_product(oid: int, name: str | None = None) -> dict:
    title = name or f"Object {oid}"
    return {
        "id": str(oid),
        "document_name_s": "threedobject",
        "name": title,
        "url": f"object-{oid}-{oid}",
        "obj_img": f"https://img/{oid}.jpg",
        "description": f"desc {oid}",
        "category_name": ["Fantasy", "Tabletop"],
    }


def test_lists_mmf_store_products_without_deep_fetch():
    page = {
        "products": [
            _api_product(111),
            {"id": "360", "document_name_s": "bundle", "name": "Bundle", "url": "bundle"},
            _api_product(222),
        ],
        "total": 2,
        "page": 1,
        "perPage": 100,
    }
    client_cls, calls = _store_api_client([page])
    with patch("app.services.scrapers.storefront.httpx.AsyncClient", client_cls), \
         patch("app.services.scrapers.mmf.fetch", AsyncMock()) as fetch:
        products = asyncio.run(
            storefront.scrape_storefront(
                "https://www.myminifactory.com/users/DM-Stash?show=store",
                mmf_api_key="k",
            )
        )

    assert calls["n"] == 1
    fetch.assert_not_called()
    assert [p.external_id for p in products] == ["111", "222"]
    assert products[0].title == "Object 111"
    assert products[0].source_url == "https://www.myminifactory.com/object/3d-print-object-111-111"
    assert products[0].thumbnail_url == "https://img/111.jpg"
    assert products[0].description == "desc 111"
    assert products[0].tags == ["Fantasy", "Tabletop"]


def test_mmf_store_api_pages_until_total(monkeypatch):
    monkeypatch.setattr(storefront, "_MMF_STORE_PAGE_SIZE", 2)
    pages = [
        {"products": [_api_product(111), _api_product(222)], "total": 3},
        {"products": [_api_product(333)], "total": 3},
    ]
    client_cls, calls = _store_api_client(pages)
    with patch("app.services.scrapers.storefront.httpx.AsyncClient", client_cls):
        products = asyncio.run(
            storefront.scrape_storefront(
                "https://www.myminifactory.com/users/DM-Stash?show=store",
                mmf_api_key="k",
            )
        )

    assert calls["n"] == 2
    assert [p.external_id for p in products] == ["111", "222", "333"]


def test_mmf_store_product_maps_url_variants():
    full = storefront._mmf_store_product({
        **_api_product(111),
        "url": "https://www.myminifactory.com/object/3d-print-full-111",
    })
    absolute = storefront._mmf_store_product({
        **_api_product(222),
        "url": "/object/3d-print-absolute-222",
    })
    slug = storefront._mmf_store_product(_api_product(333))

    assert full.source_url == "https://www.myminifactory.com/object/3d-print-full-111"
    assert absolute.source_url == "https://www.myminifactory.com/object/3d-print-absolute-222"
    assert slug.source_url == "https://www.myminifactory.com/object/3d-print-object-333-333"


def test_lists_via_mmf_adapter_with_key():
    fetch = AsyncMock(side_effect=lambda url, api_key=None: _scraped(
        int(url.rsplit("-", 1)[1])
    ))
    with patch("app.services.scrapers.mmf.fetch", fetch), \
         patch.object(storefront, "_scrape_mmf_store_products", AsyncMock(return_value=[])), \
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
         patch.object(storefront, "_scrape_mmf_store_products", AsyncMock(return_value=[])), \
         patch("app.services.scrapers.storefront.httpx.AsyncClient", _store_page_client(_STORE_HTML)):
        products = asyncio.run(storefront.scrape_storefront(_STORE_URL, mmf_api_key="k"))

    assert [p.external_id for p in products] == ["111"]


def test_no_object_ids_returns_empty():
    with patch.object(storefront, "_scrape_mmf_store_products", AsyncMock(return_value=[])), \
         patch("app.services.scrapers.storefront.httpx.AsyncClient",
               _store_page_client("<script>nothing here</script>")):
        products = asyncio.run(storefront.scrape_storefront(_STORE_URL, mmf_api_key="k"))
    assert products == []

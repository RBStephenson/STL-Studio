"""
Tests for bulk-enrichment thumbnail downloads (issue #208).

/enrich/storefront/apply previously stored bare remote thumbnail URLs; CDNs
block hot-linked <img> requests, so they often rendered nothing. It now
downloads them server-side like /scrape/apply, falling back to the URL when
a download fails.
"""
from unittest.mock import AsyncMock

import httpx
import pytest

from tests.conftest import make_creator, make_model

import app.services.enrich_refresh as enrich_refresh
import app.services.thumbnails as thumbnails

PNG_BYTES = b"\x89PNG\r\n\x1a\nfakepngdata"


@pytest.fixture()
def thumb_dir(tmp_path, monkeypatch):
    d = tmp_path / "thumbnails"
    d.mkdir()
    monkeypatch.setattr(thumbnails, "thumbnails_dir", lambda: d)
    return d


@pytest.fixture(autouse=True)
def _no_detail_fetch(monkeypatch):
    """Force the shallow-fallback path so these tests stay focused on thumbnail
    handling: the deep detail fetch returns nothing, so apply uses the item's
    own fields (the deep path is covered in test_enrich_deep.py)."""
    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=None))


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def mock_http(monkeypatch, handler):
    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(**kwargs)

    monkeypatch.setattr(thumbnails.httpx, "AsyncClient", factory)


def _apply_item(model, **overrides):
    item = {
        "model_id": model.id,
        "source_url": "https://cults3d.com/en/3d-model/figure/test",
        "source_site": "cults3d",
        "thumbnail_url": "https://cdn.example.com/thumb.png",
    }
    item.update(overrides)
    return item


def test_bulk_apply_downloads_thumbnail(client, db, thumb_dir, monkeypatch):
    creator = make_creator(db)
    model = make_model(db, creator)
    db.commit()

    mock_http(monkeypatch, lambda req: httpx.Response(
        200, content=PNG_BYTES, headers={"content-type": "image/png"}))

    resp = client.post("/enrich/storefront/apply", json={"items": [_apply_item(model)]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied"] == 1
    assert data["fallback_shallow"] == 1

    db.refresh(model)
    assert model.thumbnail_path == str(thumb_dir / f"{model.id}.png")
    assert model.thumbnail_url is None
    assert (thumb_dir / f"{model.id}.png").read_bytes() == PNG_BYTES


def test_bulk_apply_falls_back_to_url_on_download_failure(client, db, thumb_dir, monkeypatch):
    creator = make_creator(db)
    model = make_model(db, creator)
    db.commit()

    mock_http(monkeypatch, lambda req: httpx.Response(403))

    resp = client.post("/enrich/storefront/apply", json={"items": [_apply_item(model)]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied"] == 1

    db.refresh(model)
    assert model.thumbnail_url == "https://cdn.example.com/thumb.png"
    assert model.thumbnail_path is None


def test_bulk_apply_overwrites_existing_local_thumbnail(client, db, thumb_dir, monkeypatch):
    creator = make_creator(db)
    model = make_model(db, creator, thumbnail_path="/somewhere/local.png")
    db.commit()

    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})

    mock_http(monkeypatch, handler)

    resp = client.post("/enrich/storefront/apply", json={"items": [_apply_item(model)]})
    assert resp.status_code == 200
    assert calls["n"] == 1  # bulk enrich refreshes the thumbnail from source

    db.refresh(model)
    assert model.thumbnail_path == str(thumb_dir / f"{model.id}.png")
    assert model.thumbnail_url is None


def test_bulk_apply_mixed_results(client, db, thumb_dir, monkeypatch):
    creator = make_creator(db)
    ok_model = make_model(db, creator, name="ok")
    bad_model = make_model(db, creator, name="bad")
    db.commit()

    def handler(req):
        if "good" in str(req.url):
            return httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
        return httpx.Response(404)

    mock_http(monkeypatch, handler)

    resp = client.post("/enrich/storefront/apply", json={"items": [
        _apply_item(ok_model, thumbnail_url="https://cdn.example.com/good.png"),
        _apply_item(bad_model, thumbnail_url="https://cdn.example.com/missing.png"),
    ]})
    data = resp.json()
    assert data["applied"] == 2

    db.refresh(ok_model)
    db.refresh(bad_model)
    assert ok_model.thumbnail_path == str(thumb_dir / f"{ok_model.id}.png")
    assert bad_model.thumbnail_url == "https://cdn.example.com/missing.png"

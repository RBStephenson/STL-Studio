"""
Re-enrich / refresh-stale: POST /enrich/refresh re-fetches storefront detail for
models that already carry a ``source_url`` and re-applies it, overwriting more
aggressively than first-time bulk enrich (it's an explicit refresh of matched
data). Scope is by creator, an explicit id list, or staleness — none of which is
set means library-wide.

The detail fetch (scrapers.fetch_url) is mocked; the per-site adapters are tested
elsewhere.
"""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

import app.routers.enrich as enrich
from app.services import secrets
from app.services.scrapers.base import ScrapedModel
from app.utils import utcnow
from tests.conftest import make_creator, make_model


@pytest.fixture(autouse=True)
def _fixed_secret_key(monkeypatch):
    """Encryption key for the secrets store (the MMF-key path resolves through it)."""
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


_URL = "https://www.myminifactory.com/object/dragon-123"


def _deep(**overrides) -> ScrapedModel:
    fields = dict(
        title="Dragon Deluxe",
        description="A fearsome dragon with full detail.",
        source_url=_URL,
        source_site="myminifactory",
        external_id="123",
        tags=["dragon", "fantasy"],
        category="Creatures",
        license="CC-BY",
        thumbnail_url=None,
    )
    fields.update(overrides)
    return ScrapedModel(**fields)


def _enriched_model(db, creator, *, name="dragon", url=_URL, last_fetched=None, **kw):
    """A model that's already been enriched once (has a source_url)."""
    m = make_model(db, creator, name=name, **kw)
    m.source_url = url
    m.source_site = "myminifactory"
    m.source_last_fetched = last_fetched
    return m


def test_refresh_library_wide(client, db, monkeypatch):
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="dragon a")
    b = _enriched_model(db, creator, name="dragon b", url="https://www.myminifactory.com/object/orc-9")
    db.commit()

    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    resp = client.post("/enrich/refresh", json={})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "candidates": 2, "refreshed": 2, "failed": 0, "errors": 0}

    db.refresh(a); db.refresh(b)
    assert a.category == "Creatures"
    assert b.category == "Creatures"


def test_refresh_skips_models_without_source_url(client, db, monkeypatch):
    creator = make_creator(db)
    enriched = _enriched_model(db, creator, name="has url")
    make_model(db, creator, name="never enriched")  # no source_url
    db.commit()

    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich.scrapers, "fetch_url", fetch)

    resp = client.post("/enrich/refresh", json={})
    assert resp.json()["candidates"] == 1  # only the model with a source_url
    db.refresh(enriched)
    assert enriched.category == "Creatures"


def test_refresh_scopes_by_creator(client, db, monkeypatch):
    a = make_creator(db, name="Creator A")
    b = make_creator(db, name="Creator B")
    in_scope = _enriched_model(db, a, name="a model")
    out_scope = _enriched_model(db, b, name="b model", url="https://www.myminifactory.com/object/x-2")
    db.commit()

    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    resp = client.post("/enrich/refresh", json={"creator_id": a.id})
    assert resp.json()["candidates"] == 1

    db.refresh(in_scope); db.refresh(out_scope)
    assert in_scope.category == "Creatures"
    assert out_scope.category is None  # untouched


def test_refresh_scopes_by_model_ids(client, db, monkeypatch):
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="a")
    b = _enriched_model(db, creator, name="b", url="https://www.myminifactory.com/object/x-2")
    db.commit()

    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    resp = client.post("/enrich/refresh", json={"model_ids": [a.id]})
    assert resp.json()["candidates"] == 1

    db.refresh(a); db.refresh(b)
    assert a.category == "Creatures"
    assert b.category is None


def test_refresh_staleness_filter(client, db, monkeypatch):
    """stale_days keeps only models not fetched within the window (or never)."""
    creator = make_creator(db)
    fresh = _enriched_model(
        db, creator, name="fresh", last_fetched=utcnow() - timedelta(days=2),
        url="https://www.myminifactory.com/object/fresh-1",
    )
    stale = _enriched_model(
        db, creator, name="stale", last_fetched=utcnow() - timedelta(days=40),
        url="https://www.myminifactory.com/object/stale-2",
    )
    never = _enriched_model(
        db, creator, name="never", last_fetched=None,
        url="https://www.myminifactory.com/object/never-3",
    )
    db.commit()

    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    resp = client.post("/enrich/refresh", json={"stale_days": 30})
    assert resp.json()["candidates"] == 2  # stale + never, not fresh

    db.refresh(fresh); db.refresh(stale); db.refresh(never)
    assert fresh.category is None  # skipped — fetched recently
    assert stale.category == "Creatures"
    assert never.category == "Creatures"


def test_refresh_overwrites_aggressively(client, db, monkeypatch):
    """Refresh overwrites an existing title (bulk enrich only fills an empty one)."""
    creator = make_creator(db)
    model = _enriched_model(db, creator, name="dragon")
    model.title = "My Edited Title"
    model.description = "old description"
    db.commit()

    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    resp = client.post("/enrich/refresh", json={})
    assert resp.json()["refreshed"] == 1

    db.refresh(model)
    assert model.title == "Dragon Deluxe"           # overwritten
    assert model.description == "A fearsome dragon with full detail."


def test_refresh_does_not_reassign_creator(client, db, monkeypatch):
    """#699 1.1: refresh must not re-point creator_id even though it overwrites
    other fields aggressively — a differently-spelled scraped creator_name would
    otherwise silently split the library on every periodic refresh."""
    creator = make_creator(db, name="abe3d")
    model = _enriched_model(db, creator, name="dragon")
    db.commit()

    monkeypatch.setattr(
        enrich.scrapers, "fetch_url",
        AsyncMock(return_value=_deep(creator_name="Abe 3D Prints")),
    )

    resp = client.post("/enrich/refresh", json={})
    assert resp.json()["refreshed"] == 1

    db.refresh(model)
    assert model.creator_id == creator.id


def test_refresh_failed_fetch_leaves_model_untouched(client, db, monkeypatch):
    creator = make_creator(db)
    model = _enriched_model(db, creator, name="orphan")
    model.title = "Keep Me"
    db.commit()

    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=None))

    resp = client.post("/enrich/refresh", json={})
    assert resp.json() == {"ok": True, "candidates": 1, "refreshed": 0, "failed": 1, "errors": 0}

    db.refresh(model)
    assert model.title == "Keep Me"      # not clobbered with shallow data
    assert model.description is None


def test_refresh_one_fetch_per_unique_url(client, db, monkeypatch):
    """Variants share a product URL — fetch once, fan out to every model."""
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="variant a")
    b = _enriched_model(db, creator, name="variant b")  # same _URL
    db.commit()

    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich.scrapers, "fetch_url", fetch)

    resp = client.post("/enrich/refresh", json={})
    assert resp.json()["refreshed"] == 2
    assert fetch.await_count == 1

    db.refresh(a); db.refresh(b)
    assert a.category == "Creatures"
    assert b.category == "Creatures"


def test_refresh_empty_library_returns_zero(client, db, monkeypatch):
    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich.scrapers, "fetch_url", fetch)

    resp = client.post("/enrich/refresh", json={})
    assert resp.json() == {"ok": True, "candidates": 0, "refreshed": 0, "failed": 0, "errors": 0}
    fetch.assert_not_awaited()


def test_refresh_shared_scraped_model_not_mutated_across_siblings(client, db, monkeypatch):
    """#699 2.2: variant siblings on the same URL each get their own effective
    source identity — the cached ScrapedModel must not be mutated in place."""
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="variant a")
    b = _enriched_model(db, creator, name="variant b")  # same _URL
    a.external_id = None
    b.external_id = None
    db.commit()

    shared = _deep(external_id=None)
    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=shared))

    resp = client.post("/enrich/refresh", json={})
    assert resp.status_code == 200

    assert shared.external_id is None  # the shared object was never mutated


def test_refresh_error_isolation_reports_errors_and_keeps_others(client, db, monkeypatch):
    """#699 2.3: one model raising during apply must not 500 the batch — it's
    counted in ``errors`` while the other model still refreshes."""
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="dragon a", url="https://www.myminifactory.com/object/a-1")
    b = _enriched_model(db, creator, name="dragon b", url="https://www.myminifactory.com/object/b-2")
    db.commit()

    async def _fetch(url, mmf_api_key=None):
        return _deep(source_url=url, external_id=url)

    monkeypatch.setattr(enrich.scrapers, "fetch_url", _fetch)

    real_apply = enrich.apply_scraped_to_model

    async def _flaky(db_, model, scraped, **kw):
        if model.id == a.id:
            raise RuntimeError("boom")
        return await real_apply(db_, model, scraped, **kw)

    monkeypatch.setattr(enrich, "apply_scraped_to_model", _flaky)

    resp = client.post("/enrich/refresh", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["errors"] == 1
    assert data["refreshed"] == 1

    db.refresh(b)
    assert b.category == "Creatures"


def test_refresh_passes_mmf_key_to_fetch(client, db, monkeypatch):
    creator = make_creator(db)
    _enriched_model(db, creator, name="dragon")
    db.commit()

    secrets.set_mmf_api_key(db, "test-mmf-key")
    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich.scrapers, "fetch_url", fetch)

    resp = client.post("/enrich/refresh", json={})
    assert resp.status_code == 200
    fetch.assert_awaited_once_with(_URL, mmf_api_key="test-mmf-key")

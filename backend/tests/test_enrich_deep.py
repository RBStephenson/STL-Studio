"""
Deep creator-enrichment: /enrich/storefront/apply fetches each selected
product's full detail and writes the complete field set (description, tags,
category, license) to every model that matched it — so the user doesn't have to
go model-by-model through Find-on-Web.

The detail fetch (scrapers.fetch_url) is mocked here; the real per-site adapters
are tested elsewhere. Thumbnails are left out (url=None) to keep these focused on
metadata — thumbnail handling is covered in test_enrich_thumbnails.py.
"""
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

import app.routers.enrich as enrich
from app.services import secrets
from app.services.scrapers.base import ScrapedModel
from tests.conftest import make_creator, make_model


@pytest.fixture(autouse=True)
def _fixed_secret_key(monkeypatch):
    """Encryption key for the secrets store (the MMF-key test sets a key)."""
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


def _item(model, **overrides) -> dict:
    item = {
        "model_id": model.id,
        "source_url": _URL,
        "source_site": "myminifactory",
        "title": "shallow title",
    }
    item.update(overrides)
    return item


def test_apply_writes_deep_fields(client, db, monkeypatch):
    creator = make_creator(db)
    model = make_model(db, creator, name="dragon")
    db.commit()

    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    resp = client.post("/enrich/storefront/apply", json={"items": [_item(model)]})
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"ok": True, "applied": 1, "enriched_deep": 1, "fallback_shallow": 0}

    db.refresh(model)
    assert model.description == "A fearsome dragon with full detail."
    assert set(model.tags) >= {"dragon", "fantasy"}
    assert model.category == "Creatures"
    assert model.license == "CC-BY"
    assert model.source_url == _URL
    assert model.external_id == "123"
    assert model.needs_review is False


def test_one_fetch_per_unique_url_fans_to_all_models(client, db, monkeypatch):
    """Variants share a product URL — fetch the detail once, apply to every one."""
    creator = make_creator(db)
    a = make_model(db, creator, name="dragon a")
    b = make_model(db, creator, name="dragon b")
    db.commit()

    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich.scrapers, "fetch_url", fetch)

    resp = client.post("/enrich/storefront/apply", json={
        "items": [_item(a), _item(b)],
    })
    assert resp.status_code == 200
    assert resp.json()["enriched_deep"] == 2
    assert fetch.await_count == 1  # one fetch for the shared URL

    db.refresh(a); db.refresh(b)
    assert a.category == "Creatures"
    assert b.category == "Creatures"


def test_falls_back_to_shallow_when_fetch_returns_none(client, db, monkeypatch):
    creator = make_creator(db)
    model = make_model(db, creator, name="orphan")
    db.commit()

    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=None))

    resp = client.post("/enrich/storefront/apply", json={
        "items": [_item(model, title="Shallow Title")],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["enriched_deep"] == 0
    assert data["fallback_shallow"] == 1

    db.refresh(model)
    # Shallow fields from the item still land; deep-only fields stay empty.
    assert model.source_url == _URL
    assert model.title == "Shallow Title"
    assert model.description is None
    assert not model.tags


def test_apply_leaves_needs_review_set_when_already_true(client, db, monkeypatch):
    """#699 1.3: bulk apply is unreviewed data — don't clear a flag a human hasn't seen."""
    creator = make_creator(db)
    model = make_model(db, creator, name="dragon", needs_review=True)
    db.commit()

    monkeypatch.setattr(enrich.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    resp = client.post("/enrich/storefront/apply", json={"items": [_item(model)]})
    assert resp.status_code == 200

    db.refresh(model)
    assert model.needs_review is True


def test_apply_does_not_reassign_creator(client, db, monkeypatch):
    """#699 1.1: a differently-spelled scraped creator_name must not move the
    model to a new/different Creator during bulk apply."""
    creator = make_creator(db, name="abe3d")
    model = make_model(db, creator, name="dragon")
    db.commit()

    monkeypatch.setattr(
        enrich.scrapers, "fetch_url",
        AsyncMock(return_value=_deep(creator_name="Abe 3D Prints")),
    )

    resp = client.post("/enrich/storefront/apply", json={"items": [_item(model)]})
    assert resp.status_code == 200

    db.refresh(model)
    assert model.creator_id == creator.id


def test_bulk_apply_passes_mmf_key_to_fetch(client, db, monkeypatch):
    """The resolved MMF key is threaded into the detail fetch."""
    creator = make_creator(db)
    model = make_model(db, creator, name="dragon")
    db.commit()

    secrets.set_mmf_api_key(db, "test-mmf-key")
    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich.scrapers, "fetch_url", fetch)

    resp = client.post("/enrich/storefront/apply", json={"items": [_item(model)]})
    assert resp.status_code == 200
    fetch.assert_awaited_once_with(_URL, mmf_api_key="test-mmf-key")


# ---------------------------------------------------------------------------
# Group-level matching (#628)
# ---------------------------------------------------------------------------

from app.services.matcher import MatchCandidate
from app.services.scrapers.storefront import StorefrontProduct
from app.models import VariantGroup


def _cand(model_id, score):
    return MatchCandidate(
        local_model_id=model_id, local_name="x", local_folder="/f",
        product=StorefrontProduct(title="t", source_url="u", source_site="gumroad"),
        score=score, confidence="high",
    )


def test_collapse_keeps_best_candidate_per_group():
    # a,b in group 10; c ungrouped. Best of the group (b) survives; c kept.
    group_of = {1: 10, 2: 10, 3: None}
    out = enrich._collapse_candidates_to_groups(
        [_cand(1, 0.5), _cand(2, 0.8), _cand(3, 0.4)], group_of
    )
    ids = {c.local_model_id for c in out}
    assert ids == {2, 3}                       # one per group + the ungrouped one
    assert out[0].local_model_id == 2          # sorted by score desc


def test_apply_propagates_match_to_group_siblings(client, db, monkeypatch):
    creator = make_creator(db)
    a = make_model(db, creator, name="dragon a")
    b = make_model(db, creator, name="dragon b")
    g = VariantGroup(creator_id=creator.id, label="Dragon", source="auto")
    db.add(g); db.flush()
    a.variant_group_id = g.id; b.variant_group_id = g.id
    db.commit()

    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich.scrapers, "fetch_url", fetch)

    # Apply only the collapsed candidate (model a) — b is a silent sibling.
    resp = client.post("/enrich/storefront/apply", json={"items": [_item(a)]})
    assert resp.status_code == 200
    assert resp.json()["applied"] == 2          # propagated to b

    db.refresh(a); db.refresh(b)
    assert a.category == "Creatures"
    assert b.category == "Creatures"            # sibling got the deep data
    assert fetch.await_count == 1               # still one fetch for the shared URL

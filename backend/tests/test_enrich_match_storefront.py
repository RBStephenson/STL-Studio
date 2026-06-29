"""
Tests for GET /enrich/storefront/match — focuses on the model-count guard
added in #655 (unbounded fetch).
"""
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet

import app.routers.enrich as enrich_module
from app.services import secrets
from app.services.scrapers.base import ScrapedModel
from tests.conftest import make_creator, make_model

_STOREFRONT_URL = "https://www.myminifactory.com/users/test-creator"


def _product(**overrides) -> ScrapedModel:
    fields = dict(
        title="Cool Dragon",
        description=None,
        source_url=_STOREFRONT_URL,
        source_site="myminifactory",
        external_id="42",
        tags=[],
        category=None,
        license=None,
        thumbnail_url=None,
    )
    fields.update(overrides)
    return ScrapedModel(**fields)


@pytest.fixture(autouse=True)
def _secret_key(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


def test_no_models_returns_404(client, db, monkeypatch):
    creator = make_creator(db)
    db.commit()

    monkeypatch.setattr(
        enrich_module, "scrape_storefront", AsyncMock(return_value=[_product()])
    )

    resp = client.get(
        "/enrich/storefront/match",
        params={"url": _STOREFRONT_URL, "creator_id": creator.id},
    )
    assert resp.status_code == 404
    assert "No local models" in resp.json()["detail"]


def test_over_limit_returns_422(client, db, monkeypatch):
    creator = make_creator(db)
    for i in range(3):
        make_model(db, creator, name=f"model-{i}")
    db.commit()

    monkeypatch.setattr(
        enrich_module, "scrape_storefront", AsyncMock(return_value=[_product()])
    )
    # Patch the constant so we don't have to insert 5001 rows.
    monkeypatch.setattr(enrich_module, "_MAX_CREATOR_MODELS", 2)

    resp = client.get(
        "/enrich/storefront/match",
        params={"url": _STOREFRONT_URL, "creator_id": creator.id},
    )
    assert resp.status_code == 422
    assert "exceeds the match limit" in resp.json()["detail"]


def test_within_limit_returns_candidates(client, db, monkeypatch):
    creator = make_creator(db)
    make_model(db, creator, name="dragon")
    db.commit()

    monkeypatch.setattr(
        enrich_module, "scrape_storefront", AsyncMock(return_value=[_product(title="dragon")])
    )

    resp = client.get(
        "/enrich/storefront/match",
        params={"url": _STOREFRONT_URL, "creator_id": creator.id, "min_score": 0.0},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

"""Cults3D credential storage (encrypted at rest) and API endpoints (#578).

Credentials are write-only — API never returns plaintext, only a masked hint.
Uses the same Fernet pattern as AI API key (see test_ai_settings.py).
"""
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from app.models import AppSetting
from app.services import cults as cults_client
from app.services import secrets


@pytest.fixture(autouse=True)
def _fixed_secret_key(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


# --- secrets.py unit tests ---------------------------------------------------

def test_set_and_get_cults_credentials(db):
    secrets.set_cults_credentials(db, "myuser", "myapikey")
    creds = secrets.get_cults_credentials(db)
    assert creds == ("myuser", "myapikey")


def test_credentials_encrypted_at_rest(db):
    secrets.set_cults_credentials(db, "rbstephenson", "Z7JguQOvB7vYWwUsywkE8oOba")
    row = db.get(AppSetting, secrets.CULTS_CREDS_ENC)
    assert row is not None
    assert "rbstephenson" not in row.value
    assert "Z7JguQOvB7vYWwUsywkE8oOba" not in row.value


def test_credentials_hint(db):
    secrets.set_cults_credentials(db, "rbstephenson", "Z7JguQOvB7vYWwUsywkE8oOba")
    hint = secrets.cults_credentials_hint(db)
    assert hint == "rbstephenson / …oOba"


def test_clear_credentials(db):
    secrets.set_cults_credentials(db, "u", "k")
    secrets.clear_cults_credentials(db)
    assert secrets.get_cults_credentials(db) is None
    assert secrets.cults_credentials_hint(db) is None


def test_blank_credentials_clear(db):
    secrets.set_cults_credentials(db, "u", "k")
    secrets.set_cults_credentials(db, "", "")
    assert secrets.get_cults_credentials(db) is None


def test_credentials_never_in_plain_settings(client, db):
    secrets.set_cults_credentials(db, "rbstephenson", "secret-key")
    body = client.get("/settings").json()
    assert "rbstephenson" not in str(body)
    assert "secret-key" not in str(body)
    assert secrets.CULTS_CREDS_ENC not in body


# --- settings API endpoints ---------------------------------------------------

def test_cults_settings_default(client):
    r = client.get("/settings/cults")
    assert r.status_code == 200
    assert r.json() == {"credentials_set": False, "hint": None}


def test_set_credentials_via_api(client):
    r = client.put("/settings/cults/credentials", json={
        "username": "rbstephenson",
        "api_key": "Z7JguQOvB7vYWwUsywkE8oOba",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["credentials_set"] is True
    assert body["hint"] == "rbstephenson / …oOba"


def test_clear_credentials_via_api(client):
    client.put("/settings/cults/credentials", json={"username": "u", "api_key": "k"})
    r = client.delete("/settings/cults/credentials")
    assert r.status_code == 200
    assert r.json()["credentials_set"] is False


def test_empty_fields_rejected(client):
    assert client.put("/settings/cults/credentials", json={"username": "", "api_key": "k"}).status_code == 422
    assert client.put("/settings/cults/credentials", json={"username": "u", "api_key": ""}).status_code == 422


# --- cults router endpoints (mocked) -----------------------------------------

def _fake_creation():
    return cults_client.CultsCreation(
        name="Space Marine",
        short_url="https://cults3d.com/en/3d-model/game/space-marine",
        illustration_image_url="https://files.cults3d.com/img.jpg",
        license_name="CC BY",
        license_code="cc_by",
        category="Game",
        tags=["warhammer", "40k"],
        creator=cults_client.CultsCreator(
            nick="sculptor42",
            short_url="https://cults3d.com/en/users/sculptor42",
        ),
    )


@pytest.fixture
def _cults_creds(client, db):
    secrets.set_cults_credentials(db, "rbstephenson", "testkey")


def test_search_no_credentials_returns_424(client):
    r = client.get("/cults/search?q=space+marine")
    assert r.status_code == 424


def test_search_returns_results(client, _cults_creds):
    with patch.object(cults_client, "search_creations", return_value=[_fake_creation()]):
        r = client.get("/cults/search?q=space+marine")
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["name"] == "Space Marine"
    assert body["results"][0]["creator"]["nick"] == "sculptor42"


def test_get_creation_by_slug(client, _cults_creds):
    with patch.object(cults_client, "get_creation", return_value=_fake_creation()) as mock_get:
        r = client.get("/cults/creation/space-marine")
    assert r.status_code == 200
    assert r.json()["name"] == "Space Marine"
    mock_get.assert_called_once_with("rbstephenson", "testkey", "space-marine")


def test_get_creation_accepts_full_url(client, _cults_creds):
    with patch.object(cults_client, "get_creation", return_value=_fake_creation()) as mock_get:
        r = client.get("/cults/creation/https://cults3d.com/en/3d-model/game/space-marine")
    assert r.status_code == 200
    mock_get.assert_called_once_with("rbstephenson", "testkey", "space-marine")


def test_get_creation_not_found(client, _cults_creds):
    with patch.object(cults_client, "get_creation", side_effect=cults_client.CultsNotFoundError("nope")):
        r = client.get("/cults/creation/no-such-slug")
    assert r.status_code == 404


def test_auth_error_returns_401(client, _cults_creds):
    with patch.object(cults_client, "search_creations", side_effect=cults_client.CultsAuthError("bad creds")):
        r = client.get("/cults/search?q=test")
    assert r.status_code == 401


# --- cults_client unit tests --------------------------------------------------

def test_slug_from_full_url():
    assert cults_client.slug_from_url(
        "https://cults3d.com/en/3d-model/game/space-marine"
    ) == "space-marine"


def test_slug_from_bare_slug():
    assert cults_client.slug_from_url("space-marine") == "space-marine"


def test_slug_strips_trailing_slash():
    assert cults_client.slug_from_url(
        "https://cults3d.com/en/3d-model/game/space-marine/"
    ) == "space-marine"

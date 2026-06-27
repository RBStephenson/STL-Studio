"""MyMiniFactory settings: encrypted-at-rest API key.

Same write-only contract as the AI key — the API never returns the plaintext,
only whether one is set plus a masked hint. Encryption uses Fernet keyed off
STL_SECRET_KEY (set here so the suite never writes a key file).
"""
import pytest
from cryptography.fernet import Fernet

from app.models import AppSetting
from app.services import secrets


@pytest.fixture(autouse=True)
def _fixed_secret_key(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


def test_mmf_settings_default_no_key(client):
    r = client.get("/settings/mmf")
    assert r.status_code == 200
    assert r.json() == {"key_set": False, "key_hint": None}


def test_set_mmf_key_reports_masked_hint(client):
    r = client.put("/settings/mmf/key", json={"key": "ff53ef32-1cd8-wxyz"})
    assert r.status_code == 200
    body = r.json()
    assert body["key_set"] is True
    assert body["key_hint"] == "…wxyz"


def test_mmf_key_is_encrypted_at_rest(client, db):
    client.put("/settings/mmf/key", json={"key": "mmf-secret-value-1234"})
    row = db.get(AppSetting, secrets.MMF_API_KEY_ENC)
    assert row is not None
    assert "mmf-secret-value-1234" not in row.value
    assert secrets.get_mmf_api_key(db) == "mmf-secret-value-1234"


def test_mmf_key_never_appears_in_plain_settings(client):
    client.put("/settings/mmf/key", json={"key": "mmf-do-not-leak"})
    body = client.get("/settings").json()
    assert "mmf_api_key" not in body
    assert "mmf_api_key_enc" not in body
    assert "mmf-do-not-leak" not in str(body)


def test_clear_mmf_key(client):
    client.put("/settings/mmf/key", json={"key": "mmf-test-1234"})
    r = client.delete("/settings/mmf/key")
    assert r.status_code == 200
    assert r.json()["key_set"] is False
    assert client.get("/settings/mmf").json()["key_set"] is False


def test_blank_mmf_key_rejected(client):
    assert client.put("/settings/mmf/key", json={"key": ""}).status_code == 422


def test_mmf_key_resolution_prefers_db_over_env(db, monkeypatch):
    """scrape._mmf_key uses the DB secret first, the .env value as fallback."""
    from app.config import settings as live_settings
    from app.routers import scrape

    monkeypatch.setattr(live_settings, "mmf_api_key", "env-fallback-key")
    assert scrape._mmf_key(db) == "env-fallback-key"  # no DB key yet

    secrets.set_mmf_api_key(db, "db-key")
    assert scrape._mmf_key(db) == "db-key"  # DB wins

    monkeypatch.setattr(live_settings, "mmf_api_key", "")
    secrets.clear_mmf_api_key(db)
    assert scrape._mmf_key(db) is None  # neither set


def test_mmf_and_ai_keys_are_independent(client, db):
    """Both secrets coexist in their own rows — setting one doesn't touch the other."""
    client.put("/settings/ai/key", json={"key": "sk-ai-key-aaaa"})
    client.put("/settings/mmf/key", json={"key": "mmf-key-bbbb"})
    assert secrets.get_ai_api_key(db) == "sk-ai-key-aaaa"
    assert secrets.get_mmf_api_key(db) == "mmf-key-bbbb"
    # Clearing MMF leaves the AI key intact.
    client.delete("/settings/mmf/key")
    assert secrets.get_mmf_api_key(db) is None
    assert secrets.get_ai_api_key(db) == "sk-ai-key-aaaa"

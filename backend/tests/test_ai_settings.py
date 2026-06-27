"""AI settings: encrypted-at-rest API key + model (#517).

The key is write-only — the API never returns the plaintext, only whether one is
set plus a masked hint. Encryption uses Fernet keyed off STL_SECRET_KEY (set here
so the suite never writes a key file).
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


def test_ai_settings_default_no_key(client):
    r = client.get("/settings/ai")
    assert r.status_code == 200
    body = r.json()
    assert body == {"key_set": False, "key_hint": None, "model": "", "effort": "low"}


def test_set_key_reports_masked_hint(client):
    r = client.put("/settings/ai/key", json={"key": "sk-test-ABCDwxyz"})
    assert r.status_code == 200
    body = r.json()
    assert body["key_set"] is True
    assert body["key_hint"] == "…wxyz"


def test_key_is_encrypted_at_rest(client, db):
    client.put("/settings/ai/key", json={"key": "sk-secret-value-1234"})
    row = db.get(AppSetting, secrets.AI_API_KEY_ENC)
    assert row is not None
    # Stored ciphertext must not contain the plaintext.
    assert "sk-secret-value-1234" not in row.value
    # ...but decrypts back to it through the service.
    assert secrets.get_ai_api_key(db) == "sk-secret-value-1234"


def test_key_never_appears_in_plain_settings(client):
    client.put("/settings/ai/key", json={"key": "sk-do-not-leak"})
    body = client.get("/settings").json()
    assert "ai_api_key" not in body
    assert "ai_api_key_enc" not in body
    assert "sk-do-not-leak" not in str(body)


def test_clear_key(client):
    client.put("/settings/ai/key", json={"key": "sk-test-1234"})
    r = client.delete("/settings/ai/key")
    assert r.status_code == 200
    assert r.json()["key_set"] is False
    assert client.get("/settings/ai").json()["key_set"] is False


def test_blank_key_rejected(client):
    assert client.put("/settings/ai/key", json={"key": ""}).status_code == 422


def test_model_round_trips_and_shows_in_ai_settings(client):
    r = client.patch("/settings", json={"ai_model": "claude-opus-4-8"})
    assert r.status_code == 200
    assert r.json()["ai_model"] == "claude-opus-4-8"
    assert client.get("/settings/ai").json()["model"] == "claude-opus-4-8"

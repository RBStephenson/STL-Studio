"""Named AI API config CRUD (#849): create/update accept an inline api_key so
the key can be set in the same request instead of a separate follow-up call.
"""
import pytest
from cryptography.fernet import Fernet

from app.services import secrets


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


def test_create_with_inline_key_sets_it_immediately(client):
    r = client.post("/settings/ai-apis", json={
        "name": "Ollama Crawlspace", "api_type": "anthropic",
        "model": "claude-haiku-4-5", "api_key": "sk-ant-inline",
    })
    body = r.json()
    assert body["key_set"] is True
    assert body["key_hint"] == "…line"


def test_create_without_key_stays_keyless(client):
    r = client.post("/settings/ai-apis", json={
        "name": "Ollama Local", "api_type": "openai", "url": "http://localhost:11434",
    })
    assert r.json()["key_set"] is False


def test_update_with_inline_key_sets_it(client):
    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude", "api_type": "anthropic", "model": "claude-haiku-4-5",
    }).json()
    assert cfg["key_set"] is False

    r = client.patch(f"/settings/ai-apis/{cfg['id']}", json={
        "request_timeout": 20, "api_key": "sk-ant-updated",
    })
    body = r.json()
    assert body["key_set"] is True
    assert body["key_hint"] == "…ated"
    assert body["request_timeout"] == 20


def test_update_without_key_field_leaves_existing_key_untouched(client):
    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude", "api_type": "anthropic", "model": "claude-haiku-4-5",
        "api_key": "sk-ant-original",
    }).json()

    r = client.patch(f"/settings/ai-apis/{cfg['id']}", json={"request_timeout": 30})
    body = r.json()
    assert body["key_set"] is True
    assert body["key_hint"] == "…inal"
    assert body["request_timeout"] == 30


def test_create_defaults_batch_size_to_null(client):
    r = client.post("/settings/ai-apis", json={
        "name": "Ollama Local", "api_type": "openai", "url": "http://localhost:11434",
    })
    assert r.json()["batch_size"] is None


def test_create_and_update_batch_size(client):
    cfg = client.post("/settings/ai-apis", json={
        "name": "Ollama Local", "api_type": "openai", "url": "http://localhost:11434",
        "batch_size": 10,
    }).json()
    assert cfg["batch_size"] == 10

    r = client.patch(f"/settings/ai-apis/{cfg['id']}", json={"batch_size": 20})
    assert r.json()["batch_size"] == 20


def test_batch_size_out_of_range_is_rejected(client):
    r = client.post("/settings/ai-apis", json={
        "name": "Ollama Local", "api_type": "openai", "url": "http://localhost:11434",
        "batch_size": 0,
    })
    assert r.status_code == 422

    r = client.post("/settings/ai-apis", json={
        "name": "Ollama Local", "api_type": "openai", "url": "http://localhost:11434",
        "batch_size": 51,
    })
    assert r.status_code == 422

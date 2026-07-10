"""AI Guide Drafts resolves its assigned "Use API" config (#820).

Previously generate_guide_draft() ignored ai_guides_api and always read the
legacy global ai_api_key/ai_model/ai_effort settings, so assigning a named
AiApiConfig to the function had no effect. These tests cover the resolver
(load_guides_config) directly and end-to-end through the draft-kickoff router.
"""
import pytest
from cryptography.fernet import Fernet

from app.models import AppSetting
from app.painting.services import generation
from app.services import secrets


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


def _enable(db):
    db.add(AppSetting(key="ai_guides_enabled", value=True))
    db.commit()


def test_not_enabled_raises(db):
    with pytest.raises(generation.MissingApiKeyError, match="not enabled"):
        generation.load_guides_config(db)


def test_resolves_assigned_anthropic_config(client, db):
    _enable(db)
    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude Creative", "api_type": "anthropic",
        "model": "claude-opus-4-8", "effort": "high",
    }).json()
    client.post(f"/settings/ai-apis/{cfg['id']}/key", json={"key": "sk-ant-assigned"})
    client.patch("/settings", json={"ai_guides_api": cfg["id"]})

    resolved = generation.load_guides_config(db)
    assert resolved.model == "claude-opus-4-8"
    assert resolved.api_key == "sk-ant-assigned"
    assert resolved.effort == "high"


def test_assigned_config_wins_over_legacy_globals(client, db):
    """If both a legacy global key AND a named config are present, the
    assigned config must win — proving it's actually being used."""
    _enable(db)
    secrets.set_ai_api_key(db, "sk-legacy-global")
    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude Creative", "api_type": "anthropic",
        "model": "claude-opus-4-8", "effort": "low",
    }).json()
    client.post(f"/settings/ai-apis/{cfg['id']}/key", json={"key": "sk-ant-assigned"})
    client.patch("/settings", json={"ai_guides_api": cfg["id"]})

    resolved = generation.load_guides_config(db)
    assert resolved.api_key == "sk-ant-assigned"


def test_legacy_fallback_when_no_config_assigned(db):
    _enable(db)
    secrets.set_ai_api_key(db, "sk-legacy-global")
    resolved = generation.load_guides_config(db)
    assert resolved.api_key == "sk-legacy-global"


def test_openai_config_rejected(client, db):
    _enable(db)
    cfg = client.post("/settings/ai-apis", json={
        "name": "Local Ollama", "api_type": "openai", "url": "http://x:11434", "model": "llama3",
    }).json()
    client.patch("/settings", json={"ai_guides_api": cfg["id"]})

    with pytest.raises(generation.MissingApiKeyError, match="Anthropic"):
        generation.load_guides_config(db)


def test_assigned_config_missing_key_raises(client, db):
    _enable(db)
    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude Creative", "api_type": "anthropic", "model": "claude-opus-4-8",
    }).json()
    client.patch("/settings", json={"ai_guides_api": cfg["id"]})

    with pytest.raises(generation.MissingApiKeyError, match="No API key"):
        generation.load_guides_config(db)


def test_deleted_assigned_config_raises_clear_error(client, db):
    _enable(db)
    cfg = client.post("/settings/ai-apis", json={
        "name": "Temp", "api_type": "anthropic", "model": "claude-opus-4-8",
    }).json()
    client.patch("/settings", json={"ai_guides_api": cfg["id"]})
    client.delete(f"/settings/ai-apis/{cfg['id']}")

    with pytest.raises(generation.MissingApiKeyError, match="no longer exists"):
        generation.load_guides_config(db)


def test_endpoint_503_when_config_wrong_type(client, db):
    """End-to-end: the router's eager check uses the same resolver, so a
    misconfigured assignment 503s before any job is even started."""
    _enable(db)
    cfg = client.post("/settings/ai-apis", json={
        "name": "Local Ollama", "api_type": "openai", "url": "http://x:11434", "model": "llama3",
    }).json()
    client.patch("/settings", json={"ai_guides_api": cfg["id"]})

    guide = client.post(
        "/painting/guides", json={"slug": "g-cfg", "title": "G", "tabs": []}
    ).json()
    r = client.post(f"/painting/guides/{guide['id']}/draft")
    assert r.status_code == 503
    assert "Anthropic" in r.json()["detail"]

"""AI Organize — Anthropic-API support and endpoint wiring.

The Anthropic client is monkeypatched at the `ai_organize.Anthropic` boundary
(same pattern as the painting generator's tests); no live API call is made.
"""
import json
import types

import app.services.ai_organize as ai
from app.models import Model, STLFile


def _resp(text: str):
    """Mimic an Anthropic Messages response: content = [text block]."""
    block = types.SimpleNamespace(type="text", text=text)
    return types.SimpleNamespace(content=[block])


def _fake_anthropic(text: str, captured: dict | None = None):
    """A drop-in for the Anthropic class returning a canned text block."""
    class _Client:
        def __init__(self, **kw):
            self._kw = kw

        @property
        def messages(self):
            def create(**kwargs):
                if captured is not None:
                    captured["ctor"] = self._kw
                    captured["create"] = kwargs
                return _resp(text)
            return types.SimpleNamespace(create=create)

    return _Client


_UNRESOLVED = [{"id": 1, "filename": "mystery_blob.stl", "part_type": None, "part_name": None}]


def test_redact_url_strips_credentials():
    assert ai._redact_url("https://user:secret@host:11434/v1") == "https://host:11434/v1"
    assert ai._redact_url("http://ollama:11434/v1/chat") == "http://ollama:11434/v1/chat"
    # userinfo without an explicit port
    assert ai._redact_url("https://bob:pw@example.com/api") == "https://example.com/api"


def test_openai_timeout_detail_never_leaks_url_credentials(monkeypatch):
    import httpx

    def _boom(*a, **k):
        raise httpx.ConnectError("failed connecting to https://user:secret@host:11434")

    monkeypatch.setattr(ai.httpx, "post", _boom)
    res = ai.run(_UNRESOLVED, "https://user:secret@host:11434", "llama3", "", api_type="openai")
    assert res.llm.status == "error"
    assert "secret" not in (res.llm.detail or "")


def test_anthropic_path_refines_via_sdk(monkeypatch):
    canned = json.dumps({"files": [
        {"id": 1, "part_type": "Head", "part_name": "Helm", "sup_base_filename": None},
    ]})
    monkeypatch.setattr(ai, "Anthropic", _fake_anthropic(canned))

    res = ai.run(_UNRESOLVED, "", "claude-opus-4-8", "sk-ant-x", api_type="anthropic", effort="low")

    assert res.llm.status == "ok"
    by_id = {s["id"]: s for s in res.suggestions}
    assert by_id[1]["part_type"] == "Head"
    assert by_id[1]["part_name"] == "Helm"


def test_anthropic_missing_key_reports_error(monkeypatch):
    # Anthropic must not even be constructed without a key.
    def _boom(**kw):
        raise AssertionError("Anthropic should not be called without a key")
    monkeypatch.setattr(ai, "Anthropic", _boom)

    res = ai.run(_UNRESOLVED, "", "claude-opus-4-8", "", api_type="anthropic")

    assert res.llm.status == "error"
    assert "key" in (res.llm.detail or "").lower()
    # Heuristic suggestions are still returned.
    assert any(s["id"] == 1 for s in res.suggestions)


def test_anthropic_effort_maps_to_thinking_budget(monkeypatch):
    captured: dict = {}
    canned = json.dumps({"files": []})
    monkeypatch.setattr(ai, "Anthropic", _fake_anthropic(canned, captured))

    ai.run(_UNRESOLVED, "", "claude-opus-4-8", "sk-ant-x", api_type="anthropic", effort="high")

    assert captured["create"]["thinking"] == {"type": "enabled", "budget_tokens": 10000}
    # low effort sends no thinking block
    captured.clear()
    ai.run(_UNRESOLVED, "", "claude-opus-4-8", "sk-ant-x", api_type="anthropic", effort="low")
    assert "thinking" not in captured["create"]


def test_endpoint_drives_anthropic_config(client, db, monkeypatch):
    """End-to-end: an assigned Anthropic config reaches the runner and returns
    suggestions with llm_status='ok'."""
    m = Model(name="Anthropic Mini", folder_path="/lib/anthropic")
    db.add(m)
    db.flush()
    f = STLFile(model_id=m.id, filename="mystery_blob.stl", path="/lib/anthropic/mystery_blob.stl")
    db.add(f)
    db.commit()

    canned = json.dumps({"files": [
        {"id": f.id, "part_type": "Weapon", "part_name": "Blade", "sup_base_filename": None},
    ]})
    monkeypatch.setattr(ai, "Anthropic", _fake_anthropic(canned))

    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude", "api_type": "anthropic",
        "model": "claude-opus-4-8", "effort": "low",
    }).json()
    assert client.post(f"/settings/ai-apis/{cfg['id']}/key",
                       json={"key": "sk-ant-test"}).status_code == 200
    client.patch("/settings", json={"ai_organize_enabled": True, "ai_organize_api": cfg["id"]})

    r = client.post(f"/models/{m.id}/ai-organize")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_status"] == "ok"
    sug = {s["id"]: s for s in body["suggestions"]}
    assert sug[f.id]["part_type"] == "Weapon"


# --- Success-via-API-or-nothing (#821): the endpoint never substitutes
# heuristic-only suggestions for a non-"ok" LLM outcome, even though the
# service layer (ai_organize.run) computes and returns them internally. ---

def _seeded_model(db, filename="mystery_blob.stl"):
    m = Model(name="Endpoint Test", folder_path="/lib/endpoint")
    db.add(m)
    db.flush()
    f = STLFile(model_id=m.id, filename=filename, path=f"/lib/endpoint/{filename}")
    db.add(f)
    db.commit()
    return m, f


def test_endpoint_returns_empty_suggestions_on_llm_error(client, db, monkeypatch):
    m, f = _seeded_model(db)
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(
        ai.httpx.ConnectError("connection refused")
    ))
    cfg = client.post("/settings/ai-apis", json={
        "name": "Ollama", "api_type": "openai", "url": "http://x:11434", "model": "llama3",
    }).json()
    client.patch("/settings", json={"ai_organize_enabled": True, "ai_organize_api": cfg["id"]})

    r = client.post(f"/models/{m.id}/ai-organize")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_status"] == "error"
    assert body["llm_detail"]
    assert body["suggestions"] == []


def test_endpoint_returns_empty_suggestions_when_disabled(client, db):
    m, f = _seeded_model(db)
    # ai_organize_enabled is left False (the default) — the resolver itself
    # would 400 if we called it directly, but the endpoint requires it be
    # enabled to even attempt a run, so this exercises the "disabled" outcome
    # via a config assigned with no model set (never becomes llm_ready).
    cfg = client.post("/settings/ai-apis", json={
        "name": "Ollama", "api_type": "openai", "url": "http://x:11434", "model": "",
    }).json()
    client.patch("/settings", json={"ai_organize_enabled": True, "ai_organize_api": cfg["id"]})

    r = client.post(f"/models/{m.id}/ai-organize")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_status"] == "disabled"
    assert body["llm_detail"]
    assert body["suggestions"] == []


def test_endpoint_returns_empty_suggestions_when_skipped(client, db):
    """A well-named file that heuristics fully resolve needs no AI call —
    llm_status is 'skipped', and per #821 that still means zero suggestions,
    not the heuristic guess presented as an AI result."""
    m, f = _seeded_model(db, filename="Sword_of_Truth.stl")  # heuristics resolve this: Weapon
    cfg = client.post("/settings/ai-apis", json={
        "name": "Ollama", "api_type": "openai", "url": "http://x:11434", "model": "llama3",
    }).json()
    client.patch("/settings", json={"ai_organize_enabled": True, "ai_organize_api": cfg["id"]})

    r = client.post(f"/models/{m.id}/ai-organize")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_status"] == "skipped"
    assert body["llm_detail"]
    assert body["suggestions"] == []


def test_openai_path_refines_via_httpx(monkeypatch):
    """Regression for the OpenAI-compatible path after the openai/anthropic split."""
    content = json.dumps({"files": [
        {"id": 1, "part_type": "Base", "part_name": "Plinth", "sup_base_filename": None},
    ]})

    class _Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp())

    res = ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "ok"
    assert {s["id"]: s for s in res.suggestions}[1]["part_type"] == "Base"


def test_endpoint_anthropic_without_model_is_400(client, db):
    m = Model(name="No Model", folder_path="/lib/nm")
    db.add(m)
    db.flush()
    db.add(STLFile(model_id=m.id, filename="mystery_blob.stl", path="/lib/nm/mystery_blob.stl"))
    db.commit()

    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude", "api_type": "anthropic", "model": "",
    }).json()
    client.patch("/settings", json={"ai_organize_enabled": True, "ai_organize_api": cfg["id"]})

    r = client.post(f"/models/{m.id}/ai-organize")
    assert r.status_code == 400
    assert "model" in r.json()["detail"].lower()

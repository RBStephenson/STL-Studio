"""AI Organize — Anthropic-API support and endpoint wiring.

The Anthropic client is monkeypatched at the `ai_organize.Anthropic` boundary
(same pattern as the painting generator's tests); no live API call is made.
"""
import json
import logging
import types

import pytest

import app.services.ai_organize as ai
from app.models import Model, STLFile
from app.routers.models import _normalize_type


class _ListHandler(logging.Handler):
    """Collects formatted log records in a list."""
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(self.format(record))


@pytest.fixture
def ai_organize_logs():
    """Capture ai_organize's log output directly on its own logger.

    The app's `logging_config.configure_logging` deliberately sets
    `propagate = False` on the top-level "app" logger (to avoid duplicate
    lines with uvicorn's own root handler) — which also means pytest's
    caplog, which listens via a handler on the *root* logger, never sees
    anything the app logs. Attaching directly to ai_organize's own logger
    sidesteps that entirely.
    """
    handler = _ListHandler()
    ai._log.addHandler(handler)
    try:
        yield handler
    finally:
        ai._log.removeHandler(handler)


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


def test_anthropic_all_thinking_no_text_logs_stop_reason(monkeypatch, ai_organize_logs):
    """Mirrors the OpenAI path's empty-content diagnostic: if the reply is
    all "thinking" blocks and no "text" block, stop_reason plus the block
    types actually returned must be visible to diagnose it."""
    thinking_block = types.SimpleNamespace(type="thinking", text=None)
    resp = types.SimpleNamespace(content=[thinking_block], stop_reason="max_tokens")

    class _Client:
        def __init__(self, **kw):
            pass

        @property
        def messages(self):
            return types.SimpleNamespace(create=lambda **kw: resp)

    monkeypatch.setattr(ai, "Anthropic", _Client)

    res = ai.run(_UNRESOLVED, "", "claude-opus-4-8", "sk-ant-x", api_type="anthropic")

    assert res.llm.status == "error"
    assert "max_tokens" in res.llm.detail
    assert any("thinking" in m for m in ai_organize_logs.messages)


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
    """A model made entirely of Sup_ (presupported) files has nothing to send
    the AI — those files inherit their base file's category instead of being
    sent themselves. llm_status is 'skipped', and per #821 that still means
    zero suggestions, not the heuristic guess presented as an AI result."""
    m, f = _seeded_model(db, filename="Sup_Sword.stl")
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


def test_openai_path_caps_max_tokens(monkeypatch):
    """A local model with nothing bounding its reply can run away generating
    tokens until it hits the *server's* own context limit, minutes later,
    with a truncated/unparseable response as the only result. max_tokens
    must always be sent so a misbehaving model fails fast instead."""
    captured: dict = {}
    content = json.dumps({"files": []})

    def _fake_post(url, **kwargs):
        captured["payload"] = kwargs["json"]

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert captured["payload"]["max_tokens"] == ai._OPENAI_MAX_TOKENS


def test_openai_path_disables_thinking(monkeypatch):
    """Nothing to reason about for this task (filename pattern-matching) —
    disabling it where the server supports the knob avoids a reasoning
    model spending its whole max_tokens budget on hidden thinking and
    emitting nothing into content at all (#903-follow-up)."""
    captured: dict = {}
    content = json.dumps({"files": []})

    def _fake_post(url, **kwargs):
        captured["payload"] = kwargs["json"]

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert captured["payload"]["think"] is False


def test_openai_path_disables_reasoning_effort(monkeypatch):
    """"think" is the native Ollama /api/chat field and is NOT read by the
    OpenAI-compatible /v1/chat/completions endpoint at all (ollama/ollama
    #15288) — the field that endpoint actually reads is "reasoning_effort",
    with "none" as the documented value to disable thinking (ollama/ollama
    #14820). Without this, "think": false alone is a silent no-op against
    the exact endpoint we call, and the #903 empty-content bug can recur on
    any model whose reasoning Ollama routes through this mechanism."""
    captured: dict = {}
    content = json.dumps({"files": []})

    def _fake_post(url, **kwargs):
        captured["payload"] = kwargs["json"]

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert captured["payload"]["reasoning_effort"] == "none"


def test_openai_path_retries_without_reasoning_effort_on_400(monkeypatch):
    """A strict server that rejects the unrecognized "reasoning_effort" field
    outright gets one retry with it stripped — mirrors the existing
    response_format/think retries."""
    calls: list[dict] = []
    content = json.dumps({"files": []})

    def _fake_post(url, **kwargs):
        calls.append(dict(kwargs["json"]))

        class _Resp:
            def __init__(self, status_code, text, body=None):
                self.status_code = status_code
                self.is_success = status_code == 200
                self.text = text
                self._body = body

            def json(self):
                return self._body
        if len(calls) == 1:
            return _Resp(400, "unknown field: reasoning_effort")
        return _Resp(200, "", {"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "ok"
    assert len(calls) == 2
    assert "reasoning_effort" in calls[0]
    assert "reasoning_effort" not in calls[1]


def test_run_reasoning_enabled_omits_the_suppression_fields(monkeypatch):
    """reasoning_enabled=True (opt-in via AiApiConfig, #939-follow-up) skips
    both "think": false and "reasoning_effort": "none" entirely, letting a
    thinking-capable model reason before answering instead of forcing it off."""
    captured: dict = {}
    content = json.dumps({"files": []})

    def _fake_post(url, **kwargs):
        captured["payload"] = kwargs["json"]

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    ai.run(
        _UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai",
        reasoning_enabled=True,
    )

    assert "think" not in captured["payload"]
    assert "reasoning_effort" not in captured["payload"]


def test_run_reasoning_disabled_by_default(monkeypatch):
    """Default (no reasoning_enabled passed) keeps the existing suppression —
    a caller that hasn't set up the new config field must not silently start
    letting models reason."""
    captured: dict = {}
    content = json.dumps({"files": []})

    def _fake_post(url, **kwargs):
        captured["payload"] = kwargs["json"]

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert captured["payload"]["think"] is False
    assert captured["payload"]["reasoning_effort"] == "none"


def test_both_system_prompts_instruct_against_reasoning():
    """A model whose chat template reasons unconditionally, ignoring the
    "think": False API field entirely, will often still respect a plain-
    language instruction in the prompt text itself — cheap, independent
    insurance against the same failure mode (#910-follow-up)."""
    for prompt in (ai._SYSTEM_PROMPT, ai._UNIT_SYSTEM_PROMPT):
        assert "do not think" in prompt.lower()


def test_openai_path_sends_json_schema_for_parts_strategy(monkeypatch):
    """Schema-constrained decoding forces the exact "files"/"part_type" shape
    via the request itself, rather than hoping the model's own output
    matches the prompt's written format instructions — a model can drift to
    inventing its own key names even while producing well-formed JSON
    (#910-follow-up)."""
    captured: dict = {}
    content = json.dumps({"files": []})

    def _fake_post(url, **kwargs):
        captured["payload"] = kwargs["json"]

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai", strategy="parts")

    rf = captured["payload"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"] == ai._PARTS_JSON_SCHEMA


def test_openai_path_sends_json_schema_for_unit_strategy(monkeypatch):
    content = json.dumps({"units": [], "unknown": []})

    def _fake_post(url, **kwargs):
        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    captured: dict = {}
    real_post = _fake_post

    def _spy_post(url, **kwargs):
        captured["payload"] = kwargs["json"]
        return real_post(url, **kwargs)

    monkeypatch.setattr(ai.httpx, "post", _spy_post)
    ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    rf = captured["payload"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"] == ai._UNIT_JSON_SCHEMA


def test_openai_path_retries_without_think_on_400(monkeypatch):
    """A strict server that rejects the unrecognized "think" field outright
    (rather than just ignoring it) gets one retry with it stripped —
    mirrors the existing response_format retry."""
    calls: list[dict] = []
    content = json.dumps({"files": []})

    def _fake_post(url, **kwargs):
        calls.append(dict(kwargs["json"]))  # snapshot — payload is mutated in place on retry

        class _Resp:
            def __init__(self, status_code, text, body=None):
                self.status_code = status_code
                self.is_success = status_code == 200
                self.text = text
                self._body = body

            def json(self):
                return self._body
        if len(calls) == 1:
            return _Resp(400, "unknown field: think")
        return _Resp(200, "", {"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "ok"
    assert len(calls) == 2
    assert "think" in calls[0]
    assert "think" not in calls[1]


def test_openai_path_empty_content_logs_finish_reason_and_message(monkeypatch, ai_organize_logs):
    """A reasoning model can spend its entire max_tokens budget "thinking"
    and emit nothing into content — request still succeeds (status 200)
    with nothing to show for it. finish_reason + the full message object
    must be visible to diagnose this, not just a generic empty-reply error."""
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: type(
        "R", (), {
            "status_code": 200, "is_success": True, "text": "",
            "json": lambda self: {"choices": [{
                "finish_reason": "length",
                "message": {"content": "", "reasoning_content": "Let me think about this..."},
            }]},
        },
    )())

    res = ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "error"
    assert "length" in res.llm.detail
    assert any("reasoning_content" in m and "Let me think" in m for m in ai_organize_logs.messages)


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


# --- The AI is never skipped just because heuristics fully resolved a file ---

def test_llm_still_called_when_heuristics_fully_resolve_the_file(monkeypatch):
    """A well-named file that heuristics fully resolve (type AND name) must
    still be sent to the AI — it may still be able to correct a wrong
    heuristic guess or fix the name; "resolved" coverage of part_type alone
    doesn't mean the suggestion is actually correct."""
    resolved = [{"id": 1, "filename": "Sword_of_Truth.stl", "part_type": None, "part_name": None}]
    canned = json.dumps({"files": [
        {"id": 1, "part_type": "Weapon", "part_name": "Sword of Truth", "sup_base_filename": None},
    ]})
    captured: dict = {}

    def _fake_post(url, **kwargs):
        captured["payload"] = json.loads(kwargs["json"]["messages"][1]["content"])

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": canned}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(resolved, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "ok"
    # The heuristic already resolved this file (Weapon/"Sword of Truth" from
    # naming rules) — it was still sent to the LLM, not skipped.
    assert captured["payload"][0]["id"] == 1


def test_llm_receives_heuristic_suggestion_not_raw_none(monkeypatch):
    """Candidates sent to the LLM carry the heuristic-computed part_type/
    part_name (matching what the system prompt claims), not the original
    (often null) stored values."""
    files = [{"id": 1, "filename": "Sword_of_Truth.stl", "part_type": None, "part_name": None}]
    captured: dict = {}

    def _fake_post(url, **kwargs):
        captured["payload"] = json.loads(kwargs["json"]["messages"][1]["content"])
        content = json.dumps({"files": []})

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai")

    sent = captured["payload"][0]
    assert sent["part_type"] == "Weapon"  # heuristic-inferred, not None


# --- Dedupe scale/version variants before hitting the LLM ---

def test_llm_dedupes_scale_variants_of_the_same_part(monkeypatch):
    """Head_28mm.stl and Head_75mm.stl are the same physical part at
    different scales — both clean to "Head" — so only one representative
    should reach the LLM; its answer must still land on both ids."""
    files = [
        {"id": 1, "filename": "Head_28mm.stl", "part_type": None, "part_name": None},
        {"id": 2, "filename": "Head_75mm.stl", "part_type": None, "part_name": None},
        {"id": 3, "filename": "Sword_of_Truth.stl", "part_type": None, "part_name": None},
    ]
    sent: list[list[dict]] = []

    def _fake_post(url, **kwargs):
        payload = json.loads(kwargs["json"]["messages"][1]["content"])
        sent.append(payload)
        content = json.dumps({"files": [
            {"id": f["id"], "part_type": f["part_type"], "part_name": "refined", "sup_base_filename": None}
            for f in payload
        ]})

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "ok"
    # 3 candidates collapsed to 2 — only one Head sent, not both scales.
    assert len(sent) == 1
    assert len(sent[0]) == 2

    by_id = {s["id"]: s for s in res.suggestions}
    assert by_id[1]["part_type"] == "Head"
    assert by_id[2]["part_type"] == "Head"
    assert by_id[1]["part_name"] == "refined"
    assert by_id[2]["part_name"] == "refined"   # copied from the representative
    assert by_id[3]["part_type"] == "Weapon"


def test_llm_dedupe_preserved_across_unit_strategy_batches(monkeypatch):
    """The same dedupe applies to the unit strategy's batched path."""
    files = [
        {"id": 1, "filename": "Royal_Guard_1_Head_28mm.stl", "part_type": None, "part_name": None},
        {"id": 2, "filename": "Royal_Guard_1_Head_75mm.stl", "part_type": None, "part_name": None},
    ]
    sent: list[list[dict]] = []

    def _fake_post(url, **kwargs):
        content_text = kwargs["json"]["messages"][1]["content"]
        payload = json.loads(content_text.split("\n\n")[-1])
        sent.append(payload)
        content = json.dumps({"files": [
            {"id": f["id"], "part_type": "royal guard 1", "part_name": None, "sup_base_filename": None}
            for f in payload
        ]})

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "ok"
    assert len(sent) == 1
    assert len(sent[0]) == 1  # both scales collapsed to one representative
    assert {s["id"] for s in res.suggestions} == {1, 2}
    assert all(s["part_type"] == "Royal Guard 1" for s in res.suggestions)


def test_skipped_only_when_every_file_is_a_sup_variant():
    """The true 'skipped' case: nothing eligible to send at all."""
    files = [{"id": 1, "filename": "Sup_Sword.stl", "part_type": None, "part_name": None}]
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai")
    assert res.llm.status == "skipped"


def test_system_prompt_lists_the_canonical_categories():
    for cat in ai.CANONICAL_PART_TYPES:
        assert cat in ai._SYSTEM_PROMPT
    # And not the old, mismatched hardcoded list this replaced.
    assert "Accessory," not in ai._SYSTEM_PROMPT
    assert "Shoulder" not in ai._SYSTEM_PROMPT


def test_full_is_a_canonical_category():
    """"Full" (a single presupported/complete-figure file, as opposed to a
    part broken out separately) is a first-class category, not just a
    heuristic guess — must be selectable/snappable like any other."""
    assert "Full" in ai.CANONICAL_PART_TYPES


# --- Unit-based strategy (#878) ---

def test_to_pascal_case_title_cases_each_word():
    assert ai._to_pascal_case("royal guard 1") == "Royal Guard 1"
    assert ai._to_pascal_case("ROYAL GUARD 1") == "Royal Guard 1"
    assert ai._to_pascal_case("Royal Guard 1") == "Royal Guard 1"
    assert ai._to_pascal_case("royal_guard-1") == "Royal Guard 1"
    assert ai._to_pascal_case("  ogre   champion  ") == "Ogre Champion"


# --- Unit strategy's grouped response format (#894-follow-up) ---
# A unit's name is often several words ("Ogre Champion With Great Weapon") and
# used to get repeated verbatim on every one of that unit's files — stated
# once per group instead is a direct, unbounded-with-unit-size token win.

def test_unit_system_prompt_has_no_sup_base_filename():
    """Sup_ files are excluded from every candidate batch (both strategies),
    so this field could only ever come back null — dead weight in both the
    prompt and every response object. Dropped entirely from the unit prompt."""
    assert "sup_base_filename" not in ai._UNIT_SYSTEM_PROMPT


def test_parse_unit_suggestions_flattens_groups():
    raw = json.dumps({
        "units": [
            {"name": "Ogre Champion", "members": [
                {"id": 1, "part_name": "Head"},
                {"id": 2, "part_name": "Weapon"},
            ]},
            {"name": "Royal Guard 1", "members": [
                {"id": 3, "part_name": "Torso"},
            ]},
        ],
        "unknown": [4],
    })
    outcome = ai._parse_unit_suggestions(raw, "test")

    assert outcome.status == "ok"
    by_id = {s["id"]: s for s in outcome.suggestions}
    assert by_id[1] == {"id": 1, "part_type": "Ogre Champion", "part_name": "Head", "sup_base_filename": None}
    assert by_id[2]["part_type"] == "Ogre Champion"
    assert by_id[3]["part_type"] == "Royal Guard 1"
    assert by_id[4] == {"id": 4, "part_type": None, "part_name": None, "sup_base_filename": None}


def test_parse_unit_suggestions_falls_back_to_flat_format():
    """A model that ignores the grouped format and replies in the older flat
    {"files": [...]} shape anyway must still parse — cheap insurance against
    a model that's simply more reliable with the shape it's seen more of in
    training."""
    raw = json.dumps({"files": [
        {"id": 1, "part_type": "Ogre Champion", "part_name": "Head", "sup_base_filename": None},
    ]})
    outcome = ai._parse_unit_suggestions(raw, "test")
    assert outcome.status == "ok"
    assert outcome.suggestions[0]["part_type"] == "Ogre Champion"


# --- Best-effort JSON repair on a parse failure (#928-follow-up) ---
# Cheap insurance against an otherwise-good reply with one stray syntax
# slip — a trailing comma, or prose wrapped around an otherwise-valid object
# despite being told to return only JSON.

def test_repairs_trailing_comma_before_closing_bracket():
    assert ai._repair_json('{"files": [{"id": 1},]}') == '{"files": [{"id": 1}]}'
    assert ai._repair_json('{"files": [{"id": 1, "part_type": "Head",}]}') == \
        '{"files": [{"id": 1, "part_type": "Head"}]}'


def test_repairs_prose_wrapped_around_the_json_object():
    wrapped = 'Sure, here you go:\n{"files": [{"id": 1}]}\nHope that helps!'
    assert ai._repair_json(wrapped) == '{"files": [{"id": 1}]}'


def test_trailing_comma_reply_recovers_instead_of_erroring(monkeypatch):
    """The actual end-to-end path: a reply that would otherwise fail
    json.loads outright recovers via the repair pass and returns real
    suggestions, not an error."""
    content = '{"files": [{"id": 1, "part_type": "Weapon", "part_name": "Sword", "sup_base_filename": null},]}'
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: type(
        "R", (), {
            "status_code": 200, "is_success": True, "text": "",
            "json": lambda self: {"choices": [{"message": {"content": content}}]},
        },
    )())

    res = ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "ok"
    assert {s["id"]: s for s in res.suggestions}[1]["part_type"] == "Weapon"


def test_repair_logs_recovery_at_info_level(monkeypatch, ai_organize_logs):
    content = '{"files": [{"id": 1, "part_type": "Weapon", "part_name": "Sword", "sup_base_filename": null},]}'
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: type(
        "R", (), {
            "status_code": 200, "is_success": True, "text": "",
            "json": lambda self: {"choices": [{"message": {"content": content}}]},
        },
    )())

    ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert any("llm_repaired" in m for m in ai_organize_logs.messages)


def test_repair_does_not_mask_genuinely_truncated_json(monkeypatch, ai_organize_logs):
    """Truncated mid-object JSON (cut off by max_tokens) isn't something the
    narrow repair pass can recover — must still report the original error,
    not silently swallow it or return partial/wrong data."""
    truncated = '{"files": [{"id": 1, "part_type": "Wea'
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: type(
        "R", (), {
            "status_code": 200, "is_success": True, "text": "",
            "json": lambda self: {"choices": [{"message": {"content": truncated}}]},
        },
    )())

    res = ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "error"
    assert not any("llm_repaired" in m for m in ai_organize_logs.messages)


# --- Logging the actual reply on a parse failure (#894-follow-up) ---
# "LLM returned non-JSON content" alone doesn't say whether the model
# rambled prose, got stuck repeating itself, or was cut off mid-object by
# max_tokens — seeing the raw reply is the only way to tell which, and it
# must show up without needing DEBUG-level logging turned on.

def test_non_json_reply_logs_the_raw_text(monkeypatch, ai_organize_logs):
    garbage = "Sure! Here are the categorized files: " + "blah " * 20
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: type(
        "R", (), {
            "status_code": 200, "is_success": True, "text": "",
            "json": lambda self: {"choices": [{"message": {"content": garbage}}]},
        },
    )())

    res = ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "error"
    assert any("blah blah blah" in m for m in ai_organize_logs.messages)


def test_malformed_files_field_logs_the_parsed_json(monkeypatch, ai_organize_logs):
    """Valid JSON, wrong shape (files isn't a list) — same visibility need."""
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: type(
        "R", (), {
            "status_code": 200, "is_success": True, "text": "",
            "json": lambda self: {"choices": [{"message": {
                "content": json.dumps({"files": "not-a-list"}),
            }}]},
        },
    )())

    res = ai.run(_UNRESOLVED, "http://ollama:11434", "llama3", "", api_type="openai")

    assert res.llm.status == "error"
    assert any("not-a-list" in m for m in ai_organize_logs.messages)


def test_malformed_unit_response_logs_the_parsed_json(monkeypatch, ai_organize_logs):
    """Same check for the unit strategy's own malformed-shape branch."""
    files = [{"id": 1, "filename": "Sword_of_Truth.stl", "part_type": None, "part_name": None}]
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: type(
        "R", (), {
            "status_code": 200, "is_success": True, "text": "",
            "json": lambda self: {"choices": [{"message": {
                "content": json.dumps(["not", "a", "dict"]),
            }}]},
        },
    )())

    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "error"
    assert any("not" in m and "dict" in m for m in ai_organize_logs.messages)


def test_unit_strategy_end_to_end_with_grouped_response(monkeypatch):
    """Full run() through the OpenAI-compatible path with a real grouped
    response — Pascal-casing still applies to the flattened part_type."""
    files = [
        {"id": 1, "filename": "Royal_Guard_1_Head.stl", "part_type": None, "part_name": None},
        {"id": 2, "filename": "Royal_Guard_1_Weapon.stl", "part_type": None, "part_name": None},
    ]
    canned = json.dumps({"units": [
        {"name": "royal guard 1", "members": [
            {"id": 1, "part_name": "Head"},
            {"id": 2, "part_name": "Weapon"},
        ]},
    ], "unknown": []})

    class _Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": canned}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp())
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "ok"
    by_id = {s["id"]: s for s in res.suggestions}
    assert by_id[1]["part_type"] == "Royal Guard 1"
    assert by_id[2]["part_type"] == "Royal Guard 1"
    # part_name is prefixed with the unit name (#941) so it's unambiguous
    # wherever it's shown without part_type alongside it — the LLM's bare
    # "Head" alone doesn't say which unit's head it is.
    assert by_id[1]["part_name"] == "Royal Guard 1 Head"
    assert by_id[2]["part_name"] == "Royal Guard 1 Weapon"


def test_prefix_unit_name_composes_unit_and_part():
    assert ai._prefix_unit_name("Royal Guard 1", "Head") == "Royal Guard 1 Head"


def test_prefix_unit_name_avoids_double_prefixing():
    """A model that ignores the prompt's "bare part label" instruction and
    includes the unit name anyway must not get it prefixed twice."""
    assert ai._prefix_unit_name("Royal Guard 1", "Royal Guard 1 Head") == "Royal Guard 1 Head"
    # Case-insensitive: the model's casing may not match _to_pascal_case's.
    assert ai._prefix_unit_name("Royal Guard 1", "royal guard 1 head") == "royal guard 1 head"


def test_prefix_unit_name_passes_through_empty():
    assert ai._prefix_unit_name("Royal Guard 1", "") == ""


def test_prefix_unit_name_drops_redundant_part_name():
    """A single-file "unit" commonly gets a part_name that's just the unit
    name's own distinguishing word — naive concatenation produced "Escaraba
    Flamer Flamer" (#942-follow-up). The unit name alone already says
    everything the part_name would add, so it's used as-is."""
    assert ai._prefix_unit_name("Escaraba Flamer", "Flamer") == "Escaraba Flamer"


def test_prefix_unit_name_drops_redundant_part_name_regardless_of_spacing():
    """Redundancy is checked on normalized (punctuation/whitespace-stripped)
    text, so "Leftarm" in the unit name still matches "Left Arm" in
    part_name — the concatenation bug this guards against isn't limited to
    exact-spelling duplicates."""
    assert ai._prefix_unit_name("Escaraba Leftarm 1", "Left Arm") == "Escaraba Leftarm 1"


def test_unit_strategy_run_does_not_double_prefix_when_llm_already_included_unit_name(monkeypatch):
    """End-to-end guard: if the LLM's part_name already starts with the unit
    name despite the prompt, run() must not prefix it a second time."""
    files = [{"id": 1, "filename": "Royal_Guard_1_Head.stl", "part_type": None, "part_name": None}]
    canned = json.dumps({"units": [
        {"name": "Royal Guard 1", "members": [{"id": 1, "part_name": "Royal Guard 1 Head"}]},
    ], "unknown": []})

    class _Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": canned}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp())
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.suggestions[0]["part_name"] == "Royal Guard 1 Head"


def test_unit_strategy_run_drops_redundant_single_file_unit_part_name(monkeypatch):
    """End-to-end regression (#942-follow-up): a single-file "unit" whose
    part_name is just the unit name's own distinguishing word must not come
    back as "Escaraba Flamer Flamer"."""
    files = [{"id": 1, "filename": "Escaraba_Flamer.stl", "part_type": None, "part_name": None}]
    canned = json.dumps({"units": [
        {"name": "Escaraba Flamer", "members": [{"id": 1, "part_name": "Flamer"}]},
    ], "unknown": []})

    class _Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": canned}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp())
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.suggestions[0]["part_name"] == "Escaraba Flamer"


def test_parts_strategy_part_name_is_not_prefixed(monkeypatch):
    """The unit-name prefix is a unit-strategy-only behavior — "parts"
    strategy's part_name (already just a category-scoped label like "Blade")
    must pass through unchanged."""
    files = [{"id": 1, "filename": "mystery_blob.stl", "part_type": None, "part_name": None}]
    canned = json.dumps({"files": [
        {"id": 1, "part_type": "Weapon", "part_name": "Blade", "sup_base_filename": None},
    ]})

    class _Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": canned}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp())
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="parts")

    assert res.suggestions[0]["part_name"] == "Blade"


# --- Every file leaves organize with a real part_name, never empty (#947) ---
# The STL files table shows a dimmed, filename-derived placeholder for an
# empty part_name — but it's only ever a placeholder, never actually saved.
# run() now guarantees a real value gets filled in from the filename whenever
# nothing else (heuristics, the LLM) resolved one.

def test_unit_strategy_unknown_file_gets_auto_derived_name(monkeypatch):
    """A file the LLM couldn't confidently assign a unit to lands in
    "unknown" with no part_name at all — previously left permanently empty.
    Falls back to the same filename-derived name the UI would otherwise only
    ever show as a placeholder."""
    files = [{"id": 1, "filename": "Feathers.stl", "part_type": None, "part_name": None}]
    canned = json.dumps({"units": [], "unknown": [1]})

    class _Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": canned}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp())
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "ok"
    assert res.suggestions[0]["part_name"] == "Feathers"


def test_auto_derived_name_does_not_override_an_existing_one(monkeypatch):
    """The fallback only fills a genuinely empty part_name — it must not
    clobber whatever heuristics/the LLM already resolved."""
    files = [{"id": 1, "filename": "Feathers.stl", "part_type": None, "part_name": None}]
    canned = json.dumps({"files": [
        {"id": 1, "part_type": "Accessories", "part_name": "Plume", "sup_base_filename": None},
    ]})

    class _Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": canned}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp())
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="parts")

    assert res.suggestions[0]["part_name"] == "Plume"


def test_auto_derived_name_skips_a_file_whose_clean_name_is_empty(monkeypatch):
    """A filename with nothing left after cleanup (e.g. all separators, no
    actual words) has no reasonable auto-derived name to fall back to —
    left as-is rather than saving an empty string."""
    files = [{"id": 1, "filename": "____.stl", "part_type": None, "part_name": None}]
    canned = json.dumps({"units": [], "unknown": [1]})

    class _Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": canned}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp())
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "ok"
    assert not res.suggestions[0].get("part_name")


def test_unit_strategy_skips_heuristic_pass(monkeypatch):
    """Unlike "parts", "unit" has no keyword heuristic — and its prompt only
    asks the model to group by filename, so the candidate sent is just
    id/filename: no part_type/part_name key at all, heuristic-inferred or
    otherwise (#894-follow-up: those would just be stale None values, pure
    prompt bloat for a task that doesn't use them)."""
    files = [{"id": 1, "filename": "Sword_of_Truth.stl", "part_type": None, "part_name": None}]
    canned = json.dumps({"units": [
        {"name": "royal guard 1", "members": [{"id": 1, "part_name": "Sword"}]},
    ], "unknown": []})
    captured: dict = {}

    def _fake_post(url, **kwargs):
        captured["payload"] = json.loads(kwargs["json"]["messages"][1]["content"])
        captured["system"] = kwargs["json"]["messages"][0]["content"]

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": canned}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "ok"
    # Candidate is just id/filename — no part_type/part_name key at all.
    assert captured["payload"][0] == {"id": 1, "filename": "Sword_of_Truth.stl"}
    assert captured["system"] == ai._UNIT_SYSTEM_PROMPT


def test_unit_strategy_pascal_cases_the_llm_suggestion(monkeypatch):
    files = [{"id": 1, "filename": "Royal_Guard_1_Head_Female_1.stl", "part_type": None, "part_name": None}]
    canned = json.dumps({"files": [
        {"id": 1, "part_type": "royal guard 1", "part_name": "Head Female", "sup_base_filename": None},
    ]})

    class _Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": canned}}]}

    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: _Resp())
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "ok"
    assert {s["id"]: s for s in res.suggestions}[1]["part_type"] == "Royal Guard 1"


def test_unit_strategy_still_skipped_when_every_file_is_a_sup_variant():
    files = [{"id": 1, "filename": "Sup_Sword.stl", "part_type": None, "part_name": None}]
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")
    assert res.llm.status == "skipped"


# --- Unit strategy: batching past _LLM_FILE_CAP (#884) ---

def test_unit_strategy_batches_and_processes_every_file_past_the_cap(monkeypatch):
    """Regression: a model with more than _UNIT_LLM_FILE_CAP files used to have
    everything past the cap silently dropped — no suggestion at all, since
    unit strategy has no heuristic fallback to catch the rest."""
    n = ai._UNIT_LLM_FILE_CAP + 2  # forces exactly two batches
    files = [
        {"id": i, "filename": f"Royal_Guard_1_Part_{i}.stl", "part_type": None, "part_name": None}
        for i in range(n)
    ]
    calls: list[list[dict]] = []

    def _fake_post(url, **kwargs):
        payload = json.loads(kwargs["json"]["messages"][1]["content"].split("\n\n")[-1])
        calls.append(payload)
        content = json.dumps({"files": [
            {"id": f["id"], "part_type": "royal guard 1", "part_name": None, "sup_base_filename": None}
            for f in payload
        ]})

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "ok"
    assert len(calls) == 2
    assert len(calls[0]) == ai._UNIT_LLM_FILE_CAP
    assert len(calls[1]) == 2
    # Every file got a suggestion — none silently dropped past the cap.
    assert {s["id"] for s in res.suggestions} == set(range(n))
    assert all(s["part_type"] == "Royal Guard 1" for s in res.suggestions)


def test_unit_strategy_later_batch_is_told_the_earlier_batchs_unit_names(monkeypatch):
    """The second (and later) batch's prompt must mention unit names the
    first batch already established, so the LLM reuses them instead of
    inventing a differently-spelled variant for the same physical unit.
    Exercises the grouped response format end to end across batches."""
    n = ai._UNIT_LLM_FILE_CAP + 1
    files = [
        {"id": i, "filename": f"Royal_Guard_1_Part_{i}.stl", "part_type": None, "part_name": None}
        for i in range(n)
    ]
    user_messages: list[str] = []

    def _fake_post(url, **kwargs):
        content_text = kwargs["json"]["messages"][1]["content"]
        user_messages.append(content_text)
        payload = json.loads(content_text.split("\n\n")[-1])
        content = json.dumps({"units": [
            {"name": "Royal Guard 1", "members": [{"id": f["id"], "part_name": None} for f in payload]},
        ], "unknown": []})

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "ok"
    assert {s["id"] for s in res.suggestions} == set(range(n))
    assert all(s["part_type"] == "Royal Guard 1" for s in res.suggestions)
    assert len(user_messages) == 2
    assert "Units already established" not in user_messages[0]
    assert "Royal Guard 1" in user_messages[1]
    assert "Units already established" in user_messages[1]


def test_unit_strategy_stops_and_reports_error_when_any_batch_fails(monkeypatch):
    """success-via-API-or-nothing (#821) holds across the whole batched run:
    if a later batch errors, the entire result is "error" — never a partial
    mix of real suggestions from the first batch plus silence from the rest."""
    n = ai._LLM_FILE_CAP + 3
    files = [
        {"id": i, "filename": f"Royal_Guard_1_Part_{i}.stl", "part_type": None, "part_name": None}
        for i in range(n)
    ]
    call_count = 0

    def _fake_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ai.httpx.ConnectError("connection refused")
        payload = json.loads(kwargs["json"]["messages"][1]["content"].split("\n\n")[-1])
        content = json.dumps({"files": [
            {"id": f["id"], "part_type": "Royal Guard 1", "part_name": None, "sup_base_filename": None}
            for f in payload
        ]})

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(files, "http://ollama:11434", "llama3", "", api_type="openai", strategy="unit")

    assert res.llm.status == "error"
    assert call_count == 2  # stopped after the failing batch — no further batches attempted
    assert res.suggestions == []


def test_run_batch_size_overrides_unit_cap(monkeypatch):
    """A per-connection batch_size overrides _UNIT_LLM_FILE_CAP so a
    fast/reliable endpoint can be configured to send more files per call."""
    override = ai._UNIT_LLM_FILE_CAP + 3
    n = override + 1  # forces exactly two batches at the override size
    files = [
        {"id": i, "filename": f"Royal_Guard_1_Part_{i}.stl", "part_type": None, "part_name": None}
        for i in range(n)
    ]
    calls: list[list[dict]] = []

    def _fake_post(url, **kwargs):
        payload = json.loads(kwargs["json"]["messages"][1]["content"].split("\n\n")[-1])
        calls.append(payload)
        content = json.dumps({"units": [
            {"name": "Royal Guard 1", "members": [{"id": f["id"], "part_name": None} for f in payload]},
        ], "unknown": []})

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    res = ai.run(
        files, "http://ollama:11434", "llama3", "", api_type="openai",
        strategy="unit", batch_size=override,
    )

    assert res.llm.status == "ok"
    assert len(calls) == 2
    assert len(calls[0]) == override
    assert len(calls[1]) == 1


def test_run_batch_size_overrides_parts_cap(monkeypatch):
    """A per-connection batch_size overrides _LLM_FILE_CAP for the "parts"
    strategy's single, un-batched call."""
    override = ai._LLM_FILE_CAP - 5
    n = ai._LLM_FILE_CAP  # more than the override, fewer than the built-in cap
    files = [
        {"id": i, "filename": f"Part_{i}.stl", "part_type": None, "part_name": None}
        for i in range(n)
    ]
    captured: dict = {}

    def _fake_post(url, **kwargs):
        payload = kwargs["json"]["messages"][1]["content"]
        captured["sent"] = json.loads(payload)
        content = json.dumps({"files": []})

        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return _Resp()

    monkeypatch.setattr(ai.httpx, "post", _fake_post)
    ai.run(
        files, "http://ollama:11434", "llama3", "", api_type="openai",
        strategy="parts", batch_size=override,
    )

    assert len(captured["sent"]) == override


def test_endpoint_unit_strategy_skips_canonical_snap(client, db, monkeypatch):
    """A unit name is freeform — it must reach the client exactly as the LLM
    (Pascal-cased) returned it, never snapped toward a canonical part-type
    category the way "parts" strategy suggestions are."""
    m = Model(name="Royal Guard Squad", folder_path="/lib/royal-guard")
    db.add(m)
    db.flush()
    f = STLFile(model_id=m.id, filename="Royal_Guard_1_Head_Female_1.stl",
               path="/lib/royal-guard/Royal_Guard_1_Head_Female_1.stl")
    db.add(f)
    db.commit()

    canned = json.dumps({"files": [
        {"id": f.id, "part_type": "royal guard 1", "part_name": "Head Female", "sup_base_filename": None},
    ]})
    monkeypatch.setattr(ai, "Anthropic", _fake_anthropic(canned))

    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude", "api_type": "anthropic", "model": "claude-opus-4-8", "effort": "low",
    }).json()
    client.post(f"/settings/ai-apis/{cfg['id']}/key", json={"key": "sk-ant-test"})
    client.patch("/settings", json={"ai_organize_enabled": True, "ai_organize_api": cfg["id"]})

    r = client.post(f"/models/{m.id}/ai-organize", json={"strategy": "unit"})
    assert r.status_code == 200
    body = r.json()
    sug = {s["id"]: s for s in body["suggestions"]}
    # Pascal-cased by the service, and NOT snapped to any canonical category.
    assert sug[f.id]["part_type"] == "Royal Guard 1"


def test_endpoint_defaults_to_parts_strategy_when_body_omitted(client, db, monkeypatch):
    """Back-compat: a caller that sends no body (the old contract) still gets
    parts-based behavior, unchanged."""
    m = Model(name="Legacy Caller", folder_path="/lib/legacy")
    db.add(m)
    db.flush()
    f = STLFile(model_id=m.id, filename="mystery_blob.stl", path="/lib/legacy/mystery_blob.stl")
    db.add(f)
    db.commit()

    canned = json.dumps({"files": [
        {"id": f.id, "part_type": "Weapon", "part_name": "Blade", "sup_base_filename": None},
    ]})
    monkeypatch.setattr(ai, "Anthropic", _fake_anthropic(canned))

    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude", "api_type": "anthropic", "model": "claude-opus-4-8", "effort": "low",
    }).json()
    client.post(f"/settings/ai-apis/{cfg['id']}/key", json={"key": "sk-ant-test"})
    client.patch("/settings", json={"ai_organize_enabled": True, "ai_organize_api": cfg["id"]})

    r = client.post(f"/models/{m.id}/ai-organize")  # no body
    assert r.status_code == 200
    assert r.json()["suggestions"][0]["part_type"] == "Weapon"


def test_ai_category_snaps_to_canonical_name_even_in_a_fresh_library(client, db, monkeypatch):
    """No existing STLFile.part_type values are stored anywhere yet — the AI's
    "Accessory" must still snap to the app's canonical "Accessories", not be
    stored as an invented near-miss."""
    m = Model(name="Fresh Library Model", folder_path="/lib/fresh")
    db.add(m)
    db.flush()
    f = STLFile(model_id=m.id, filename="mystery_blob.stl", path="/lib/fresh/mystery_blob.stl")
    db.add(f)
    db.commit()

    canned = json.dumps({"files": [
        {"id": f.id, "part_type": "Accessory", "part_name": "Trinket", "sup_base_filename": None},
    ]})
    monkeypatch.setattr(ai, "Anthropic", _fake_anthropic(canned))

    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude", "api_type": "anthropic", "model": "claude-opus-4-8", "effort": "low",
    }).json()
    client.post(f"/settings/ai-apis/{cfg['id']}/key", json={"key": "sk-ant-test"})
    client.patch("/settings", json={"ai_organize_enabled": True, "ai_organize_api": cfg["id"]})

    r = client.post(f"/models/{m.id}/ai-organize")
    assert r.status_code == 200
    body = r.json()
    sug = {s["id"]: s for s in body["suggestions"]}
    assert sug[f.id]["part_type"] == "Accessories"


def test_ai_category_snaps_to_canonical_even_when_a_stale_non_canonical_value_already_exists(client, db, monkeypatch):
    """Regression (#963): a prior mistake (some other file already stored as
    part_type "Hand", before this normalization existed) must not "shadow"
    the real canonical match. Without prioritizing the canonical list, the
    AI's "Hand" suggestion would exact-match the stale "Hand" already sitting
    in the DB and never reach the singular/plural check that maps it to the
    canonical "Hands"."""
    m = Model(name="Stale Category Model", folder_path="/lib/stale")
    db.add(m)
    db.flush()
    poisoned = STLFile(model_id=m.id, filename="already_hand.stl",
                        path="/lib/stale/already_hand.stl", part_type="Hand")
    target = STLFile(model_id=m.id, filename="hand_r.stl", path="/lib/stale/hand_r.stl")
    db.add_all([poisoned, target])
    db.commit()

    canned = json.dumps({"files": [
        {"id": target.id, "part_type": "Hand", "part_name": "Right Hand", "sup_base_filename": None},
    ]})
    monkeypatch.setattr(ai, "Anthropic", _fake_anthropic(canned))

    cfg = client.post("/settings/ai-apis", json={
        "name": "Claude", "api_type": "anthropic", "model": "claude-opus-4-8", "effort": "low",
    }).json()
    client.post(f"/settings/ai-apis/{cfg['id']}/key", json={"key": "sk-ant-test"})
    client.patch("/settings", json={"ai_organize_enabled": True, "ai_organize_api": cfg["id"]})

    r = client.post(f"/models/{m.id}/ai-organize")
    assert r.status_code == 200
    sug = {s["id"]: s for s in r.json()["suggestions"]}
    assert sug[target.id]["part_type"] == "Hands"


class TestNormalizeType:
    """Direct unit coverage for _normalize_type (#963) — the endpoint tests
    above exercise it end to end; these pin down the priority order itself."""

    def test_exact_match_passthrough(self):
        assert _normalize_type("Weapon", ["Weapon", "Head"]) == "Weapon"

    def test_singular_snaps_to_canonical_plural(self):
        assert _normalize_type("Hand", ["Hands"]) == "Hands"

    def test_singular_snaps_to_canonical_plural_via_es(self):
        assert _normalize_type("Accessory", ai.CANONICAL_PART_TYPES) == "Accessories"

    def test_canonical_match_wins_over_a_stale_exact_match_already_in_db(self):
        # "Hand" is already sitting in `existing` (a prior mistake) — it must
        # not shadow the real canonical "Hands" match.
        existing = sorted(set(ai.CANONICAL_PART_TYPES) | {"Hand"})
        assert _normalize_type("Hand", existing) == "Hands"

    def test_genuinely_custom_category_still_passes_through(self):
        # Not canonical, not a fuzzy variant of anything canonical — a real
        # user-defined category must survive normalization unchanged.
        existing = sorted(set(ai.CANONICAL_PART_TYPES) | {"Trophy Base"})
        assert _normalize_type("Trophy Base", existing) == "Trophy Base"

    def test_no_existing_categories_returns_suggestion_unchanged(self):
        assert _normalize_type("Anything", []) == "Anything"


class TestHeuristicLinkSups:
    """Direct unit coverage for heuristic_link_sups (#967) — the endpoint
    tests below exercise the full round trip; these pin down the matching
    algorithm itself."""

    def _f(self, id_, filename, part_name=None, sup_of_id=None):
        return {"id": id_, "filename": filename, "part_name": part_name, "sup_of_id": sup_of_id}

    def test_matches_a_supported_suffix_to_its_base(self):
        files = [
            self._f(1, "icon-of-flame-2.stl"),
            self._f(2, "icon-of-flame-2-supported.stl"),
        ]
        sugs = ai.heuristic_link_sups(files)
        assert sugs == [{"id": 2, "part_type": None, "part_name": None, "sup_base_filename": "icon-of-flame-2.stl"}]

    def test_matches_by_part_name_when_set_rather_than_filename(self):
        files = [
            self._f(1, "a.stl", part_name="Icon of Flame 2"),
            self._f(2, "b.stl", part_name="Icon of Flame 2 Supported"),
        ]
        sugs = ai.heuristic_link_sups(files)
        assert sugs == [{"id": 2, "part_type": None, "part_name": None, "sup_base_filename": "a.stl"}]

    def test_bare_sup_keyword_matches(self):
        files = [self._f(1, "widget.stl"), self._f(2, "widget-sup.stl")]
        assert ai.heuristic_link_sups(files) == [
            {"id": 2, "part_type": None, "part_name": None, "sup_base_filename": "widget.stl"}
        ]

    def test_hollowed_keyword_matches(self):
        files = [self._f(1, "gargoyle.stl"), self._f(2, "gargoyle-hollowed.stl")]
        assert ai.heuristic_link_sups(files) == [
            {"id": 2, "part_type": None, "part_name": None, "sup_base_filename": "gargoyle.stl"}
        ]

    def test_matches_by_filename_even_when_part_name_is_mislabeled_and_collides(self):
        # Regression (#967-follow-up): real-world data had two *different*
        # physical parts both labeled "Escaraba 1 Base" by part_name (a
        # leftover from an earlier/buggier naming pass), while their
        # filenames were still correct and consistent. Matching by part_name
        # alone either missed this pair or matched it to the wrong base;
        # filename must win.
        files = [
            self._f(1, "escaraba-1-base.stl", part_name="Escaraba 1 Base"),
            self._f(2, "escaraba-hellfyre-base.stl", part_name="Escaraba 1 Base"),  # mislabeled, same as #1
            self._f(3, "escaraba-hellfyre-base-supported.stl", part_name="Supported Escaraba Hellfyre Base"),
        ]
        sugs = ai.heuristic_link_sups(files)
        assert sugs == [
            {"id": 3, "part_type": None, "part_name": None, "sup_base_filename": "escaraba-hellfyre-base.stl"}
        ]

    def test_already_linked_candidate_is_skipped(self):
        # sup_of_id already set (to some other file, id 9) — must not be
        # touched or re-suggested even though a perfect name match exists.
        files = [
            self._f(1, "icon-of-flame-2.stl"),
            self._f(2, "icon-of-flame-2-supported.stl", sup_of_id=9),
        ]
        assert ai.heuristic_link_sups(files) == []

    def test_plain_named_file_is_never_treated_as_a_sup_candidate(self):
        # Neither file has a link keyword — nothing to link, even though
        # "widget" is a substring relationship of sorts.
        files = [self._f(1, "widget.stl"), self._f(2, "widget-extra.stl")]
        assert ai.heuristic_link_sups(files) == []

    def test_no_matching_base_found_yields_no_suggestion(self):
        files = [self._f(1, "orphan-supported.stl")]
        assert ai.heuristic_link_sups(files) == []

    def test_word_boundary_prevents_false_positive_on_superman(self):
        # "sup" must not match inside "Superman" — no word boundary there.
        files = [self._f(1, "hero.stl"), self._f(2, "superman.stl")]
        assert ai.heuristic_link_sups(files) == []

    def test_a_supported_named_file_is_never_used_as_someone_elses_base(self):
        # Two "supported" files that would normally-name-collide with each
        # other after stripping the keyword must not link to each other —
        # only a plain-named file is eligible as a base.
        files = [
            self._f(1, "widget-supported.stl"),
            self._f(2, "widget-hollowed.stl"),
        ]
        assert ai.heuristic_link_sups(files) == []


def test_endpoint_link_sups_strategy_links_unlinked_supported_file(client, db):
    """Full round trip, and critically: no AI API config needed at all for
    this strategy (#967) — unlike "parts"/"unit", which 400 without one."""
    m = Model(name="Flame Cultist", folder_path="/lib/flame-cultist")
    db.add(m)
    db.flush()
    base = STLFile(model_id=m.id, filename="icon-of-flame-2.stl", path="/lib/flame-cultist/icon-of-flame-2.stl")
    sup = STLFile(model_id=m.id, filename="icon-of-flame-2-supported.stl",
                  path="/lib/flame-cultist/icon-of-flame-2-supported.stl")
    db.add_all([base, sup])
    db.commit()

    # Deliberately no AI API config, no ai_organize_enabled — link_sups must
    # not require either.
    r = client.post(f"/models/{m.id}/ai-organize", json={"strategy": "link_sups"})
    assert r.status_code == 200
    body = r.json()
    assert body["llm_status"] == "ok"
    sug = {s["id"]: s for s in body["suggestions"]}
    assert sug[sup.id]["sup_of_id"] == base.id


def test_endpoint_link_sups_apply_writes_sup_of_id(client, db):
    m = Model(name="Flame Cultist", folder_path="/lib/flame-cultist")
    db.add(m)
    db.flush()
    base = STLFile(model_id=m.id, filename="icon-of-flame-2.stl", path="/lib/flame-cultist/icon-of-flame-2.stl")
    sup = STLFile(model_id=m.id, filename="icon-of-flame-2-supported.stl",
                  path="/lib/flame-cultist/icon-of-flame-2-supported.stl")
    db.add_all([base, sup])
    db.commit()

    preview = client.post(f"/models/{m.id}/ai-organize", json={"strategy": "link_sups"}).json()
    items = [{"id": s["id"], "sup_of_id": s["sup_of_id"]} for s in preview["suggestions"]]

    r = client.post(f"/models/{m.id}/ai-organize/apply", json={"items": items})
    assert r.status_code == 200

    db.refresh(sup)
    assert sup.sup_of_id == base.id

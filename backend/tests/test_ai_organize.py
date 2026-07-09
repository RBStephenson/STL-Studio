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
    assert by_id[1]["part_name"] == "Head"
    assert by_id[2]["part_name"] == "Weapon"


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
    """Regression: a model with more than _LLM_FILE_CAP files used to have
    everything past the cap silently dropped — no suggestion at all, since
    unit strategy has no heuristic fallback to catch the rest."""
    n = ai._LLM_FILE_CAP + 5  # forces exactly two batches
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
    assert len(calls[0]) == ai._LLM_FILE_CAP
    assert len(calls[1]) == 5
    # Every file got a suggestion — none silently dropped past the cap.
    assert {s["id"] for s in res.suggestions} == set(range(n))
    assert all(s["part_type"] == "Royal Guard 1" for s in res.suggestions)


def test_unit_strategy_later_batch_is_told_the_earlier_batchs_unit_names(monkeypatch):
    """The second (and later) batch's prompt must mention unit names the
    first batch already established, so the LLM reuses them instead of
    inventing a differently-spelled variant for the same physical unit.
    Exercises the grouped response format end to end across batches."""
    n = ai._LLM_FILE_CAP + 1
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

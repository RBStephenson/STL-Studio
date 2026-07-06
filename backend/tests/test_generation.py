"""AI draft generation — Claude call + parse to GuideDraft (#526).

The Anthropic client is monkeypatched at the boundary; no live API call.
"""
import json
import types

import pytest
from cryptography.fernet import Fernet

from app.models import AppSetting
from app.painting.models import Guide
from app.painting.schemas import GuideDraft
from app.painting.services import generation
from app.services import secrets


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


@pytest.fixture(autouse=True)
def _enabled(db):
    """These tests exercise generate_guide_draft's legacy-fallback path (a
    global ai_api_key, no assigned AiApiConfig) — see test_guides_config.py
    for the named-config resolution itself."""
    db.add(AppSetting(key="ai_guides_enabled", value=True))
    db.commit()


def _guide(db):
    g = Guide(slug="presto", title="Presto", scale="1:6")
    db.add(g)
    db.commit()
    return g


class _StreamCM:
    """Mimics the SDK's `with client.messages.stream(...) as s: s.get_final_message()`."""
    def __init__(self, response, captured=None, kwargs=None):
        self._response = response
        if captured is not None and kwargs is not None:
            captured.update(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._response


def _response(text: str, *, stop_reason: str | None = None):
    block = types.SimpleNamespace(type="text", text=text)
    return types.SimpleNamespace(content=[block], stop_reason=stop_reason)


def _fake_anthropic(text: str, *, stop_reason: str | None = None):
    """A drop-in for the Anthropic class streaming a canned text block."""
    response = _response(text, stop_reason=stop_reason)

    class _Client:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(stream=lambda **kw: _StreamCM(response))

    return _Client


_VALID_DRAFT = json.dumps({
    "title": "Presto",
    "tabs": [{"name": "Skin", "phases": [{"label": "Base", "steps": [
        {"title": "Basecoat", "swatches": [{"name": "Warm Flesh", "value_pct": 55}]}
    ]}]}],
})


def test_generates_and_parses_guidedraft(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")
    monkeypatch.setattr(generation, "Anthropic", _fake_anthropic(_VALID_DRAFT))

    draft = generation.generate_guide_draft(db, _guide(db))

    assert isinstance(draft, GuideDraft)
    assert draft.tabs[0].phases[0].steps[0].swatches[0].name == "Warm Flesh"


def test_strips_code_fence(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")
    fenced = f"```json\n{_VALID_DRAFT}\n```"
    monkeypatch.setattr(generation, "Anthropic", _fake_anthropic(fenced))

    draft = generation.generate_guide_draft(db, _guide(db))
    assert draft.title == "Presto"


def test_missing_key_raises(client, db):
    # No key set.
    with pytest.raises(generation.MissingApiKeyError):
        generation.generate_guide_draft(db, _guide(db))


def test_malformed_json_raises_generation_error(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")
    monkeypatch.setattr(generation, "Anthropic", _fake_anthropic("not json at all"))

    with pytest.raises(generation.GenerationError):
        generation.generate_guide_draft(db, _guide(db))


def test_bad_schema_raises_generation_error(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")
    # Valid JSON, wrong shape (tabs must be a list).
    monkeypatch.setattr(generation, "Anthropic", _fake_anthropic('{"title": "X", "tabs": "nope"}'))

    with pytest.raises(generation.GenerationError):
        generation.generate_guide_draft(db, _guide(db))


def test_api_error_wrapped(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")

    class _Boom:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(
                stream=lambda **kw: (_ for _ in ()).throw(RuntimeError("429 rate limit"))
            )
    monkeypatch.setattr(generation, "Anthropic", _Boom)

    with pytest.raises(generation.GenerationError):
        generation.generate_guide_draft(db, _guide(db))


def test_model_setting_overrides_default(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")
    client.patch("/settings", json={"ai_model": "claude-opus-4-8"})
    captured = {}

    class _Client:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(stream=self._stream)

        def _stream(self, **kw):
            captured["model"] = kw["model"]
            return _StreamCM(_response(_VALID_DRAFT))
    monkeypatch.setattr(generation, "Anthropic", _Client)

    generation.generate_guide_draft(db, _guide(db))
    assert captured["model"] == "claude-opus-4-8"


def _capture_kwargs_client(captured: dict):
    class _Client:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(stream=self._stream)

        def _stream(self, **kw):
            return _StreamCM(_response(_VALID_DRAFT), captured=captured, kwargs=kw)
    return _Client


def test_low_effort_sends_no_thinking(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")
    captured: dict = {}
    monkeypatch.setattr(generation, "Anthropic", _capture_kwargs_client(captured))

    generation.generate_guide_draft(db, _guide(db))  # default effort = low
    assert "thinking" not in captured


def test_high_effort_enables_thinking_budget(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")
    client.patch("/settings", json={"ai_effort": "high"})
    captured: dict = {}
    monkeypatch.setattr(generation, "Anthropic", _capture_kwargs_client(captured))

    generation.generate_guide_draft(db, _guide(db))
    assert captured["thinking"]["type"] == "enabled"
    assert captured["thinking"]["budget_tokens"] == 10000
    # max_tokens must exceed the thinking budget.
    assert captured["max_tokens"] > 10000


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (12, 12), (90, 60, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_no_reference_sends_text_only(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")
    captured: dict = {}
    monkeypatch.setattr(generation, "Anthropic", _capture_kwargs_client(captured))

    generation.generate_guide_draft(db, _guide(db))

    content = captured["messages"][0]["content"]
    assert isinstance(content, str)  # plain text, no image block


def test_reference_image_adds_image_block(client, db, tmp_path, monkeypatch):
    from app.painting.services import images

    monkeypatch.setattr(images, "data_dir", lambda: tmp_path)
    secrets.set_ai_api_key(db, "sk-test")
    guide = _guide(db)
    images.store_upload(db, guide, _png_bytes())
    db.commit()

    captured: dict = {}
    monkeypatch.setattr(generation, "Anthropic", _capture_kwargs_client(captured))

    generation.generate_guide_draft(db, guide)

    content = captured["messages"][0]["content"]
    assert isinstance(content, list)
    kinds = [block["type"] for block in content]
    assert "image" in kinds and "text" in kinds
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["media_type"] == "image/png"
    assert image_block["source"]["type"] == "base64"


def test_truncated_output_raises_clear_error(client, db, monkeypatch):
    secrets.set_ai_api_key(db, "sk-test")
    # A reply cut off at the token ceiling: partial JSON + stop_reason max_tokens.
    monkeypatch.setattr(
        generation, "Anthropic",
        _fake_anthropic(_VALID_DRAFT[:100], stop_reason="max_tokens"),
    )
    with pytest.raises(generation.GenerationError, match="cut off"):
        generation.generate_guide_draft(db, _guide(db))

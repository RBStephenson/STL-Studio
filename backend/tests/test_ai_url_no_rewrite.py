"""#1008: AI/Ollama endpoint URLs must be used exactly as configured — no
silent localhost/127.0.0.1 -> host.docker.internal rewrite, under any
condition. Regression guard for the three call sites that used to do this
rewrite unconditionally (get_organize_models, get_ai_api_config_models,
_llm_refine_openai).
"""
from app.models import AiApiConfig
from app.services import ai_organize


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text

    def json(self):
        return self._json

    @property
    def is_success(self):
        return 200 <= self.status_code < 300


def test_get_organize_models_uses_localhost_url_unmodified(client, db, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse(200, {"data": [{"id": "llama3"}]})

    monkeypatch.setattr("app.routers.settings.httpx.get", fake_get)

    resp = client.get("/settings/ai-organize/models", params={"url": "http://localhost:11434"})
    assert resp.status_code == 200
    assert calls == ["http://localhost:11434/v1/models"]


def test_get_organize_models_uses_127_url_unmodified(client, db, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse(200, {"data": [{"id": "llama3"}]})

    monkeypatch.setattr("app.routers.settings.httpx.get", fake_get)

    resp = client.get("/settings/ai-organize/models", params={"url": "http://127.0.0.1:11434"})
    assert resp.status_code == 200
    assert calls == ["http://127.0.0.1:11434/v1/models"]


def test_get_ai_api_config_models_uses_localhost_url_unmodified(client, db, monkeypatch):
    cfg = AiApiConfig(name="Local Ollama", api_type="openai", url="http://localhost:11434", model="llama3")
    db.add(cfg)
    db.commit()

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse(200, {"data": [{"id": "llama3"}]})

    monkeypatch.setattr("app.routers.settings.httpx.get", fake_get)

    resp = client.get(f"/settings/ai-apis/{cfg.id}/models")
    assert resp.status_code == 200
    assert calls == ["http://localhost:11434/v1/models"]


def test_llm_refine_openai_uses_localhost_url_unmodified(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
        )

    monkeypatch.setattr(ai_organize.httpx, "post", fake_post)

    ai_organize._llm_refine_openai(
        [{"filename": "a.stl"}],
        "http://localhost:11434",
        "llama3",
        "",
    )
    assert calls == ["http://localhost:11434/v1/chat/completions"]


def test_llm_refine_openai_uses_127_url_unmodified(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
        )

    monkeypatch.setattr(ai_organize.httpx, "post", fake_post)

    ai_organize._llm_refine_openai(
        [{"filename": "a.stl"}],
        "http://127.0.0.1:11434",
        "llama3",
        "",
    )
    assert calls == ["http://127.0.0.1:11434/v1/chat/completions"]

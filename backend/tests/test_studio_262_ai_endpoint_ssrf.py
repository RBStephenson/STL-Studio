"""STUDIO-262: AI-endpoint httpx calls must reject metadata/link-local targets
even though loopback/private targets (local Ollama, a LAN AI box) are allowed.
"""
from app.models import AiApiConfig
from app.services import ai_organize


def test_get_organize_models_rejects_link_local_metadata_url(client, db, monkeypatch):
    def fake_get(url, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("httpx.get should not run past the SSRF guard")

    monkeypatch.setattr("app.routers.settings.httpx.get", fake_get)

    resp = client.get(
        "/settings/ai-organize/models", params={"url": "http://169.254.169.254/"}
    )
    assert resp.status_code == 400


def test_get_ai_api_config_models_rejects_link_local_metadata_url(client, db, monkeypatch):
    cfg = AiApiConfig(
        name="Sneaky", api_type="openai", url="http://169.254.169.254", model="llama3"
    )
    db.add(cfg)
    db.commit()

    def fake_get(url, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("httpx.get should not run past the SSRF guard")

    monkeypatch.setattr("app.routers.settings.httpx.get", fake_get)

    resp = client.get(f"/settings/ai-apis/{cfg.id}/models")
    assert resp.status_code == 400


def test_llm_refine_openai_rejects_link_local_metadata_url(monkeypatch):
    def fake_post(url, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("httpx.post should not run past the SSRF guard")

    monkeypatch.setattr(ai_organize.httpx, "post", fake_post)

    outcome = ai_organize._llm_refine_openai(
        [{"filename": "a.stl"}],
        "http://169.254.169.254",
        "llama3",
        "",
    )
    assert outcome.status == "error"

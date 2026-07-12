"""Tests for AI-assisted reorganize field suggestions (STUDIO-186).

Covers the service function (app.services.ai_organize.suggest_reorganize_fields)
and the /reorganize/ai-suggest endpoint. Advisory-only: neither ever writes to
the DB or moves a file — the endpoint only returns suggestions for the caller
to resubmit through the existing /reorganize/preview overrides path.
"""
import json

import app.services.ai_organize as ai
from app.models import Creator, Model, ScanRoot, STLFile
from tests.conftest import make_creator, make_model, make_stl_file


def _fake_openai_post(content: dict):
    def _post(url, **kwargs):
        class _Resp:
            status_code = 200
            is_success = True
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": json.dumps(content)}}]}
        return _Resp()
    return _post


class TestSuggestReorganizeFieldsService:
    def test_disabled_without_llm_configured(self):
        result = ai.suggest_reorganize_fields(
            [{"id": 1, "folder_name": "junk", "filenames": ["a.stl"]}], "", "",
        )
        assert result.llm.status == "disabled"
        assert result.suggestions == []

    def test_skipped_with_no_entries(self):
        result = ai.suggest_reorganize_fields([], "http://x:11434", "llama3")
        assert result.llm.status == "skipped"

    def test_parses_model_suggestions(self, monkeypatch):
        canned = {"models": [
            {"id": 1, "creator": "Abe3D", "character": "Joker", "title": "Bust"},
        ]}
        monkeypatch.setattr(ai.httpx, "post", _fake_openai_post(canned))

        result = ai.suggest_reorganize_fields(
            [{"id": 1, "folder_name": "KS_March_2024_v3", "filenames": ["head.stl"]}],
            "http://x:11434", "llama3",
        )

        assert result.llm.status == "ok"
        assert result.suggestions == [
            {"id": 1, "creator": "Abe3D", "character": "Joker", "title": "Bust"},
        ]

    def test_error_on_llm_failure_returns_no_suggestions(self, monkeypatch):
        monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(
            ai.httpx.ConnectError("connection refused")
        ))

        result = ai.suggest_reorganize_fields(
            [{"id": 1, "folder_name": "junk", "filenames": ["a.stl"]}],
            "http://x:11434", "llama3",
        )

        assert result.llm.status == "error"
        assert result.suggestions == []

    def test_batches_across_the_per_request_cap(self, monkeypatch):
        calls: list[int] = []

        def _post(url, json, **kwargs):
            sent = json["messages"][1]["content"]
            n = sent.count('"id"')
            calls.append(n)
            models = [{"id": i, "creator": None, "character": None, "title": None}
                      for i in range(n)]

            class _Resp:
                status_code = 200
                is_success = True
                text = ""

                def json(self):
                    import json as _json
                    return {"choices": [{"message": {"content": _json.dumps({"models": models})}}]}
            return _Resp()

        monkeypatch.setattr(ai.httpx, "post", _post)
        entries = [{"id": i, "folder_name": f"f{i}", "filenames": []} for i in range(25)]

        result = ai.suggest_reorganize_fields(entries, "http://x:11434", "llama3", batch_size=10)

        assert calls == [10, 10, 5]
        assert result.llm.status == "ok"
        assert len(result.suggestions) == 25


def _root(db, tmp_path):
    db.add(ScanRoot(path=str(tmp_path), enabled=True))
    db.commit()


def _unclassifiable_model(db, tmp_path, folder_name="KS_March_2024_v3"):
    """A model with no creator/character — unclassifiable in the reorganize
    preview — so it's a candidate for AI suggestion."""
    folder = tmp_path / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "mystery_head.stl"
    f.write_bytes(b"solid\nendsolid\n")
    m = Model(name=folder_name, folder_path=str(folder))
    db.add(m)
    db.commit()
    make_stl_file(db, m, filename="mystery_head.stl", path=str(f))
    db.commit()
    return m


class TestAiSuggestEndpoint:
    def test_returns_400_when_flag_disabled(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _unclassifiable_model(db, tmp_path)
        manifest_id = client.get("/reorganize/preview").json()["manifest_id"]

        r = client.post("/reorganize/ai-suggest", json={
            "manifest_id": manifest_id, "model_ids": [m.id],
        })
        assert r.status_code == 400

    def test_skipped_when_no_flagged_entries_requested(self, client, db, tmp_path):
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3D")
        m = make_model(db, creator, name="Bust", character="Joker")
        folder = tmp_path / "Abe3D" / "Joker" / "Bust"
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / "head.stl"
        f.write_bytes(b"solid\nendsolid\n")
        m.folder_path = str(folder)
        db.commit()
        make_stl_file(db, m, filename="head.stl", path=str(f))
        db.commit()

        client.patch("/settings", json={"reorganize_ai_suggestions_enabled": True})
        manifest_id = client.get("/reorganize/preview").json()["manifest_id"]

        r = client.post("/reorganize/ai-suggest", json={
            "manifest_id": manifest_id, "model_ids": [m.id],
        })
        assert r.status_code == 200
        assert r.json() == {"suggestions": [], "llm_status": "skipped", "llm_detail": None}

    def test_returns_suggestions_for_unclassifiable_entry(self, client, db, tmp_path, monkeypatch):
        _root(db, tmp_path)
        m = _unclassifiable_model(db, tmp_path)

        cfg = client.post("/settings/ai-apis", json={
            "name": "Ollama", "api_type": "openai", "url": "http://x:11434", "model": "llama3",
        }).json()
        client.patch("/settings", json={
            "ai_organize_enabled": True, "ai_organize_api": cfg["id"],
            "reorganize_ai_suggestions_enabled": True,
        })

        canned = {"models": [
            {"id": m.id, "creator": "Some Studio", "character": "Mystery Head", "title": "Mystery Head"},
        ]}
        monkeypatch.setattr(ai.httpx, "post", _fake_openai_post(canned))

        manifest_id = client.get("/reorganize/preview").json()["manifest_id"]
        r = client.post("/reorganize/ai-suggest", json={
            "manifest_id": manifest_id, "model_ids": [m.id],
        })

        assert r.status_code == 200
        body = r.json()
        assert body["llm_status"] == "ok"
        assert body["suggestions"] == [
            {"model_id": m.id, "creator": "Some Studio", "character": "Mystery Head", "title": "Mystery Head"},
        ]

    def test_404_on_unknown_manifest(self, client, db):
        client.patch("/settings", json={"reorganize_ai_suggestions_enabled": True})
        r = client.post("/reorganize/ai-suggest", json={
            "manifest_id": "does-not-exist", "model_ids": [1],
        })
        assert r.status_code == 404

    def test_400_over_the_model_cap(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _unclassifiable_model(db, tmp_path)
        client.patch("/settings", json={"reorganize_ai_suggestions_enabled": True})
        manifest_id = client.get("/reorganize/preview").json()["manifest_id"]

        r = client.post("/reorganize/ai-suggest", json={
            "manifest_id": manifest_id, "model_ids": list(range(50)),
        })
        assert r.status_code == 400

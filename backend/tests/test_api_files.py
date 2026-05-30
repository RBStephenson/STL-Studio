"""
Tests for the /files endpoints: image serving, STL serving, zip download.
"""
import io
import zipfile
import pytest
from tests.conftest import make_creator, make_model, make_stl_file


# ---------------------------------------------------------------------------
# /files/download-zip
# ---------------------------------------------------------------------------

class TestDownloadZip:
    def test_empty_file_ids_returns_400(self, client):
        resp = client.post("/files/download-zip", json={"file_ids": [], "zip_name": "Test"})
        assert resp.status_code == 400

    def test_unknown_file_ids_returns_404(self, client):
        resp = client.post("/files/download-zip", json={"file_ids": [99999], "zip_name": "Test"})
        assert resp.status_code == 404

    def test_returns_zip_content_type(self, client, db, tmp_path, monkeypatch):
        # Bypass path-safety check so tmp_path files are served
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)

        stl = tmp_path / "Head_01.stl"
        stl.write_bytes(b"solid head\nendsolid head\n")

        creator = make_creator(db)
        model = make_model(db, creator)
        file_row = make_stl_file(db, model, filename="Head_01.stl", path=str(stl))
        db.commit()

        resp = client.post(
            "/files/download-zip",
            json={"file_ids": [file_row.id], "zip_name": "My Model 2026-05-30"},
        )
        assert resp.status_code == 200
        assert "application/zip" in resp.headers["content-type"]

    def test_zip_contains_correct_files(self, client, db, tmp_path, monkeypatch):
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)

        creator = make_creator(db)
        model = make_model(db, creator)

        filenames = ["Head_01.stl", "RightArm_02.stl", "Base_32mm.stl"]
        file_ids = []
        for name in filenames:
            p = tmp_path / name
            p.write_bytes(b"solid\nendsolid\n")
            row = make_stl_file(db, model, filename=name, path=str(p))
            file_ids.append(row.id)
        db.commit()

        resp = client.post(
            "/files/download-zip",
            json={"file_ids": file_ids, "zip_name": "Build"},
        )
        assert resp.status_code == 200

        z = zipfile.ZipFile(io.BytesIO(resp.content))
        assert set(z.namelist()) == set(filenames)

    def test_zip_filename_header(self, client, db, tmp_path, monkeypatch):
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)

        stl = tmp_path / "test.stl"
        stl.write_bytes(b"solid\nendsolid\n")

        creator = make_creator(db)
        model = make_model(db, creator)
        row = make_stl_file(db, model, filename="test.stl", path=str(stl))
        db.commit()

        resp = client.post(
            "/files/download-zip",
            json={"file_ids": [row.id], "zip_name": "Chaos Warriors 2026-05-30"},
        )
        assert resp.status_code == 200
        disposition = resp.headers.get("content-disposition", "")
        assert "Chaos Warriors 2026-05-30.zip" in disposition

    def test_missing_files_skipped_gracefully(self, client, db, monkeypatch):
        """Files whose paths don't exist on disk are silently skipped."""
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)

        creator = make_creator(db)
        model = make_model(db, creator)
        row = make_stl_file(db, model, filename="ghost.stl", path="/nonexistent/ghost.stl")
        db.commit()

        resp = client.post(
            "/files/download-zip",
            json={"file_ids": [row.id], "zip_name": "Empty Build"},
        )
        # Should still return 200 with an empty (but valid) zip
        assert resp.status_code == 200
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        assert z.namelist() == []

    def test_zip_name_sanitized(self, client, db, tmp_path, monkeypatch):
        """Special characters in zip_name are sanitized in the filename header."""
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)

        stl = tmp_path / "test.stl"
        stl.write_bytes(b"solid\nendsolid\n")

        creator = make_creator(db)
        model = make_model(db, creator)
        row = make_stl_file(db, model, filename="test.stl", path=str(stl))
        db.commit()

        resp = client.post(
            "/files/download-zip",
            json={"file_ids": [row.id], "zip_name": 'Bad/Name:With<>Chars'},
        )
        assert resp.status_code == 200
        disposition = resp.headers.get("content-disposition", "")
        # Should not contain raw special chars
        assert "/" not in disposition.split("filename=")[-1]
        assert ":" not in disposition.split("filename=")[-1]

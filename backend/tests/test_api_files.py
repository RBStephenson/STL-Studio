"""
Tests for the /files endpoints: image serving, STL serving, zip download.
"""
import io
import zipfile
from pathlib import Path
import pytest
from tests.conftest import make_creator, make_model, make_stl_file


# ---------------------------------------------------------------------------
# Path-safety allowlist
# ---------------------------------------------------------------------------

class TestAllowedRoots:
    @pytest.fixture(autouse=True)
    def _isolate_env_roots(self, monkeypatch):
        """The conftest sets STL_ROOTS=/tmp, and pytest's tmp_path lives under
        /tmp — which would mask the scan_roots logic under test. Clear the
        env-based roots so only the DB scan_roots decide the allowlist."""
        import app.routers.files as files_module
        monkeypatch.setattr(files_module.settings, "stl_roots", "")
        files_module._roots_cache = None
        yield
        files_module._roots_cache = None

    def test_scan_roots_from_db_are_allowed(self, db, tmp_path):
        """Roots added via the Settings UI (scan_roots table) must be served,
        even when the STL_ROOTS env var doesn't include them (standalone mode)."""
        import app.routers.files as files_module
        from app.models import ScanRoot

        db.add(ScanRoot(path=str(tmp_path), enabled=True))
        db.commit()

        f = tmp_path / "sub" / "model.stl"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"solid\nendsolid\n")

        files_module._roots_cache = None
        assert files_module._is_safe_path(f) is True

    def test_disabled_scan_roots_are_not_allowed(self, db, tmp_path):
        import app.routers.files as files_module
        from app.models import ScanRoot

        db.add(ScanRoot(path=str(tmp_path), enabled=False))
        db.commit()

        f = tmp_path / "model.stl"
        f.write_bytes(b"solid\nendsolid\n")

        files_module._roots_cache = None
        assert files_module._is_safe_path(f) is False

    def test_no_roots_denies_everything(self, db, tmp_path):
        import app.routers.files as files_module

        f = tmp_path / "model.stl"
        f.write_bytes(b"solid\nendsolid\n")

        files_module._roots_cache = None
        assert files_module._is_safe_path(f) is False


# ---------------------------------------------------------------------------
# /files/stl
# ---------------------------------------------------------------------------

class TestServeStl:
    def test_rejects_non_stl_extension(self, client):
        resp = client.get("/files/stl", params={"path": "/tmp/notes.txt"})
        assert resp.status_code == 400

    def test_rejects_path_outside_allowed_roots(self, client, monkeypatch):
        """An STL outside the allowlist must be refused, not served."""
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: False)

        resp = client.get("/files/stl", params={"path": "/etc/secret.stl"})
        assert resp.status_code == 403

    def test_serves_allowed_stl(self, client, tmp_path, monkeypatch):
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)

        stl = tmp_path / "model.stl"
        stl.write_bytes(b"solid\nendsolid\n")

        resp = client.get("/files/stl", params={"path": str(stl)})
        assert resp.status_code == 200
        assert resp.content == b"solid\nendsolid\n"


# ---------------------------------------------------------------------------
# /files/image — cache headers (#185)
# ---------------------------------------------------------------------------

class TestServeImageCaching:
    def _write_png(self, tmp_path):
        img = tmp_path / "thumb.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        return img

    def test_unversioned_request_is_no_cache(self, client, tmp_path, monkeypatch):
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)
        img = self._write_png(tmp_path)

        resp = client.get("/files/image", params={"path": str(img)})
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache"

    def test_versioned_request_is_immutable(self, client, tmp_path, monkeypatch):
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)
        img = self._write_png(tmp_path)

        resp = client.get("/files/image", params={"path": str(img), "v": "2026-06-15T00:00:00"})
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


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

    def test_duplicate_filenames_are_deduplicated(self, client, db, tmp_path, monkeypatch):
        """Two files sharing a basename in different folders must both survive in
        the archive — the second is suffixed, not silently overwritten (#219)."""
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)

        creator = make_creator(db)
        model = make_model(db, creator)

        file_ids = []
        for sub in ("Body", "Base"):
            p = tmp_path / sub / "base.stl"
            p.parent.mkdir(parents=True)
            p.write_bytes(b"solid\nendsolid\n")
            row = make_stl_file(db, model, filename="base.stl", path=str(p))
            file_ids.append(row.id)
        db.commit()

        resp = client.post(
            "/files/download-zip",
            json={"file_ids": file_ids, "zip_name": "Dupes"},
        )
        assert resp.status_code == 200
        names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
        assert len(names) == 2
        assert "base.stl" in names
        assert "base (2).stl" in names

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


# ---------------------------------------------------------------------------
# /files/browse-images
# ---------------------------------------------------------------------------

class TestBrowseImages:
    @pytest.fixture(autouse=True)
    def _allow_tmp(self, monkeypatch):
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: True)

    def test_lists_subdirs_and_images(self, client, tmp_path):
        (tmp_path / "subfolder").mkdir()
        (tmp_path / "cover.png").write_bytes(b"PNG")
        (tmp_path / "render.jpg").write_bytes(b"JPEG")
        (tmp_path / "readme.txt").write_bytes(b"text")  # must be excluded

        resp = client.get("/files/browse-images", params={"path": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()
        names = [e["name"] for e in data["entries"]]
        assert "subfolder" in names
        assert "cover.png" in names
        assert "render.jpg" in names
        assert "readme.txt" not in names

    def test_dirs_sorted_before_files(self, client, tmp_path):
        (tmp_path / "zzz_folder").mkdir()
        (tmp_path / "aaa_image.png").write_bytes(b"PNG")

        resp = client.get("/files/browse-images", params={"path": str(tmp_path)})
        entries = resp.json()["entries"]
        dir_indices = [i for i, e in enumerate(entries) if e["is_dir"]]
        file_indices = [i for i, e in enumerate(entries) if not e["is_dir"]]
        assert max(dir_indices) < min(file_indices)

    def test_image_entries_include_url(self, client, tmp_path):
        (tmp_path / "thumb.png").write_bytes(b"PNG")

        resp = client.get("/files/browse-images", params={"path": str(tmp_path)})
        entries = resp.json()["entries"]
        img = next(e for e in entries if e["name"] == "thumb.png")
        assert img["is_dir"] is False
        assert img["url"] is not None
        assert "thumb.png" in img["url"]

    def test_hidden_entries_excluded(self, client, tmp_path):
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden_img.png").write_bytes(b"PNG")
        (tmp_path / "visible.png").write_bytes(b"PNG")

        resp = client.get("/files/browse-images", params={"path": str(tmp_path)})
        names = [e["name"] for e in resp.json()["entries"]]
        assert ".hidden" not in names
        assert ".hidden_img.png" not in names
        assert "visible.png" in names

    def test_missing_path_returns_404(self, client, tmp_path):
        resp = client.get("/files/browse-images", params={"path": str(tmp_path / "nope")})
        assert resp.status_code == 404

    def test_path_outside_allowed_roots_returns_403(self, client, monkeypatch):
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_is_safe_path", lambda p: False)

        resp = client.get("/files/browse-images", params={"path": "/etc"})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /files/model-images (caching)
# ---------------------------------------------------------------------------

class TestModelImagesCache:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        import app.routers.files as files_module
        files_module._clear_model_images_cache()
        files_module._roots_cache = None
        yield
        files_module._clear_model_images_cache()
        files_module._roots_cache = None

    def _setup_model(self, db, tmp_path):
        """A scan root → creator → character folder holding the model."""
        from app.models import ScanRoot
        db.add(ScanRoot(path=str(tmp_path), enabled=True))
        char_dir = tmp_path / "Creator" / "Hero"
        char_dir.mkdir(parents=True)
        creator = make_creator(db)
        model = make_model(db, creator)
        model.folder_path = str(char_dir)
        db.commit()
        return model, char_dir

    def test_returns_images_in_boundary(self, client, db, tmp_path):
        model, char_dir = self._setup_model(db, tmp_path)
        (char_dir / "render.png").write_bytes(b"PNG")

        resp = client.get(f"/files/model-images/{model.id}")
        assert resp.status_code == 200
        assert [i["filename"] for i in resp.json()] == ["render.png"]

    def test_second_open_is_served_from_cache(self, client, db, tmp_path):
        """A file added after the first call isn't re-walked until the TTL lapses."""
        model, char_dir = self._setup_model(db, tmp_path)
        (char_dir / "first.png").write_bytes(b"PNG")

        first = client.get(f"/files/model-images/{model.id}").json()
        assert [i["filename"] for i in first] == ["first.png"]

        # Add a new image — the cached result should still be returned.
        (char_dir / "second.png").write_bytes(b"PNG")
        cached = client.get(f"/files/model-images/{model.id}").json()
        assert [i["filename"] for i in cached] == ["first.png"]

    def test_cache_clear_forces_rewalk(self, client, db, tmp_path):
        import app.routers.files as files_module
        model, char_dir = self._setup_model(db, tmp_path)
        (char_dir / "first.png").write_bytes(b"PNG")

        client.get(f"/files/model-images/{model.id}")
        (char_dir / "second.png").write_bytes(b"PNG")
        files_module._clear_model_images_cache()

        fresh = client.get(f"/files/model-images/{model.id}").json()
        assert {i["filename"] for i in fresh} == {"first.png", "second.png"}

    def test_unknown_model_returns_404(self, client, db):
        resp = client.get("/files/model-images/99999")
        assert resp.status_code == 404

    def test_manifest_persists_and_skips_rewalk(self, client, db, tmp_path):
        """After the in-memory cache is gone, an unchanged folder is served from
        the persisted DB manifest without re-walking the disk (#304)."""
        import app.routers.files as files_module
        from app.models import Model as ModelDB

        model, char_dir = self._setup_model(db, tmp_path)
        (char_dir / "render.png").write_bytes(b"PNG")

        first = client.get(f"/files/model-images/{model.id}").json()
        assert [i["filename"] for i in first] == ["render.png"]

        # The walk persisted a manifest + signature to the DB.
        db.expire_all()
        stored = db.query(ModelDB).filter(ModelDB.id == model.id).first()
        assert [i["filename"] for i in stored.image_manifest] == ["render.png"]
        assert stored.image_manifest_sig

        # Drop the in-memory layer; the persisted manifest must answer without a
        # full walk (patch _collect to fail if it runs).
        files_module._clear_model_images_cache()
        orig_iterdir = Path.iterdir

        def _boom(self):
            raise AssertionError("boundary was re-walked despite unchanged signature")

        Path.iterdir = _boom
        try:
            served = client.get(f"/files/model-images/{model.id}").json()
        finally:
            Path.iterdir = orig_iterdir
        assert [i["filename"] for i in served] == ["render.png"]

    def test_refresh_param_bypasses_caches(self, client, db, tmp_path):
        """?refresh=true forces a re-walk even when both the in-memory cache and
        the persisted manifest signature are still valid (#304 escape hatch)."""
        model, char_dir = self._setup_model(db, tmp_path)
        (char_dir / "first.png").write_bytes(b"PNG")
        # A deep subtree that already exists at first walk, so adding a file
        # inside it later won't bump the boundary or its immediate children's
        # mtimes — the shallow signature stays stale.
        nested = char_dir / "Supported" / "Extra"
        nested.mkdir(parents=True)
        client.get(f"/files/model-images/{model.id}")  # warms both caches

        (nested / "deep.png").write_bytes(b"PNG")

        forced = client.get(f"/files/model-images/{model.id}?refresh=true").json()
        assert {i["filename"] for i in forced} == {"first.png", "deep.png"}

    def test_signature_change_forces_rewalk_and_repersist(self, client, db, tmp_path):
        """Adding an image bumps the boundary signature, so the persisted manifest
        is rebuilt on the next open even after a restart (no in-memory cache)."""
        import app.routers.files as files_module
        from app.models import Model as ModelDB

        model, char_dir = self._setup_model(db, tmp_path)
        (char_dir / "first.png").write_bytes(b"PNG")
        client.get(f"/files/model-images/{model.id}")

        # Simulate a restart: only the persisted manifest survives.
        files_module._clear_model_images_cache()
        (char_dir / "second.png").write_bytes(b"PNG")

        served = client.get(f"/files/model-images/{model.id}").json()
        assert {i["filename"] for i in served} == {"first.png", "second.png"}

        db.expire_all()
        stored = db.query(ModelDB).filter(ModelDB.id == model.id).first()
        assert {i["filename"] for i in stored.image_manifest} == {"first.png", "second.png"}


# ---------------------------------------------------------------------------
# /files/drive-status
# ---------------------------------------------------------------------------

class TestDriveStatus:
    def test_reports_available_root(self, client, db, tmp_path):
        from app.models import ScanRoot
        db.add(ScanRoot(path=str(tmp_path), enabled=True))
        db.commit()

        data = client.get("/files/drive-status").json()
        assert data["all_available"] is True
        entry = next(r for r in data["roots"] if r["path"] == str(tmp_path))
        assert entry == {"path": str(tmp_path), "enabled": True, "available": True}

    def test_reports_unavailable_root(self, client, db, tmp_path):
        from app.models import ScanRoot
        missing = tmp_path / "unmounted_drive"
        db.add(ScanRoot(path=str(missing), enabled=True))
        db.commit()

        data = client.get("/files/drive-status").json()
        assert data["all_available"] is False
        entry = next(r for r in data["roots"] if r["path"] == str(missing))
        assert entry["available"] is False

    def test_disabled_unavailable_root_does_not_fail_all(self, client, db, tmp_path):
        from app.models import ScanRoot
        db.add(ScanRoot(path=str(tmp_path / "gone"), enabled=False))
        db.commit()

        data = client.get("/files/drive-status").json()
        assert data["all_available"] is True

"""Tests for POST /scan/inbox and the is_inbox model flag (#428)."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.conftest import make_creator, make_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stl_tree(base: Path, structure: dict):
    """Recursively create files/directories from a dict.
    str values are file content; dict values are subdirectories."""
    for name, content in structure.items():
        if isinstance(content, dict):
            child = base / name
            child.mkdir(parents=True, exist_ok=True)
            _make_stl_tree(child, content)
        else:
            (base / name).write_text(content)


# ---------------------------------------------------------------------------
# POST /scan/inbox — validation
# ---------------------------------------------------------------------------

class TestInboxScanValidation:
    def test_missing_path_returns_400(self, client, db):
        r = client.post("/scan/inbox", json={"path": ""})
        assert r.status_code == 400
        assert "required" in r.json()["detail"].lower()

    def test_nonexistent_path_returns_400(self, client, db):
        r = client.post("/scan/inbox", json={"path": "/nonexistent/path/xyz"})
        assert r.status_code == 400
        assert "not exist" in r.json()["detail"].lower()

    def test_file_path_returns_400(self, client, db):
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            f.write(b"solid test\nendsolid")
            fpath = f.name
        try:
            r = client.post("/scan/inbox", json={"path": fpath})
            assert r.status_code == 400
            assert "not a directory" in r.json()["detail"].lower()
        finally:
            os.unlink(fpath)

    def test_configured_scan_root_returns_400(self, client, db):
        with tempfile.TemporaryDirectory() as tmpdir:
            client.post("/scan/roots", json={"path": tmpdir, "layout": "{creator}"})
            r = client.post("/scan/inbox", json={"path": tmpdir})
            assert r.status_code == 400
            assert "scan root" in r.json()["detail"].lower()

    def test_child_of_scan_root_returns_400(self, client, db):
        """Inbox path is a subdirectory of a scan root — overlap rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            child = os.path.join(tmpdir, "sub")
            os.makedirs(child)
            client.post("/scan/roots", json={"path": tmpdir, "layout": "{creator}"})
            r = client.post("/scan/inbox", json={"path": child})
            assert r.status_code == 400

    def test_parent_of_scan_root_returns_400(self, client, db):
        """Inbox path is an ancestor of a scan root — overlap rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            child = os.path.join(tmpdir, "lib")
            os.makedirs(child)
            client.post("/scan/roots", json={"path": child, "layout": "{creator}"})
            r = client.post("/scan/inbox", json={"path": tmpdir})
            assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /scan/inbox — scan already running
# ---------------------------------------------------------------------------

class TestInboxScanConflict:
    def test_409_when_scan_running(self, client, db):
        with patch("app.services.scanner.get_status", return_value={"running": True}):
            with tempfile.TemporaryDirectory() as tmpdir:
                r = client.post("/scan/inbox", json={"path": tmpdir})
        assert r.status_code == 409

    def test_409_when_write_lock_held(self, client, db):
        """Lock acquired synchronously in endpoint — 409 before thread starts."""
        from unittest.mock import MagicMock
        mock_settings = MagicMock()
        with patch("app.services.scanner.prepare_inbox_scan", return_value=False), \
             patch("app.routers.scan._configured_roots", return_value=[]), \
             patch("app.routers.scan.settings", mock_settings):
            with tempfile.TemporaryDirectory() as tmpdir:
                r = client.post("/scan/inbox", json={"path": tmpdir})
        assert r.status_code == 409
        assert "busy" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /models?is_inbox filter
# ---------------------------------------------------------------------------

class TestIsInboxFilter:
    def test_filter_returns_only_inbox_models(self, client, db):
        creator = make_creator(db)
        inbox_m = make_model(db, creator, name="Inbox Model")
        inbox_m.is_inbox = True
        normal_m = make_model(db, creator, name="Normal Model")
        db.commit()

        r = client.get("/models?is_inbox=true")
        assert r.status_code == 200
        names = {m["name"] for m in r.json()["items"]}
        assert "Inbox Model" in names
        assert "Normal Model" not in names

    def test_filter_false_excludes_inbox(self, client, db):
        creator = make_creator(db)
        inbox_m = make_model(db, creator, name="Inbox Model")
        inbox_m.is_inbox = True
        normal_m = make_model(db, creator, name="Normal Model")
        db.commit()

        r = client.get("/models?is_inbox=false")
        assert r.status_code == 200
        names = {m["name"] for m in r.json()["items"]}
        assert "Normal Model" in names
        assert "Inbox Model" not in names

    def test_no_filter_returns_all(self, client, db):
        creator = make_creator(db)
        inbox_m = make_model(db, creator, name="Inbox Model")
        inbox_m.is_inbox = True
        make_model(db, creator, name="Normal Model")
        db.commit()

        r = client.get("/models")
        assert r.status_code == 200
        names = {m["name"] for m in r.json()["items"]}
        assert "Inbox Model" in names
        assert "Normal Model" in names

    def test_is_inbox_field_in_model_response(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="Test")
        m.is_inbox = True
        db.commit()

        r = client.get("/models")
        assert r.status_code == 200
        item = next(i for i in r.json()["items"] if i["name"] == "Test")
        assert item["is_inbox"] is True


# ---------------------------------------------------------------------------
# scan_inbox_folder — unit tests (synchronous, no thread)
# ---------------------------------------------------------------------------

class TestScanInboxFolder:
    def test_creator_structure_indexes_subdirs_as_creators(self, client, db):
        """Approach B: each immediate subdir becomes a creator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            _make_stl_tree(inbox, {
                "Artist One": {
                    "Dragon Pack": {"dragon.stl": "solid d\nendsolid"},
                },
                "Artist Two": {
                    "Knight": {"knight.stl": "solid k\nendsolid"},
                },
                "EmptyFolder": {},
            })

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db)

        r = client.get("/models?is_inbox=true")
        assert r.json()["total"] >= 1

    def test_flat_structure_uses_inbox_creator(self, client, db):
        """Flat: STLs directly in inbox root → _Inbox creator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            (inbox / "thing.stl").write_text("solid t\nendsolid")

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db)

        r = client.get("/models?is_inbox=true")
        assert r.json()["total"] >= 1

    def test_inbox_flag_not_cleared_by_index_model(self, client, db):
        """_index_model called without is_inbox=True must not clear an existing True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            (inbox / "thing.stl").write_text("solid t\nendsolid")

            from app.services.scanner import scan_inbox_folder, _index_model, _has_stls
            from app.models import Creator as CreatorModel
            scan_inbox_folder(tmpdir, db=db)

        r = client.get("/models?is_inbox=true")
        assert r.json()["total"] >= 1
        item = r.json()["items"][0]
        assert item["is_inbox"] is True

        # Call _index_model again on the same folder WITHOUT is_inbox=True.
        # is_inbox should remain True — the function only ever sets it, never clears.
        with tempfile.TemporaryDirectory() as tmpdir2:
            inbox2 = Path(tmpdir2)
            (inbox2 / "other.stl").write_text("solid o\nendsolid")
            creator = db.query(CreatorModel).first()
            _index_model(
                folder=inbox2,
                creator=creator,
                db=db,
                creator_boundary=inbox2,
                character=None,
                stl_cache={},
                is_inbox=False,
            )
            db.commit()

        # Pre-existing inbox model unchanged
        r2 = client.get(f"/models/{item['id']}")
        assert r2.json()["is_inbox"] is True

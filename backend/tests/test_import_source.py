"""Tests for browse-first import endpoints (Child C, #452):
GET /import/source-contents and POST /import/scan-folder."""
import os
from unittest.mock import patch

from app.models import Model, ScanRoot
from app.utils import utcnow


def _stl(dirpath, name="part.stl"):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, name), "w") as f:
        f.write("solid\nendsolid\n")


def _inbox_model(db, folder_path):
    m = Model(name="m", folder_path=os.path.normpath(folder_path), tags=[], auto_tags=[],
              is_inbox=True, created_at=utcnow(), updated_at=utcnow())
    db.add(m)
    db.commit()
    return m


class TestSourceContents:
    def test_lists_immediate_subfolders(self, client, db, tmp_path):
        _stl(str(tmp_path / "PackA"))
        _stl(str(tmp_path / "PackB"))
        (tmp_path / ".hidden").mkdir()
        r = client.get("/import/source-contents", params={"source": str(tmp_path)})
        assert r.status_code == 200
        body = r.json()
        assert body["is_flat"] is False
        names = [e["name"] for e in body["entries"]]
        assert names == ["PackA", "PackB"]  # sorted, hidden excluded

    def test_flat_source_has_no_entries(self, client, db, tmp_path):
        _stl(str(tmp_path))  # STL directly in the source root
        r = client.get("/import/source-contents", params={"source": str(tmp_path)})
        body = r.json()
        assert body["is_flat"] is True
        assert body["entries"] == []

    def test_already_imported_flag(self, client, db, tmp_path):
        _stl(str(tmp_path / "PackA"))
        _stl(str(tmp_path / "PackB"))
        _inbox_model(db, str(tmp_path / "PackA" / "sub"))
        r = client.get("/import/source-contents", params={"source": str(tmp_path)})
        by_name = {e["name"]: e["already_imported"] for e in r.json()["entries"]}
        assert by_name == {"PackA": True, "PackB": False}

    def test_missing_source_400(self, client, db):
        assert client.get("/import/source-contents", params={"source": ""}).status_code == 400

    def test_nonexistent_source_404(self, client, db):
        r = client.get("/import/source-contents", params={"source": "/no/such/dir/xyz"})
        assert r.status_code == 404


class TestScanFolder:
    def test_missing_path_400(self, client, db):
        assert client.post("/import/scan-folder", json={"path": ""}).status_code == 400

    def test_nonexistent_path_400(self, client, db):
        r = client.post("/import/scan-folder", json={"path": "/no/such/dir/xyz"})
        assert r.status_code == 400

    def test_file_path_400(self, client, db, tmp_path):
        f = tmp_path / "x.stl"
        f.write_text("solid")
        r = client.post("/import/scan-folder", json={"path": str(f)})
        assert r.status_code == 400

    def test_409_when_scan_running(self, client, db, tmp_path):
        with patch("app.routers.imports.scanner.get_status", return_value={"running": True}):
            r = client.post("/import/scan-folder", json={"path": str(tmp_path)})
        assert r.status_code == 409

    def test_allows_path_under_scan_root(self, client, db, tmp_path):
        """Key difference from /scan/inbox: importing a folder inside a configured
        scan root is allowed (explicit per-folder import)."""
        db.add(ScanRoot(path=str(tmp_path), enabled=True, layout="{creator}"))
        db.commit()
        pack = tmp_path / "PackA"
        pack.mkdir()
        with patch("app.routers.imports.scanner.get_status", return_value={"running": False}), \
             patch("app.routers.imports.scanner.prepare_inbox_scan", return_value=True), \
             patch("app.routers.imports.threading.Thread") as thread:
            r = client.post("/import/scan-folder", json={"path": str(pack)})
        assert r.status_code == 200
        assert r.json()["running"] is True
        thread.assert_called_once()

    def test_busy_returns_409(self, client, db, tmp_path):
        with patch("app.routers.imports.scanner.get_status", return_value={"running": False}), \
             patch("app.routers.imports.scanner.prepare_inbox_scan", return_value=False):
            r = client.post("/import/scan-folder", json={"path": str(tmp_path)})
        assert r.status_code == 409

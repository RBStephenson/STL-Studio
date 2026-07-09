"""
Tests for the v0.17.0 endpoints added in PR #584:
  - GET    /files/document        (serve non-STL/non-image pack files)
  - DELETE /models/bulk           (bulk delete, optional file removal)
  - POST   /import/download-images (CDN image fetch into pack folder)

These three endpoints shipped without coverage; the absence let two NameError
bugs through. The first test in each class exercises the happy path that would
have caught them.
"""
import pytest

from tests.conftest import make_creator, make_model, make_stl_file


def _register_root(db, path) -> None:
    from app.models import ScanRoot
    db.add(ScanRoot(path=str(path), enabled=True))
    db.commit()
    import app.routers.files as files_module
    files_module._roots_cache = None


# ---------------------------------------------------------------------------
# GET /files/document
# ---------------------------------------------------------------------------

class TestServeDocument:
    def test_serves_pdf_inside_root(self, client, db, tmp_path):
        """An absolute path to a non-STL file under a scan root downloads as an
        attachment. Regression: the endpoint referenced an undefined `rel_path`
        and 500'd on every call (PR #584)."""
        _register_root(db, tmp_path)
        doc = tmp_path / "instructions.pdf"
        doc.write_bytes(b"%PDF-1.4 fake")

        resp = client.get("/files/document", params={"path": str(doc)})
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"]
        assert "instructions.pdf" in resp.headers["content-disposition"]
        assert resp.content == b"%PDF-1.4 fake"

    def test_rejects_image_extension(self, client):
        resp = client.get("/files/document", params={"path": "/x/cover.png"})
        assert resp.status_code == 400

    def test_rejects_stl_extension(self, client):
        resp = client.get("/files/document", params={"path": "/x/body.stl"})
        assert resp.status_code == 400

    def test_rejects_path_outside_roots(self, client, monkeypatch):
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_allowed_roots", lambda: [])
        resp = client.get("/files/document", params={"path": "/etc/passwd.txt"})
        assert resp.status_code == 403

    def test_missing_file_404(self, client, db, tmp_path):
        _register_root(db, tmp_path)
        resp = client.get("/files/document", params={"path": str(tmp_path / "gone.pdf")})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /models/bulk
# ---------------------------------------------------------------------------

class TestBulkDelete:
    def _delete(self, client, ids, delete_files=False):
        return client.request(
            "DELETE", "/models/bulk", json={"ids": ids, "delete_files": delete_files}
        )

    def test_records_only_keeps_files(self, client, db, tmp_path):
        """delete_files=False removes DB rows but leaves the folder on disk."""
        creator = make_creator(db)
        model = make_model(db, creator)
        model.folder_path = str(tmp_path / "pack")
        (tmp_path / "pack").mkdir()
        make_stl_file(db, model)
        db.commit()
        mid = model.id  # capture before the row is deleted out from under the ORM

        resp = self._delete(client, [mid], delete_files=False)
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] == 1
        assert body["folders_removed"] == 0
        assert (tmp_path / "pack").exists()

        from app.models import Model
        assert db.query(Model).filter(Model.id == mid).first() is None

    def test_delete_files_removes_folder_inside_root(self, client, db, tmp_path):
        creator = make_creator(db)
        model = make_model(db, creator)
        model.folder_path = str(tmp_path / "pack")
        (tmp_path / "pack").mkdir()
        (tmp_path / "pack" / "body.stl").write_bytes(b"solid\nendsolid\n")
        db.commit()
        _register_root(db, tmp_path)

        resp = self._delete(client, [model.id], delete_files=True)
        assert resp.status_code == 200
        assert resp.json()["folders_removed"] == 1
        assert not (tmp_path / "pack").exists()

    def test_delete_files_rejects_folder_outside_roots(self, client, db, tmp_path):
        """A folder_path outside every scan root must be refused before any
        rmtree — the path-injection guard."""
        creator = make_creator(db)
        model = make_model(db, creator)
        model.folder_path = str(tmp_path / "pack")
        (tmp_path / "pack").mkdir()
        db.commit()
        # No scan root registered → guard rejects.

        resp = self._delete(client, [model.id], delete_files=True)
        assert resp.status_code == 400
        assert (tmp_path / "pack").exists()

    def test_empty_ids_400(self, client):
        resp = self._delete(client, [])
        assert resp.status_code == 400

    def test_unknown_ids_404(self, client):
        resp = self._delete(client, [999999])
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /import/download-images
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, content=b"\x89PNG fake", content_type="image/png"):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        pass


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient — download-images now fetches
    concurrently on a background job thread (STUDIO-XX), so the mock must be
    an async context manager with an async .get()."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        return _FakeResponse()


def _download_and_wait(client, pack_path, image_urls, expected_status=200):
    """POST /import/download-images and, if a background job started, block
    until it finishes — mirrors _apply_and_wait in test_import_apply.py."""
    from app.routers.imports import _DOWNLOAD_IMAGES_KEY
    from app.services.job_runner import runner

    r = client.post(
        "/import/download-images",
        json={"pack_path": pack_path, "image_urls": image_urls},
    )
    if r.status_code != expected_status:
        return r.status_code, r.json()
    body = r.json()
    if not body["started"]:
        return r.status_code, body["result"]
    assert runner.wait(_DOWNLOAD_IMAGES_KEY, timeout=10), "download-images job did not finish"
    status = client.get("/import/download-images/status").json()
    assert not status["running"]
    return r.status_code, status["result"]


class TestDownloadImages:
    @pytest.fixture(autouse=True)
    def _no_bootstrap_roots(self, monkeypatch):
        """The allow-set is configured roots + bootstrap roots. On Windows the
        bootstrap set is the drive roots (C:\\…), which would contain tmp_path and
        mask the guard. Stub it to [] so only the registered scan root decides."""
        import app.routers.imports as imports_module
        monkeypatch.setattr(imports_module, "_bootstrap_roots", lambda: [])

    def test_downloads_into_pack_folder(self, client, db, tmp_path, monkeypatch):
        """Images fetched from CDN URLs land in the pack folder. Mocks httpx so
        no network is touched."""
        import app.routers.imports as imports_module
        monkeypatch.setattr(imports_module.httpx, "AsyncClient", _FakeAsyncClient)
        _register_root(db, tmp_path)
        pack = tmp_path / "pack"
        pack.mkdir()

        status, result = _download_and_wait(
            client, str(pack), ["http://cdn/a.png", "http://cdn/b.png"],
        )
        assert status == 200, result
        assert result["downloaded"] == 2
        assert len(list(pack.glob("gallery_*.png"))) == 2

    def test_rejects_path_outside_roots(self, client, db, tmp_path):
        resp = client.post(
            "/import/download-images",
            json={"pack_path": str(tmp_path / "pack"), "image_urls": []},
        )
        # tmp_path is not a configured root → 403 before any fetch.
        assert resp.status_code == 403

    def test_missing_pack_folder_404(self, client, db, tmp_path):
        _register_root(db, tmp_path)
        resp = client.post(
            "/import/download-images",
            json={"pack_path": str(tmp_path / "nope"), "image_urls": []},
        )
        assert resp.status_code == 404

    def test_empty_pack_path_400(self, client):
        resp = client.post(
            "/import/download-images", json={"pack_path": "  ", "image_urls": []}
        )
        assert resp.status_code == 400

    def test_no_image_urls_returns_immediately_without_starting_a_job(self, client, db, tmp_path):
        """No URLs to fetch — respond synchronously instead of starting a job
        the poller would just see finish instantly."""
        _register_root(db, tmp_path)
        pack = tmp_path / "pack"
        pack.mkdir()

        resp = client.post(
            "/import/download-images", json={"pack_path": str(pack), "image_urls": []},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["started"] is False
        assert body["result"]["downloaded"] == 0

    def test_concurrent_downloads_still_produce_correct_progress_and_count(
        self, client, db, tmp_path, monkeypatch,
    ):
        """Regression guard for the move from a sequential loop to
        asyncio.gather-based concurrency: every image is still accounted for
        exactly once, with no double-count or lost update under concurrency."""
        import app.routers.imports as imports_module
        monkeypatch.setattr(imports_module.httpx, "AsyncClient", _FakeAsyncClient)
        _register_root(db, tmp_path)
        pack = tmp_path / "pack"
        pack.mkdir()

        urls = [f"http://cdn/{n}.png" for n in range(10)]
        status, result = _download_and_wait(client, str(pack), urls)
        assert status == 200, result
        assert result["downloaded"] == 10
        assert len(list(pack.glob("gallery_*.png"))) == 10

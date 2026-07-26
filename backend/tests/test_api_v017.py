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

    def test_bulk_delete_removes_model_tag_rows(self, client, db, tmp_path):
        """STUDIO-324: PRAGMA foreign_keys is off, so the DDL CASCADE on
        model_tags never fires — the manual cascade must delete them, or
        ghost tags accumulate in tag lists/counts after every bulk delete."""
        from app.models import ModelTag
        creator = make_creator(db)
        model = make_model(db, creator)
        db.add(ModelTag(model_id=model.id, tag="dragon", is_auto=False))
        db.commit()
        mid = model.id

        resp = self._delete(client, [mid], delete_files=False)
        assert resp.status_code == 200
        assert db.query(ModelTag).filter(ModelTag.model_id == mid).count() == 0

    def test_bulk_delete_nulls_stale_variant_group_rep(self, client, db, tmp_path):
        """STUDIO-324: deleting a group's designated rep must null
        variant_groups.rep_model_id (DDL SET NULL is unenforced) so the rep
        heuristic takes over instead of a dangling pointer persisting."""
        from app.models import VariantGroup
        creator = make_creator(db)
        rep = make_model(db, creator, name="Rep")
        sibling = make_model(db, creator, name="Sibling")
        group = VariantGroup(creator_id=creator.id, label="G", rep_model_id=rep.id)
        db.add(group)
        db.flush()
        rep.variant_group_id = group.id
        sibling.variant_group_id = group.id
        db.commit()
        gid, rid = group.id, rep.id

        resp = self._delete(client, [rid], delete_files=False)
        assert resp.status_code == 200
        db.expire_all()
        assert db.get(VariantGroup, gid).rep_model_id is None

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

PNG_BYTES = bytes.fromhex("89504e470d0a1a0a") + b"fakepngdata"


def _stub_fetch(monkeypatch, handler):
    """Replace the shared hardened fetch used by download-images.

    Since STUDIO-320 this path delegates to thumbnails.fetch_image_bytes, which
    owns the SSRF guard, the redirect cap, the size cap, and magic-byte
    validation — so the seam to stub is that function, not an httpx client.
    """
    import app.routers.imports as imports_module

    async def fake(url, *, _follow_html=True):
        return handler(url)

    monkeypatch.setattr(imports_module, "fetch_image_bytes", fake)


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
        """Images fetched from CDN URLs land in the pack folder. Stubs the
        shared fetch so no network is touched."""
        _stub_fetch(monkeypatch, lambda url: (".png", PNG_BYTES))
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
        _stub_fetch(monkeypatch, lambda url: (".png", PNG_BYTES))
        _register_root(db, tmp_path)
        pack = tmp_path / "pack"
        pack.mkdir()

        urls = [f"http://cdn/{n}.png" for n in range(10)]
        status, result = _download_and_wait(client, str(pack), urls)
        assert status == 200, result
        assert result["downloaded"] == 10
        assert len(list(pack.glob("gallery_*.png"))) == 10


class TestDownloadImagesHardening:
    """STUDIO-320: this path used a bare httpx client with a content-type
    blocklist. It now delegates to the shared hardened fetch, so the guarantees
    are inherited rather than reimplemented — these tests pin the delegation
    and the behaviour the job layer still owns."""

    @pytest.fixture(autouse=True)
    def _no_bootstrap_roots(self, monkeypatch):
        import app.routers.imports as imports_module
        monkeypatch.setattr(imports_module, "_bootstrap_roots", lambda: [])

    def test_uses_the_ssrf_guarded_fetch_rather_than_a_bare_client(
        self, client, db, tmp_path, monkeypatch,
    ):
        """The guard lives in fetch_image_bytes; if this path ever stops calling
        it, the SSRF and size protections silently disappear."""
        import app.routers.imports as imports_module
        assert not hasattr(imports_module, "httpx"), (
            "imports.py should no longer construct its own HTTP client"
        )

        seen = []

        def handler(url):
            seen.append(url)
            return (".png", PNG_BYTES)

        _stub_fetch(monkeypatch, handler)
        _register_root(db, tmp_path)
        pack = tmp_path / "pack"
        pack.mkdir()

        _download_and_wait(client, str(pack), ["https://cdn/a.png"])
        assert seen == ["https://cdn/a.png"]

    def test_a_rejected_image_is_skipped_without_failing_the_job(
        self, client, db, tmp_path, monkeypatch,
    ):
        """A blocked URL or a non-image body must degrade to a missing gallery
        image, not a failed import."""
        from app.services.thumbnails import ThumbnailDownloadError

        def handler(url):
            if "bad" in url:
                raise ThumbnailDownloadError("That URL isn't allowed.")
            return (".png", PNG_BYTES)

        _stub_fetch(monkeypatch, handler)
        _register_root(db, tmp_path)
        pack = tmp_path / "pack"
        pack.mkdir()

        status, result = _download_and_wait(
            client, str(pack), ["https://cdn/bad.png", "https://cdn/good.png"],
        )
        assert status == 200, result
        assert result["downloaded"] == 1
        assert len(list(pack.glob("gallery_*"))) == 1

    def test_extension_follows_the_sniffed_type_not_the_url(
        self, client, db, tmp_path, monkeypatch,
    ):
        """The URL says .webp; the fetch reports PNG from the bytes. The stored
        file is named for the bytes."""
        _stub_fetch(monkeypatch, lambda url: (".png", PNG_BYTES))
        _register_root(db, tmp_path)
        pack = tmp_path / "pack"
        pack.mkdir()

        _download_and_wait(client, str(pack), ["https://cdn/render.webp"])
        assert [p.suffix for p in pack.glob("gallery_*")] == [".png"]

    def test_an_unexpected_extension_is_not_written(
        self, client, db, tmp_path, monkeypatch,
    ):
        """Defence in depth: even if the fetch returned something outside
        IMAGE_EXTS, it must not reach the pack folder."""
        _stub_fetch(monkeypatch, lambda url: (".exe", b"MZ\x90\x00"))
        _register_root(db, tmp_path)
        pack = tmp_path / "pack"
        pack.mkdir()

        status, result = _download_and_wait(client, str(pack), ["https://cdn/x"])
        assert status == 200, result
        assert result["downloaded"] == 0
        assert list(pack.iterdir()) == []

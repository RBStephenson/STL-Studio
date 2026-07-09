"""Tests for on-demand model gallery sync: refresh-from-disk and image upload
(the model detail page's "Refresh" / "Upload Images" actions)."""
from app.models import Model, ScanRoot
from app.services.scanner import refresh_model_gallery
from tests.conftest import make_creator, make_model


def _root(db, tmp_path):
    db.add(ScanRoot(path=str(tmp_path), enabled=True))
    db.commit()


def _model_with_folder(db, tmp_path, name="Bust") -> tuple[Model, "object"]:
    creator = make_creator(db, name="Abe3D")
    folder = tmp_path / "Abe3D" / name
    folder.mkdir(parents=True)
    m = make_model(db, creator, name=name)
    m.folder_path = str(folder)
    db.commit()
    return m, folder


class TestRefreshModelGallery:
    def test_picks_up_manually_added_images(self, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        (folder / "gallery_00.jpg").write_bytes(b"fake-jpg")
        (folder / "gallery_01.jpg").write_bytes(b"fake-jpg")

        refresh_model_gallery(db, m)
        db.commit()

        assert len(m.image_paths) == 2
        assert any(p.endswith("gallery_00.jpg") for p in m.image_paths)
        assert any(p.endswith("gallery_01.jpg") for p in m.image_paths)

    def test_ignores_hidden_directories(self, db, tmp_path):
        """Other tools stash their own resized derivative caches in hidden
        dot-directories alongside real content — none of that should ever
        surface as a gallery image (#888-follow-up)."""
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        (folder / "real_photo.jpg").write_bytes(b"fake-jpg")
        hidden = folder / ".othertool" / "derivatives" / "real_photo.jpg"
        hidden.mkdir(parents=True)
        (hidden / "carousel.jpg").write_bytes(b"fake-jpg")
        (hidden / "preview.jpg").write_bytes(b"fake-jpg")

        refresh_model_gallery(db, m)
        db.commit()

        assert len(m.image_paths) == 1
        assert m.image_paths[0].endswith("real_photo.jpg")
        assert not any(".othertool" in p for p in m.image_paths)

    def test_drops_stale_entries_for_deleted_files(self, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        stale = folder / "old.jpg"
        stale.write_bytes(b"fake-jpg")
        m.image_paths = [str(stale)]
        db.commit()
        stale.unlink()

        refresh_model_gallery(db, m)
        db.commit()

        assert m.image_paths == []

    def test_clears_stale_primary_image_path(self, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        stale = folder / "old.jpg"
        stale.write_bytes(b"fake-jpg")
        m.image_paths = [str(stale)]
        m.primary_image_path = str(stale)
        db.commit()
        stale.unlink()

        refresh_model_gallery(db, m)
        db.commit()

        assert m.primary_image_path is None

    def test_sets_thumbnail_when_unset(self, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        (folder / "a.jpg").write_bytes(b"fake-jpg")

        refresh_model_gallery(db, m)
        db.commit()

        assert m.thumbnail_path is not None

    def test_respects_removed_image_paths(self, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        removed = folder / "user_removed.jpg"
        removed.write_bytes(b"fake-jpg")
        m.removed_image_paths = [str(removed)]
        db.commit()

        refresh_model_gallery(db, m)
        db.commit()

        assert m.image_paths == []

    def test_missing_folder_is_a_noop(self, db, tmp_path):
        creator = make_creator(db, name="Ghost")
        m = make_model(db, creator, name="Missing")
        m.folder_path = str(tmp_path / "does-not-exist")
        db.commit()

        refresh_model_gallery(db, m)  # must not raise
        db.commit()

        assert m.image_paths == []


class TestRefreshGalleryEndpoint:
    def test_refresh_endpoint_syncs_images(self, client, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        (folder / "new.jpg").write_bytes(b"fake-jpg")

        resp = client.post(f"/models/{m.id}/images/refresh")
        assert resp.status_code == 200
        body = resp.json()
        assert any(p.endswith("new.jpg") for p in body["image_paths"])

    def test_refresh_unknown_model_returns_404(self, client, db):
        resp = client.post("/models/99999/images/refresh")
        assert resp.status_code == 404


class TestUploadGalleryImages:
    def test_upload_writes_file_and_syncs_gallery(self, client, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        # A file already sitting in the folder outside the app should also
        # show up once upload triggers the refresh.
        (folder / "gallery_00.jpg").write_bytes(b"fake-jpg")

        resp = client.post(
            f"/models/{m.id}/images/upload",
            files=[("files", ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png"))],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert (folder / "photo.png").exists()
        assert any(p.endswith("photo.png") for p in body["image_paths"])
        assert any(p.endswith("gallery_00.jpg") for p in body["image_paths"])

    def test_upload_dedupes_filename_collision(self, client, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        (folder / "photo.png").write_bytes(b"existing")

        resp = client.post(
            f"/models/{m.id}/images/upload",
            files=[("files", ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png"))],
        )
        assert resp.status_code == 200
        assert (folder / "photo.png").read_bytes() == b"existing"
        assert (folder / "photo_1.png").exists()

    def test_upload_rejects_non_image(self, client, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)

        resp = client.post(
            f"/models/{m.id}/images/upload",
            files=[("files", ("bad.txt", b"not an image", "text/plain"))],
        )
        assert resp.status_code == 400
        assert not any(folder.iterdir())

    def test_upload_rejects_oversized_file(self, client, db, tmp_path):
        _root(db, tmp_path)
        m, folder = _model_with_folder(db, tmp_path)
        oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (15 * 1024 * 1024 + 1)

        resp = client.post(
            f"/models/{m.id}/images/upload",
            files=[("files", ("big.png", oversized, "image/png"))],
        )
        assert resp.status_code == 413

    def test_upload_missing_folder_returns_409(self, client, db, tmp_path):
        creator = make_creator(db, name="Ghost2")
        m = make_model(db, creator, name="Missing2")
        m.folder_path = str(tmp_path / "does-not-exist")
        db.commit()

        resp = client.post(
            f"/models/{m.id}/images/upload",
            files=[("files", ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png"))],
        )
        assert resp.status_code == 409

    def test_upload_unknown_model_returns_404(self, client, db):
        resp = client.post(
            "/models/99999/images/upload",
            files=[("files", ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png"))],
        )
        assert resp.status_code == 404

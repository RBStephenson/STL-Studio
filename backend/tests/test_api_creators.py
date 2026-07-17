"""Tests for manually adding a creator and the model-detail "unorganized"
indicator (reorganize destination vs. current folder_path)."""
import os
from pathlib import Path

from app.models import AppSetting, Creator, Model, ScanRoot
from tests.conftest import make_creator, make_model, make_stl_file


def _root(db, tmp_path):
    db.add(ScanRoot(path=str(tmp_path), enabled=True))
    db.commit()


class TestCreateCreator:
    def test_creates_creator_and_directory(self, client, db, tmp_path):
        _root(db, tmp_path)

        resp = client.post("/models/creators", json={"name": "Abe 3D"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Abe 3D"
        assert body["model_count"] == 0

        creator = db.query(Creator).filter_by(name="Abe 3D").first()
        assert creator is not None
        # Directory naming is lowercase/hyphenated by default (reorganize_slugify).
        assert (tmp_path / "abe-3d").is_dir()

    def test_directory_keeps_original_casing_when_slugify_disabled(self, client, db, tmp_path):
        _root(db, tmp_path)
        db.add(AppSetting(key="reorganize_slugify", value=False))
        db.commit()

        resp = client.post("/models/creators", json={"name": "Abe 3D"})
        assert resp.status_code == 201
        assert (tmp_path / "Abe 3D").is_dir()
        assert not (tmp_path / "abe-3d").exists()

    def test_duplicate_name_is_rejected_case_insensitively(self, client, db, tmp_path):
        _root(db, tmp_path)
        make_creator(db, name="Abe3D")
        db.commit()

        resp = client.post("/models/creators", json={"name": "abe3d"})
        assert resp.status_code == 409

    def test_blank_name_is_rejected(self, client, db):
        resp = client.post("/models/creators", json={"name": "   "})
        assert resp.status_code == 400

    def test_no_scan_root_still_creates_creator(self, client, db):
        """Directory creation is best-effort — no root to anchor to is not an error."""
        resp = client.post("/models/creators", json={"name": "Solo"})
        assert resp.status_code == 201
        assert db.query(Creator).filter_by(name="Solo").first() is not None


def _model_with_real_file(db, tmp_path, creator, character="Joker", title="Bust", filename="head.stl"):
    """Create a model backed by a real folder/file on disk (unlike
    tests.conftest.make_model's fake /tmp/models/... path) — the delete-
    creator move needs os.path.isdir/shutil.move to see something real."""
    folder = tmp_path / creator.name / character / title
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / filename
    f.write_bytes(b"solid\nendsolid\n")
    m = make_model(db, creator, name=title, character=character)
    m.folder_path = str(folder)
    m.title = title
    db.commit()
    make_stl_file(db, m, filename=filename, path=str(f))
    db.commit()
    return m


class TestDeleteCreator:
    def test_deletes_a_creator_with_no_models(self, client, db):
        creator = make_creator(db, name="Solo")
        db.commit()

        resp = client.delete(f"/models/creators/{creator.id}")
        assert resp.status_code == 204
        assert db.query(Creator).filter_by(id=creator.id).first() is None

    def test_model_folder_moved_into_inbox_and_creator_dir_removed(self, client, db, tmp_path):
        """The whole point of #1097-follow-up: deleting a creator physically
        relocates its models' folders into the "_Inbox" creator's directory
        (not just a DB flag flip), and the now-empty old creator directory
        disappears along with the row."""
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3D")
        m = _model_with_real_file(db, tmp_path, creator)
        old_folder = m.folder_path
        stl_path = m.stl_files[0].path
        model_id = m.id

        resp = client.delete(f"/models/creators/{creator.id}")
        assert resp.status_code == 204
        assert db.query(Creator).filter_by(id=creator.id).first() is None

        db.expire_all()
        moved = db.get(Model, model_id)
        assert moved.creator_id is not None  # now owned by "_Inbox"
        inbox_creator = db.get(Creator, moved.creator_id)
        assert inbox_creator.name == "_Inbox"
        assert moved.is_inbox is True
        assert moved.character == "Joker"  # untouched otherwise

        # Physically moved — old path gone, new path exists with the file.
        assert not os.path.exists(old_folder)
        assert os.path.isdir(moved.folder_path)
        assert os.path.basename(moved.folder_path) == "Bust"
        assert (Path(moved.folder_path) / "head.stl").exists()

        # STLFile.path rewritten onto the new location; the old stl path is gone.
        assert not os.path.exists(stl_path)
        db.refresh(moved.stl_files[0])
        assert moved.stl_files[0].path == str(Path(moved.folder_path) / "head.stl")

        # The old creator's now-empty directory tree is gone too.
        assert not (tmp_path / "Abe3D").exists()

    def test_gallery_and_other_file_paths_rewritten_onto_the_new_location(self, client, db, tmp_path):
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3D")
        m = _model_with_real_file(db, tmp_path, creator)
        folder = Path(m.folder_path)
        img = folder / "cover.jpg"
        img.write_bytes(b"\xff\xd8\xff")
        doc = folder / "notes.txt"
        doc.write_text("hi")
        m.thumbnail_path = str(img)
        m.image_paths = [str(img)]
        m.primary_image_path = str(img)
        m.other_files = [str(doc)]
        db.commit()

        resp = client.delete(f"/models/creators/{creator.id}")
        assert resp.status_code == 204

        db.expire_all()
        moved = db.get(Model, m.id)
        new_folder = Path(moved.folder_path)
        assert moved.thumbnail_path == str(new_folder / "cover.jpg")
        assert moved.primary_image_path == str(new_folder / "cover.jpg")
        assert moved.image_paths == [str(new_folder / "cover.jpg")]
        assert moved.other_files == [str(new_folder / "notes.txt")]
        assert (new_folder / "cover.jpg").exists()
        assert (new_folder / "notes.txt").exists()

    def test_name_collision_in_inbox_gets_suffixed(self, client, db, tmp_path):
        """Two different creators each with a model folder named "Bust" —
        both must land in the inbox without one clobbering the other."""
        _root(db, tmp_path)
        c1 = make_creator(db, name="Abe3D")
        c2 = make_creator(db, name="Zeroc")
        m1 = _model_with_real_file(db, tmp_path, c1, title="Bust")
        m2 = _model_with_real_file(db, tmp_path, c2, title="Bust")

        assert client.delete(f"/models/creators/{c1.id}").status_code == 204
        assert client.delete(f"/models/creators/{c2.id}").status_code == 204

        db.expire_all()
        f1 = db.get(Model, m1.id).folder_path
        f2 = db.get(Model, m2.id).folder_path
        assert f1 != f2
        assert os.path.isdir(f1)
        assert os.path.isdir(f2)

    def test_excluded_model_also_moved(self, client, db, tmp_path):
        """Same treatment regardless of the excluded/hidden flag — this
        checks the raw FK relationship, not just what the library grid shows,
        so nothing is left silently pointing at a deleted creator."""
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3D")
        m = _model_with_real_file(db, tmp_path, creator)
        m.excluded = True
        db.commit()
        model_id = m.id

        resp = client.delete(f"/models/creators/{creator.id}")
        assert resp.status_code == 204

        db.expire_all()
        moved = db.get(Model, model_id)
        assert moved.is_inbox is True
        assert os.path.isdir(moved.folder_path)

    def test_multiple_models_all_moved_and_creator_dir_pruned(self, client, db, tmp_path):
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3D")
        m1 = _model_with_real_file(db, tmp_path, creator, character="Joker", title="Bust")
        m2 = _model_with_real_file(db, tmp_path, creator, character="Riddler", title="Statue")
        ids = [m1.id, m2.id]

        resp = client.delete(f"/models/creators/{creator.id}")
        assert resp.status_code == 204

        db.expire_all()
        for mid in ids:
            m = db.get(Model, mid)
            assert m.is_inbox is True
            assert os.path.isdir(m.folder_path)
        assert not (tmp_path / "Abe3D").exists()

    def test_missing_folder_on_disk_still_moves_to_inbox_in_db(self, client, db, tmp_path):
        """A model whose folder is already gone from disk (moved/deleted
        outside the app) can't be physically relocated — it still gets
        cleared to the inbox in the DB rather than being left dangling."""
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3D")
        m = make_model(db, creator, name="Bust", character="Joker")
        m.folder_path = str(tmp_path / "Abe3D" / "Joker" / "Bust")  # never created
        db.commit()
        model_id = m.id

        resp = client.delete(f"/models/creators/{creator.id}")
        assert resp.status_code == 204

        db.expire_all()
        moved = db.get(Model, model_id)
        assert moved.is_inbox is True
        inbox_creator = db.get(Creator, moved.creator_id)
        assert inbox_creator.name == "_Inbox"

    def test_no_scan_root_is_rejected_and_nothing_changes(self, client, db, tmp_path):
        """No scan root configured means no safe place to anchor the inbox
        folder — the whole delete is rejected rather than guessing."""
        creator = make_creator(db, name="Abe3D")
        m = _model_with_real_file(db, tmp_path, creator)

        resp = client.delete(f"/models/creators/{creator.id}")
        assert resp.status_code == 409

        db.expire_all()
        assert db.query(Creator).filter_by(id=creator.id).first() is not None
        untouched = db.get(Model, m.id)
        assert untouched.creator_id == creator.id
        assert untouched.is_inbox is False
        assert os.path.isdir(untouched.folder_path)

    def test_cannot_delete_the_inbox_sentinel_creator(self, client, db):
        creator = make_creator(db, name="_Inbox")
        db.commit()

        resp = client.delete(f"/models/creators/{creator.id}")
        assert resp.status_code == 400
        assert db.query(Creator).filter_by(id=creator.id).first() is not None

    def test_unknown_creator_is_404(self, client, db):
        resp = client.delete("/models/creators/999999")
        assert resp.status_code == 404


class TestUnorganizedIndicator:
    def test_model_in_place_is_not_flagged(self, client, db, tmp_path):
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3D")
        folder = tmp_path / "abe3d" / "joker" / "bust"
        folder.mkdir(parents=True)
        f = folder / "head.stl"
        f.write_bytes(b"solid\nendsolid\n")
        m = make_model(db, creator, name="Bust", character="Joker")
        m.folder_path = str(folder)
        m.title = "Bust"
        db.commit()
        make_stl_file(db, m, filename="head.stl", path=str(f))
        db.commit()

        resp = client.get(f"/models/{m.id}")
        assert resp.status_code == 200
        assert resp.json()["unorganized"] is False

    def test_model_out_of_place_is_flagged(self, client, db, tmp_path):
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3D")
        folder = tmp_path / "Misc" / "Bust"
        folder.mkdir(parents=True)
        f = folder / "head.stl"
        f.write_bytes(b"solid\nendsolid\n")
        m = make_model(db, creator, name="Bust", character="Joker")
        m.folder_path = str(folder)
        m.title = "Bust"
        db.commit()
        make_stl_file(db, m, filename="head.stl", path=str(f))
        db.commit()

        resp = client.get(f"/models/{m.id}")
        assert resp.status_code == 200
        assert resp.json()["unorganized"] is True

    def test_invalid_stored_template_does_not_500(self, client, db, tmp_path):
        from app.models import AppSetting

        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3D")
        m = make_model(db, creator, name="Bust", character="Joker")
        db.commit()
        db.add(AppSetting(key="reorganize_template", value="{bogus}"))
        db.commit()

        resp = client.get(f"/models/{m.id}")
        assert resp.status_code == 200
        assert resp.json()["unorganized"] is False

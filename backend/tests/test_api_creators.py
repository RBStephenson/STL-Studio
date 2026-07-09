"""Tests for manually adding a creator and the model-detail "unorganized"
indicator (reorganize destination vs. current folder_path)."""
from app.models import AppSetting, Creator, ScanRoot
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

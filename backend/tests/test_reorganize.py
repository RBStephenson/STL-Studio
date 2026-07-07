"""
Tests for the library reorganize Phase 1 preview (#323).

Exercises the full path: router → core builder → schema → manifest persistence.
Focuses on the "dangerous population" the issue calls out — pack-split / shared
folders, collisions, sentinels, scan-root escape, override capture — not just
the happy path. No test moves any files.
"""
from app.models import Creator, PackOverride, ReorganizeManifest, ScanRoot
from tests.conftest import make_creator, make_model, make_stl_file


def _root(db, tmp_path):
    db.add(ScanRoot(path=str(tmp_path), enabled=True))
    db.commit()


def _get_creator(db, name):
    """Get-or-create — Creator.name is unique, so multi-model tests must reuse."""
    existing = db.query(Creator).filter_by(name=name).first()
    return existing or make_creator(db, name=name)


def _model_with_file(db, tmp_path, creator_name="Abe3D", character="Joker",
                     title="Bust", filename="head.stl", subdir=""):
    """Create creator/character/title model with one real file on disk."""
    folder = tmp_path / creator_name / (character or "loose") / title / subdir
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / filename
    f.write_bytes(b"solid\nendsolid\n")
    creator = _get_creator(db, creator_name)
    m = make_model(db, creator, name=title, character=character)
    m.folder_path = str(folder)
    m.title = title
    db.commit()
    make_stl_file(db, m, filename=filename, path=str(f))
    db.commit()
    return m


class TestPreviewHappyPath:
    def test_returns_manifest_id_and_persists(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path)

        resp = client.get("/reorganize/preview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["manifest_id"]
        # The manifest was persisted as an artifact.
        row = db.query(ReorganizeManifest).filter_by(id=data["manifest_id"]).first()
        assert row is not None
        assert row.template == "{creator}/{character}/{title}"

    def test_file_move_carries_real_fingerprint(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path)

        entry = client.get("/reorganize/preview").json()["entries"][0]
        f = entry["files"][0]
        assert f["fingerprint_method"] == "stat"
        assert f["size_bytes"] == len(b"solid\nendsolid\n")
        assert f["mtime_ns"] > 0
        assert f["content_hash"] is None

    def test_proposed_dir_under_scan_root(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, creator_name="Abe3D", character="Joker", title="Bust")

        entry = client.get("/reorganize/preview").json()["entries"][0]
        # Destination segments render lowercase/hyphenated by default (#reorganize).
        assert entry["proposed_dir"].endswith("abe3d/joker/bust")
        assert entry["eligible"] is True
        assert entry["escapes_scan_root"] is False


class TestSentinels:
    def test_missing_character_is_unclassifiable_and_ineligible(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, character=None)

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert "character" in entry["missing_fields"]
        assert entry["unclassifiable"] is True
        assert entry["eligible"] is False
        assert "unknown-character" in entry["proposed_dir"]


class TestCollisions:
    def test_duplicate_destination_flagged_as_merge(self, client, db, tmp_path):
        _root(db, tmp_path)
        # One creator, two models with identical character/title but distinct
        # source folders → both resolve to the same destination dir.
        _model_with_file(db, tmp_path, title="Bust", filename="a.stl", subdir="v1")
        _model_with_file(db, tmp_path, title="Bust", filename="b.stl", subdir="v2")

        entries = client.get("/reorganize/preview").json()["entries"]
        assert all(e["collision"] for e in entries)
        assert all(e["kind"] == "merge" for e in entries)
        assert all(e["eligible"] is False for e in entries)
        assert all(e["collision_kind"] == "legitimate_duplicate" for e in entries)


class TestScanRootEscape:
    def test_model_outside_all_roots_escapes(self, client, db, tmp_path):
        # Root is a sibling dir; the model lives outside it.
        root_dir = tmp_path / "library"
        root_dir.mkdir()
        db.add(ScanRoot(path=str(root_dir), enabled=True))
        db.commit()
        outside = tmp_path / "elsewhere" / "Abe3D" / "Joker" / "Bust"
        outside.mkdir(parents=True)
        f = outside / "head.stl"
        f.write_bytes(b"x")
        creator = make_creator(db, name="Abe3D")
        m = make_model(db, creator, name="Bust", character="Joker")
        m.folder_path = str(outside)
        m.title = "Bust"
        db.commit()
        make_stl_file(db, m, filename="head.stl", path=str(f))
        db.commit()

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert entry["escapes_scan_root"] is True
        assert entry["eligible"] is False


class TestOverrideCapture:
    def test_pack_override_paths_captured(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path)
        db.add(PackOverride(path=m.folder_path))
        db.commit()

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert m.folder_path.replace("\\", "/") in entry["pack_override_paths"]


class TestSpansMultipleDirs:
    def test_model_with_files_in_two_dirs_flagged(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path, filename="a.stl")
        # Add a second file in a different directory.
        other = tmp_path / "Abe3D" / "Joker" / "Bust" / "sub"
        other.mkdir(parents=True)
        f2 = other / "b.stl"
        f2.write_bytes(b"x")
        make_stl_file(db, m, filename="b.stl", path=str(f2))
        db.commit()

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert entry["spans_multiple_dirs"] is True
        assert entry["eligible"] is False


class TestMissingFile:
    def test_absent_source_file_flagged_and_ineligible(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, filename="head.stl")
        # Delete the file on disk after indexing — simulates a source that has
        # gone missing by preview time.
        (tmp_path / "Abe3D" / "Joker" / "Bust" / "head.stl").unlink()

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert entry["files"][0]["missing_file"] is True
        # Zeroed sentinel, not a real fingerprint.
        assert entry["files"][0]["size_bytes"] == 0
        assert entry["files"][0]["mtime_ns"] == 0
        assert entry["missing_files_on_disk"] is True
        assert entry["eligible"] is False


class TestTemplateValidation:
    def test_malformed_template_returns_400(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path)
        resp = client.get("/reorganize/preview", params={"template": "{creator}/{scale}"})
        assert resp.status_code == 400

    def test_custom_template_applied(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, creator_name="Abe3D", title="Bust")
        entry = client.get(
            "/reorganize/preview", params={"template": "{creator}/{title}"}
        ).json()["entries"][0]
        assert entry["proposed_dir"].endswith("abe3d/bust")


class TestResolution:
    def test_override_resolves_unclassifiable(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path, character=None)
        base = client.get("/reorganize/preview").json()["entries"][0]
        assert base["eligible"] is False and "character" in base["missing_fields"]

        resp = client.post("/reorganize/preview", json={
            "overrides": {str(m.id): {"character": "Harley"}},
        })
        assert resp.status_code == 200
        entry = resp.json()["entries"][0]
        assert entry["eligible"] is True
        assert "character" not in entry["missing_fields"]
        assert entry["proposed_dir"].endswith("harley/bust")

    def test_suffix_breaks_a_collision(self, client, db, tmp_path):
        _root(db, tmp_path)
        m1 = _model_with_file(db, tmp_path, title="Bust", filename="a.stl", subdir="v1")
        m2 = _model_with_file(db, tmp_path, title="Bust", filename="b.stl", subdir="v2")
        assert all(e["collision"] for e in client.get("/reorganize/preview").json()["entries"])

        data = client.post("/reorganize/preview", json={
            "overrides": {str(m2.id): {"suffix": "v2"}},
        }).json()
        by_id = {e["model_id"]: e for e in data["entries"]}
        assert by_id[m1.id]["collision"] is False
        assert by_id[m2.id]["collision"] is False
        assert by_id[m2.id]["proposed_dir"].endswith("bust-v2")

    def test_post_preview_persists_new_manifest(self, client, db, tmp_path):
        from app.models import ReorganizeManifest
        _root(db, tmp_path)
        _model_with_file(db, tmp_path)
        mid = client.post("/reorganize/preview", json={}).json()["manifest_id"]
        assert db.query(ReorganizeManifest).filter_by(id=mid).first() is not None


class TestStats:
    def test_stats_summary_counts(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, title="Bust", filename="a.stl")
        _model_with_file(db, tmp_path, character=None, title="Lost", filename="b.stl")

        data = client.get("/reorganize/preview").json()
        stats = data["stats"]
        assert stats["total"] == 2
        assert stats["unclassifiable"] == 1
        assert stats["blocked"] >= 1

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
                     title="Bust", filename="head.stl", subdir="", auto_tags=None):
    """Create creator/character/title model with one real file on disk."""
    folder = tmp_path / creator_name / (character or "loose") / title / subdir
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / filename
    f.write_bytes(b"solid\nendsolid\n")
    creator = _get_creator(db, creator_name)
    m = make_model(db, creator, name=title, character=character)
    m.folder_path = str(folder)
    m.title = title
    m.auto_tags = auto_tags or []
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


class TestSlugifyFilenames:
    """reorganize_slugify_filenames (#946) is off by default and independent
    of reorganize_slugify (directory segments only) — it renders each STL's
    own filename lowercase/hyphenated too."""

    def test_filename_unchanged_by_default(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, filename="Cold Giant last time hollowed.stl")

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert entry["files"][0]["proposed_path"].endswith(
            "/Cold Giant last time hollowed.stl"
        )

    def test_filename_slugified_when_setting_on(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, filename="Cold Giant last time hollowed.stl")
        client.patch("/settings", json={"reorganize_slugify_filenames": True})

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert entry["files"][0]["proposed_path"].endswith(
            "/cold-giant-last-time-hollowed.stl"
        )

    def test_already_in_place_directory_reclassified_as_rename_when_filename_needs_slugging(
        self, client, db, tmp_path,
    ):
        """A model whose directory is already correctly placed must not be
        reported as "in_place" (nothing to do) when its filename still needs
        slugging — the Reorganize page excludes "in_place" entries from
        selection entirely, so this would otherwise never get applied."""
        _root(db, tmp_path)
        # Already-lowercase directory placement — reorganize_slugify defaults
        # to on, so this is exactly what preview would propose, making the
        # directory itself "in_place" before slugify_filenames enters into it.
        _model_with_file(
            db, tmp_path, creator_name="abe3d", character="joker", title="bust",
            filename="Cold Giant.stl",
        )
        client.patch("/settings", json={"reorganize_slugify_filenames": True})

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert entry["kind"] == "rename"
        assert entry["files"][0]["proposed_path"].endswith("/cold-giant.stl")


class TestHiddenDirImagesExcluded:
    def test_image_inside_hidden_directory_never_becomes_a_move_entry(self, client, db, tmp_path):
        """A stale image_paths reference into a hidden directory (e.g. a
        .manyfold derivative-thumbnail cache another tool left behind, from
        before the scanner started skipping them) must never be treated as
        a real gallery image to carry through a move — that would relocate
        the junk into the organized library instead of letting it fall away
        (#903-follow-up)."""
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path)
        folder = tmp_path / "Abe3D" / "Joker" / "Bust"
        hidden = folder / ".manyfold" / "derivatives"
        hidden.mkdir(parents=True)
        stale = hidden / "carousel.jpg"
        stale.write_bytes(b"\x89PNG\r\n\x1a\n")
        # A real, legitimate gallery image too, to prove it's still included.
        real = folder / "cover.jpg"
        real.write_bytes(b"\x89PNG\r\n\x1a\n")
        m.image_paths = [str(stale), str(real)]
        db.commit()

        entry = client.get("/reorganize/preview").json()["entries"][0]
        image_sources = [f["current_path"] for f in entry["files"] if f["kind"] == "image"]

        assert not any(".manyfold" in p for p in image_sources)
        assert any(p.endswith("cover.jpg") for p in image_sources)


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


class TestLockedFlag:
    def test_locked_model_is_ineligible_with_locked_flag(self, client, db, tmp_path):
        """A locked model is blocked from Reorganize entirely
        (#978) — same as a collision or unclassifiable row, but reported via
        its own `locked` flag rather than overloading an existing one."""
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path)
        m.locked = True
        db.commit()

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert entry["locked"] is True
        assert entry["eligible"] is False

    def test_unlocked_model_is_unaffected(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path)

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert entry["locked"] is False


class TestTemplateValidation:
    def test_unknown_template_field_returns_400(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path)
        resp = client.get("/reorganize/preview", params={"template": "{creator}/{franchise}"})
        assert resp.status_code == 400

    def test_custom_template_applied(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, creator_name="Abe3D", title="Bust")
        entry = client.get(
            "/reorganize/preview", params={"template": "{creator}/{title}"}
        ).json()["entries"][0]
        assert entry["proposed_dir"].endswith("abe3d/bust")

    def test_scale_template_uses_detected_auto_tag(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, title="Bust", auto_tags=["1:6", "statue"])

        entry = client.get(
            "/reorganize/preview", params={"template": "{creator}/{scale}/{title}"}
        ).json()["entries"][0]

        assert entry["proposed_dir"].endswith("abe3d/1-6/bust")
        assert entry["eligible"] is True
        assert "scale" not in entry["missing_fields"]

    def test_missing_scale_only_blocks_when_template_uses_scale(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, title="Bust")

        default_entry = client.get("/reorganize/preview").json()["entries"][0]
        assert "scale" not in default_entry["missing_fields"]
        assert default_entry["eligible"] is True

        scale_entry = client.get(
            "/reorganize/preview", params={"template": "{creator}/{scale}/{title}"}
        ).json()["entries"][0]
        assert "scale" in scale_entry["missing_fields"]
        assert scale_entry["unclassifiable"] is True
        assert scale_entry["eligible"] is False
        assert "unknown-scale" in scale_entry["proposed_dir"]


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

    def test_override_resolves_missing_scale(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path)

        resp = client.post("/reorganize/preview", json={
            "template": "{creator}/{scale}/{title}",
            "overrides": {str(m.id): {"scale": "75mm"}},
        })

        assert resp.status_code == 200
        entry = resp.json()["entries"][0]
        assert entry["eligible"] is True
        assert "scale" not in entry["missing_fields"]
        assert entry["proposed_dir"].endswith("abe3d/75mm/bust")

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

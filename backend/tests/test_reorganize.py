"""
Tests for the library reorganize Phase 1 preview (#323).

Exercises the full path: router → core builder → schema → manifest persistence.
Focuses on the "dangerous population" the issue calls out — pack-split / shared
folders, collisions, sentinels, scan-root escape, override capture — not just
the happy path. No test moves any files.
"""
from pathlib import Path

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
        model = _model_with_file(db, tmp_path, creator_name="Abe3D", character="Joker", title="Bust")

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert entry["creator_id"] == model.creator_id
        assert entry["creator_name"] == "Abe3D"
        # Destination segments render lowercase/hyphenated by default (#reorganize).
        assert entry["proposed_dir"].endswith("abe3d/joker/bust")
        assert entry["eligible"] is True
        assert entry["escapes_scan_root"] is False


class TestPackageMode:
    def test_groups_nested_models_and_preserves_relative_tree(self, client, db, tmp_path):
        _root(db, tmp_path)
        creator = _get_creator(db, "Abe3d")
        package = tmp_path / "Abe3d" / "2B" / "1_4 2B YoRHa - Abe3D"
        alternate = package / "Alternate"
        alternate.mkdir(parents=True)
        standard_file = package / "Base.stl"
        alternate_file = alternate / "Head.stl"
        companion = package / "README.txt"
        shared_render = package.parent / "Renders" / "preview.jpg"
        shared_render.parent.mkdir()
        standard_file.write_bytes(b"standard")
        alternate_file.write_bytes(b"alternate")
        companion.write_text("assembly notes", encoding="utf-8")
        shared_render.write_bytes(b"jpg")

        standard = make_model(db, creator, name="2B", character="2B")
        standard.folder_path = str(package)
        standard.thumbnail_path = str(shared_render)
        alternate_model = make_model(db, creator, name="Alternative", character="2B")
        alternate_model.folder_path = str(alternate)
        db.commit()
        make_stl_file(db, standard, filename="Base.stl", path=str(standard_file))
        make_stl_file(db, alternate_model, filename="Head.stl", path=str(alternate_file))
        db.commit()
        client.patch("/settings", json={"reorganize_package_mode_enabled": True})

        data = client.get("/reorganize/preview", params={"template": "{creator}/{character}"}).json()

        assert len(data["entries"]) == 1
        entry = data["entries"][0]
        assert entry["package_mode"] is True
        assert entry["eligible"] is True
        assert entry["model_ids"] == [standard.id, alternate_model.id]
        assert entry["source_path"].replace("\\", "/").endswith("Abe3d/2B/1_4 2B YoRHa - Abe3D")
        assert entry["proposed_dir"].replace("\\", "/").endswith(
            "abe3d/2b/1_4 2B YoRHa - Abe3D"
        )
        moves = {Path(f["current_path"]).name: f for f in entry["files"]}
        assert moves["Head.stl"]["proposed_path"].replace("\\", "/").endswith(
            "1_4 2B YoRHa - Abe3D/Alternate/Head.stl"
        )
        assert moves["README.txt"]["kind"] == "companion"
        assert "preview.jpg" not in moves
        assert [Path(f["current_path"]).name for f in entry["shared_files"]] == ["preview.jpg"]
        assert entry["character_package_ids"] == [entry["model_id"]]

    def test_blocks_when_character_folder_cannot_be_found(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, character="Joker", title="Bust")
        model = db.query(Creator).filter_by(name="Abe3D").one().models[0]
        model.character = "Different Character"
        db.commit()
        client.patch("/settings", json={"reorganize_package_mode_enabled": True})

        entry = client.get("/reorganize/preview").json()["entries"][0]

        assert entry["ambiguous_package"] is True
        assert entry["eligible"] is False


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
        assert all(e["collision_kind"] == "same_destination" for e in entries)
        assert {e["suggested_suffix"] for e in entries} == {"v1", "v2"}

    def test_generic_source_folders_do_not_produce_suffix_suggestions(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, title="Bust", filename="a.stl", subdir="files")
        _model_with_file(db, tmp_path, title="Bust", filename="b.stl", subdir="stl")

        entries = client.get("/reorganize/preview").json()["entries"]

        assert all(e["collision_kind"] == "same_destination" for e in entries)
        assert all(e["suggested_suffix"] is None for e in entries)

    def test_support_status_folders_suggest_but_do_not_auto_resolve_on_reorganize_page(
        self, client, db, tmp_path,
    ):
        """The Reorganize page (no inbox_source) keeps its existing
        suggest-not-auto-apply behavior even now that support-status names are
        a recognized suggestion source (#1087) — only import-apply auto-folds
        the suggestion into the entry."""
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, title="Bust", filename="a.stl", subdir="Bust (supported)")
        _model_with_file(db, tmp_path, title="Bust", filename="b.stl", subdir="Bust (unsupported)")

        entries = client.get("/reorganize/preview").json()["entries"]

        assert all(e["collision"] for e in entries)
        assert all(e["eligible"] is False for e in entries)
        assert {e["suggested_suffix"] for e in entries} == {"supported", "unsupported"}


class TestSiblingFilenameCollision:
    """Two distinct source filenames can collapse to the identical
    destination name — most commonly slugify_filenames stripping enough
    that e.g. "arm_2_R_sup.stl" and "arm_2_R__sup.stl" both slug to
    "arm-2-r-sup.stl". Left unchecked, apply either silently overwrites one
    file with the other or hard-fails mid-batch (#1087 — cost a real
    build-kit pack a file with no way to recover it)."""

    def test_slug_collision_within_one_model_gets_disambiguated(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path, filename="arm_2_R_sup.stl")
        f2 = Path(m.folder_path) / "arm_2_R__sup.stl"
        f2.write_bytes(b"solid\nendsolid\n")
        make_stl_file(db, m, filename="arm_2_R__sup.stl", path=str(f2))
        client.patch("/settings", json={"reorganize_slugify_filenames": True})

        entry = client.get("/reorganize/preview").json()["entries"][0]
        proposed = sorted(f["proposed_path"].rsplit("/", 1)[-1] for f in entry["files"])
        assert proposed == ["arm-2-r-sup-2.stl", "arm-2-r-sup.stl"]
        # No two files in the same entry ever propose the identical path.
        assert len({f["proposed_path"] for f in entry["files"]}) == len(entry["files"])

    def test_gallery_image_basename_collision_gets_disambiguated(self, client, db, tmp_path):
        """STUDIO-314: two gallery images with the same basename in different
        subfolders both flatten to proposed_dir/<basename> — apply forgives
        an image FileExistsError by skipping the move, so unlike an STL
        collision this wouldn't even fail loudly. Must be disambiguated the
        same way STL filenames already are (#1087)."""
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path)
        folder = Path(m.folder_path)
        sub_a, sub_b = folder / "a", folder / "b"
        sub_a.mkdir()
        sub_b.mkdir()
        img_a, img_b = sub_a / "cover.jpg", sub_b / "cover.jpg"
        img_a.write_bytes(b"one")
        img_b.write_bytes(b"two")
        m.image_paths = [str(img_a).replace("\\", "/"), str(img_b).replace("\\", "/")]
        db.commit()

        entry = client.get("/reorganize/preview").json()["entries"][0]
        image_moves = [f for f in entry["files"] if f["kind"] == "image"]
        assert len(image_moves) == 2
        proposed = {f["proposed_path"] for f in image_moves}
        assert len(proposed) == 2  # no collision — both get a real destination


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


class TestRootScopedPreview:
    """STUDIO-314: root_id now runs a coarse SQL prefix filter before the
    exact case-insensitive check, to avoid loading every model in the
    library just to discard most of them in Python. The SQL filter is only
    a narrowing pre-pass — this exercises that the exact result is
    unaffected (right models included, unrelated ones excluded, even when
    they sit on a same-prefix sibling root)."""

    def test_only_models_under_selected_root_are_included(self, client, db, tmp_path):
        root_a = tmp_path / "library-a"
        # Deliberately a prefix-sharing sibling, not a nested subdir — proves
        # the SQL LIKE pre-filter's "/"-anchored pattern isn't fooled into
        # treating "library-ab" as being under "library-a".
        root_b = tmp_path / "library-ab"
        root_a.mkdir()
        root_b.mkdir()
        ra = db.query(ScanRoot).filter_by(path=str(root_a)).first() or ScanRoot(path=str(root_a), enabled=True)
        rb = ScanRoot(path=str(root_b), enabled=True)
        db.add_all([ra, rb])
        db.commit()

        m_a = _model_with_file(db, root_a, creator_name="InA")
        m_b = _model_with_file(db, root_b, creator_name="InB")

        scoped = client.get("/reorganize/preview", params={"root_id": ra.id}).json()
        scoped_ids = {e["model_id"] for e in scoped["entries"]}
        assert m_a.id in scoped_ids
        assert m_b.id not in scoped_ids


class TestOverrideCapture:
    def test_pack_override_paths_captured(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path)
        db.add(PackOverride(path=m.folder_path))
        db.commit()

        entry = client.get("/reorganize/preview").json()["entries"][0]
        assert m.folder_path.replace("\\", "/") in entry["pack_override_paths"]


class TestSpansMultipleDirs:
    def test_files_in_one_descendant_directory_are_not_flagged(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _model_with_file(db, tmp_path, filename="a.stl", subdir="Alternative")
        source_dir = Path(m.folder_path)
        m.folder_path = str(source_dir.parent)
        db.commit()

        entry = client.get("/reorganize/preview").json()["entries"][0]

        assert entry["spans_multiple_dirs"] is False
        assert entry["source_path"] == str(source_dir.parent).replace("\\", "/")
        assert entry["source_directories"] == [str(source_dir).replace("\\", "/")]

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
        assert entry["source_directories"] == sorted([
            m.folder_path.replace("\\", "/"),
            str(other).replace("\\", "/"),
        ], key=str.casefold)
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


class TestManifestRetention:
    """STUDIO-313: a never-applied manifest must not survive a later preview —
    otherwise every resolved-field edit on the Reorganize page (each of which
    re-previews the whole library) leaves a dead row behind forever."""

    def test_prior_unapplied_manifest_pruned_on_next_preview(self, client, db, tmp_path):
        from app.models import ReorganizeManifest
        _root(db, tmp_path)
        _model_with_file(db, tmp_path)

        first_id = client.get("/reorganize/preview").json()["manifest_id"]
        assert db.query(ReorganizeManifest).filter_by(id=first_id).first() is not None

        second_id = client.get("/reorganize/preview").json()["manifest_id"]
        assert first_id != second_id
        assert db.query(ReorganizeManifest).filter_by(id=first_id).first() is None
        assert db.query(ReorganizeManifest).filter_by(id=second_id).first() is not None


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

    def test_moves_needed_excludes_a_blocked_mover(self, client, db, tmp_path):
        # A model missing its character still renders a "move"-kind entry (its
        # proposed dir differs from its current one via the sentinel), but
        # it's blocked (unclassifiable) — moves_needed should not count it as
        # a pending move until that's resolved (STUDIO-164).
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, title="Bust", filename="a.stl")
        blocked = _model_with_file(db, tmp_path, character=None, title="Lost", filename="b.stl")

        data = client.get("/reorganize/preview").json()
        by_id = {e["model_id"]: e for e in data["entries"]}
        blocked_entry = by_id[blocked.id]
        assert blocked_entry["kind"] in ("move", "rename", "case_rename")
        assert blocked_entry["eligible"] is False
        assert data["stats"]["moves_needed"] == 1

"""
Integration tests for the filesystem scanner's leaf detection and variant
grouping — the subsystem that has historically harboured the subtlest bugs.

Each test lays out a fake library under tmp_path, runs the real walk, and
asserts what got indexed (and how it grouped).
"""
import os
import re
import threading
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.models import Creator, Model, STLFile, VariantGroup
from app.services import scanner, name_parser
from app.services.job_runner import JobHandle, JobState
from app.services.scan_rules import IgnoreMatcher
from tests.conftest import make_creator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stl(folder: Path, name: str = "part.stl") -> None:
    """Create a folder containing one dummy STL file."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"solid x\nendsolid x\n")


def _img(folder: Path, name: str = "render.png") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"\x89PNG\r\n")


def _walk(db, creator: Creator, creator_dir: Path, group_by_character: bool = False) -> None:
    scanner._walk_for_models(
        folder=creator_dir, creator=creator, db=db,
        creator_boundary=creator_dir, character=None,
        stl_cache={}, last_scanned=None,
        group_by_character=group_by_character,
    )


def _models(db, creator: Creator) -> list[Model]:
    return db.query(Model).filter(Model.creator_id == creator.id).all()


def _rel(model: Model, creator_dir: Path) -> str:
    return str(Path(model.folder_path).relative_to(creator_dir))


# ---------------------------------------------------------------------------
# Leaf detection
# ---------------------------------------------------------------------------

class TestLeafDetection:
    def test_creator_root_with_type_keyword_is_not_collapsed(self, db, tmp_path):
        """A creator folder named like a type ('Tanuki Figures' -> 'figure')
        must NOT be indexed as one model; the walk descends into characters."""
        creator_dir = tmp_path / "Tanuki Figures"
        _stl(creator_dir / "Auron" / "STL")
        _stl(creator_dir / "Barbatos" / "STL")
        creator = make_creator(db, "Tanuki Figures")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        paths = {_rel(m, creator_dir) for m in models}
        assert "." not in paths                       # creator root never a model
        assert len(models) >= 2                        # descended into characters
        assert any("Auron" in p for p in paths)
        assert any("Barbatos" in p for p in paths)

    def test_folder_without_stls_is_not_a_model(self, db, tmp_path):
        """Render/image-only folders (no STLs in subtree) are never models,
        even when image filenames trip a scale/type signal."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Cloud Strife" / "STL" / "Bust")
        # Render folder with an image whose name contains type/scale signals
        _img(creator_dir / "Cloud Strife" / "Render Images", "Cloud_bust_75mm.png")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        paths = {_rel(m, creator_dir) for m in _models(db, creator)}
        assert not any("Render Images" in p for p in paths)
        assert any("Bust" in p for p in paths)

    def test_every_indexed_model_has_stls(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Knight" / "STL")
        _img(creator_dir / "Knight" / "Photos")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        for m in _models(db, creator):
            assert db.query(STLFile).filter(STLFile.model_id == m.id).count() > 0

    def test_creator_root_with_direct_stls_and_no_subfolders_is_indexed(self, db, tmp_path):
        """Regression (#1048): a creator whose own folder IS the product —
        STLs directly in the creator root, no character/product subfolder at
        all — previously indexed 0 models. "The creator boundary is never
        itself a model" (so real multi-character creators recurse past their
        own root) only makes sense when there's something to recurse into;
        with zero subdirectories, that rule silently dropped every file."""
        creator_dir = tmp_path / "SoloCreator"
        _stl(creator_dir, "part.stl")
        creator = make_creator(db, "SoloCreator")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 1
        assert db.query(STLFile).filter(STLFile.model_id == models[0].id).count() == 1

    def test_creator_root_with_direct_stls_and_a_character_subfolder_still_recurses(self, db, tmp_path):
        """Unaffected by the #1048 fix: when the creator root has direct STLs
        *and* a character subfolder also has STLs, any_child_stls is True, so
        the new fallback does not fire — existing behaviour (the loose direct
        files are not indexed as their own model) is unchanged."""
        creator_dir = tmp_path / "MixedCreator"
        _stl(creator_dir, "loose.stl")
        _stl(creator_dir / "Knight" / "STL")
        creator = make_creator(db, "MixedCreator")

        _walk(db, creator, creator_dir)

        paths = {_rel(m, creator_dir) for m in _models(db, creator)}
        assert "." not in paths
        assert any("Knight" in p for p in paths)


# ---------------------------------------------------------------------------
# Gallery images
# ---------------------------------------------------------------------------

class TestGalleryImages:
    def test_scan_populates_gallery_and_thumbnail_from_images(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Knight"
        _stl(model_dir / "STL")
        _img(model_dir / "Images", "render.png")
        _img(model_dir, "box.jpg")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        model = _models(db, creator)[0]
        render = str(model_dir / "Images" / "render.png")
        box = str(model_dir / "box.jpg")
        assert model.thumbnail_path == render
        assert model.image_paths == [render, box]

    def test_scan_prefers_image_dirs_before_direct_images(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Knight"
        _stl(model_dir)
        _img(model_dir, "a-direct.jpg")
        _img(model_dir / "Renders", "b-render.png")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        model = _models(db, creator)[0]
        assert model.image_paths[0] == str(model_dir / "Renders" / "b-render.png")
        assert model.image_paths[1] == str(model_dir / "a-direct.jpg")

    def test_scan_does_not_readd_removed_gallery_images(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Knight"
        _stl(model_dir)
        removed = model_dir / "render.png"
        kept = model_dir / "kept.png"
        _img(model_dir, removed.name)
        _img(model_dir, kept.name)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)
        model = _models(db, creator)[0]
        model.removed_image_paths = [str(removed)]
        db.commit()

        _walk(db, creator, creator_dir)
        db.refresh(model)

        assert str(removed) not in model.image_paths
        assert str(kept) in model.image_paths

    def test_scan_ignores_hidden_directories(self, db, tmp_path):
        """A hidden dot-directory (e.g. some other tool's own derivative-
        thumbnail cache) must never be walked into for images, and never
        become a model of its own (#888-follow-up)."""
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Knight"
        _stl(model_dir)
        _img(model_dir, "real_photo.jpg")
        hidden = model_dir / ".othertool" / "derivatives" / "real_photo.jpg"
        hidden.mkdir(parents=True)
        (hidden / "carousel.jpg").write_bytes(b"\x89PNG\r\n")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 1   # the hidden dir never became a model of its own
        model = models[0]
        assert model.image_paths == [str(model_dir / "real_photo.jpg")]

    def test_transient_read_error_does_not_prune_known_gallery_images(self, db, tmp_path, monkeypatch):
        """A gallery-discovery failure during a rescan (drive hiccup,
        permission blip) must never look identical to "no images here
        anymore" — a real, already-indexed gallery image must survive
        (#894-follow-up).

        Mocks _collect_gallery_images directly rather than breaking a real
        subdirectory: any unreadable folder is *also* caught earlier by the
        existing model-vs-container STL classification (_any_child_has_stls_cached),
        which aborts that whole creator's walk — a coarser, separately-tested
        safety net. This test isolates the finer-grained protection added
        specifically around the gallery merge.
        """
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Knight"
        _stl(model_dir)
        _img(model_dir, "real_photo.jpg")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)
        model = _models(db, creator)[0]
        assert model.image_paths == [str(model_dir / "real_photo.jpg")]

        def _boom(*a, **k):
            raise OSError("simulated read failure")

        monkeypatch.setattr(scanner, "_collect_gallery_images", _boom)

        _walk(db, creator, creator_dir)   # must not raise — and must not prune
        db.refresh(model)

        assert model.image_paths == [str(model_dir / "real_photo.jpg")]

    def test_scan_preserves_remote_and_user_added_gallery_paths(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Knight"
        _stl(model_dir)
        _img(model_dir, "render.png")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)
        model = _models(db, creator)[0]
        remote = "https://cdn.example.test/render.png"
        outside = str(tmp_path / "manual.png")
        model.image_paths = [remote, outside]
        db.commit()

        _walk(db, creator, creator_dir)
        db.refresh(model)

        assert model.image_paths == [str(model_dir / "render.png"), remote, outside]


# ---------------------------------------------------------------------------
# Configurable ignore patterns (#31, Phase 1)
# ---------------------------------------------------------------------------

class TestIgnorePatterns:
    def test_ignored_subtree_is_not_walked(self, db, tmp_path, monkeypatch):
        """A folder matching an ignore pattern — and everything beneath it — is
        skipped, while siblings still index."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Knight" / "STL")
        _stl(creator_dir / "WIP" / "HalfDone" / "STL")
        creator = make_creator(db, "Creator")

        monkeypatch.setattr(scanner, "_ignore_matcher", IgnoreMatcher(("wip",)))
        _walk(db, creator, creator_dir)

        paths = {_rel(m, creator_dir) for m in _models(db, creator)}
        assert any("Knight" in p for p in paths)
        assert not any("WIP" in p for p in paths)

    def test_creator_root_is_never_ignored(self, db, tmp_path, monkeypatch):
        """A pattern matching the creator boundary itself must not drop the whole
        creator — ignore is for sub-folders, not entire creators."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Knight" / "STL")
        creator = make_creator(db, "Creator")

        monkeypatch.setattr(scanner, "_ignore_matcher", IgnoreMatcher(("creator",)))
        _walk(db, creator, creator_dir)

        assert any("Knight" in _rel(m, creator_dir) for m in _models(db, creator))

    def test_prune_ignored_removes_nested_models(self, db, tmp_path, monkeypatch):
        """Models already indexed under a folder a NEW pattern now covers are
        pruned, including those nested below a bare-name match."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Knight" / "STL")
        _stl(creator_dir / "WIP" / "HalfDone" / "STL")
        creator = make_creator(db, "Creator")
        _walk(db, creator, creator_dir)
        assert len(_models(db, creator)) == 2  # nothing ignored on first walk

        monkeypatch.setattr(scanner, "_ignore_matcher", IgnoreMatcher(("wip",)))
        removed = scanner._prune_ignored(db, [str(tmp_path)])

        assert removed == 1
        paths = {_rel(m, creator_dir) for m in _models(db, creator)}
        assert any("Knight" in p for p in paths)
        assert not any("WIP" in p for p in paths)

    def test_prune_ignored_respects_cap(self, db, tmp_path, monkeypatch):
        """A pattern matching >50% of models is treated as a misconfiguration and
        skipped, not allowed to wipe the library."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "WIP_A" / "STL")
        _stl(creator_dir / "WIP_B" / "STL")
        _stl(creator_dir / "Knight" / "STL")
        creator = make_creator(db, "Creator")
        _walk(db, creator, creator_dir)
        before = len(_models(db, creator))

        monkeypatch.setattr(scanner, "_ignore_matcher", IgnoreMatcher(("wip*",)))
        removed = scanner._prune_ignored(db, [str(tmp_path)])

        assert removed == 0
        assert len(_models(db, creator)) == before

    def test_prune_ignored_skips_excluded(self, db, tmp_path, monkeypatch):
        """User-excluded models are already hidden; the ignore prune leaves them
        alone (mirrors _prune_stale_models)."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Knight" / "STL")
        _stl(creator_dir / "WIP" / "STL")
        creator = make_creator(db, "Creator")
        _walk(db, creator, creator_dir)
        wip = next(m for m in _models(db, creator) if "WIP" in m.folder_path)
        wip.excluded = True
        db.commit()

        monkeypatch.setattr(scanner, "_ignore_matcher", IgnoreMatcher(("wip",)))
        removed = scanner._prune_ignored(db, [str(tmp_path)])

        assert removed == 0
        assert any("WIP" in m.folder_path for m in _models(db, creator))


# ---------------------------------------------------------------------------
# Configurable tag-inference rules (#31, Phase 2)
# ---------------------------------------------------------------------------

class TestTagRules:
    def test_user_rule_adds_auto_tag(self, db, tmp_path):
        """A keyword→tag rule tags a model whose name contains the whole word."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Aztec Warrior" / "STL")
        creator = make_creator(db, "Creator")

        name_parser.set_tag_rules([(re.compile(r"\bAztec\b", re.I), "civ")])
        try:
            _walk(db, creator, creator_dir)
        finally:
            name_parser.set_tag_rules(None)

        m = next(m for m in _models(db, creator) if "Aztec" in m.folder_path)
        assert "civ" in (m.auto_tags or [])

    def test_no_rules_leaves_auto_tags_unchanged(self, db, tmp_path):
        name_parser.set_tag_rules(None)
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Aztec Warrior" / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        m = next(m for m in _models(db, creator) if "Aztec" in m.folder_path)
        assert "civ" not in (m.auto_tags or [])


# ---------------------------------------------------------------------------
# Configurable parts/structural folder names (#31, Phase 3)
# ---------------------------------------------------------------------------

class TestPartsNames:
    def test_default_splits_signal_subfolder(self, db, tmp_path):
        """Baseline: 'Golem' (no signal, direct STLs) with a 'Bust' sub-folder —
        'Bust' carries a product signal, so by default it splits into its own
        model rather than folding into Golem."""
        creator_dir = tmp_path / "A"
        _stl(creator_dir / "Golem")
        _stl(creator_dir / "Golem" / "Bust")
        creator = make_creator(db, "A")

        name_parser.set_parts_names(None)
        _walk(db, creator, creator_dir)

        assert any("Bust" in _rel(m, creator_dir) for m in _models(db, creator))

    def test_user_parts_folder_folds_into_parent_product(self, db, tmp_path):
        """With 'bust' configured as a parts name, the same layout collapses to a
        single 'Golem' model — the parts sub-folder is no longer split out."""
        creator_dir = tmp_path / "B"
        _stl(creator_dir / "Golem")
        _stl(creator_dir / "Golem" / "Bust")
        creator = make_creator(db, "B")

        name_parser.set_parts_names(frozenset({"bust"}))
        try:
            _walk(db, creator, creator_dir)
        finally:
            name_parser.set_parts_names(None)

        paths = {_rel(m, creator_dir) for m in _models(db, creator)}
        assert paths == {"Golem"}

    def test_is_structural_folder_honors_user_names(self):
        name_parser.set_parts_names(frozenset({"sprues"}))
        try:
            assert name_parser.is_structural_folder("Sprues") is True
        finally:
            name_parser.set_parts_names(None)
        # cleared → no longer structural
        assert name_parser.is_structural_folder("Sprues") is False


class TestNestedProductBoundaries:
    """A qualifying product folder must not absorb an independently qualifying child."""

    def test_product_parent_and_alternative_child_index_separately(self, db, tmp_path):
        creator_dir = tmp_path / "Abe3d"
        product = creator_dir / "2B" / "1_4 2B YoRHa - Abe3d"
        alternative = product / "Alternative"
        _stl(product, name="standard.stl")
        _stl(alternative, name="alternative.stl")
        creator = make_creator(db, "Abe3d")

        _walk(db, creator, creator_dir)

        by_path = {Path(m.folder_path): m for m in _models(db, creator)}
        assert set(by_path) == {product, alternative}
        assert {f.filename for f in by_path[product].stl_files} == {"standard.stl"}
        assert {f.filename for f in by_path[alternative].stl_files} == {"alternative.stl"}

    def test_empty_product_parent_does_not_become_phantom_model(self, db, tmp_path):
        creator_dir = tmp_path / "Abe3d"
        product = creator_dir / "2B" / "1_4 2B YoRHa"
        alternative = product / "Alternative"
        _stl(alternative, name="alternative.stl")
        creator = make_creator(db, "Abe3d")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert [Path(m.folder_path) for m in models] == [alternative]
        assert {f.filename for f in models[0].stl_files} == {"alternative.stl"}

    def test_structural_child_remains_owned_by_product_parent(self, db, tmp_path):
        creator_dir = tmp_path / "Abe3d"
        product = creator_dir / "2B" / "1_4 2B YoRHa"
        _stl(product / "STL", name="body.stl")
        creator = make_creator(db, "Abe3d")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert [Path(m.folder_path) for m in models] == [product]
        assert {f.filename for f in models[0].stl_files} == {"body.stl"}

    def test_rescan_transfers_existing_child_file_without_losing_metadata(self, db, tmp_path):
        creator_dir = tmp_path / "Abe3d"
        product = creator_dir / "2B" / "1_4 2B YoRHa"
        alternative = product / "Alternative"
        _stl(product, name="standard.stl")
        _stl(alternative, name="alternative.stl")
        creator = make_creator(db, "Abe3d")

        collapsed = Model(
            name="2B YoRHa",
            folder_path=str(product),
            creator_id=creator.id,
        )
        db.add(collapsed)
        db.flush()
        db.add(STLFile(
            model_id=collapsed.id,
            path=str(product / "standard.stl"),
            filename="standard.stl",
        ))
        child_file = STLFile(
            model_id=collapsed.id,
            path=str(alternative / "alternative.stl"),
            filename="alternative.stl",
            part_name="Custom alternate head",
        )
        db.add(child_file)
        db.commit()
        child_file_id = child_file.id

        _walk(db, creator, creator_dir)

        by_path = {Path(m.folder_path): m for m in _models(db, creator)}
        transferred = db.get(STLFile, child_file_id)
        assert transferred.model_id == by_path[alternative].id
        assert transferred.part_name == "Custom alternate head"
        assert {f.filename for f in by_path[product].stl_files} == {"standard.stl"}


# ---------------------------------------------------------------------------
# Configurable folder layouts — layout {tag} levels become model auto-tags
# ---------------------------------------------------------------------------

class TestLayoutTags:
    def test_layout_tags_become_auto_tags(self, db, tmp_path):
        """Tag folder names from levels above the creator are merged into every
        model's auto_tags, lower-cased and de-duplicated with detected signals."""
        creator_dir = tmp_path / "Abe3D"
        _stl(creator_dir / "Cloud" / "1-6 Bust")
        creator = make_creator(db, "Abe3D")

        scanner._walk_for_models(
            folder=creator_dir, creator=creator, db=db,
            creator_boundary=creator_dir, character=None,
            stl_cache={}, last_scanned=None,
            layout_tags=["Sci-Fi", "Mechs"],
        )

        models = _models(db, creator)
        assert models
        for m in models:
            assert "sci-fi" in m.auto_tags
            assert "mechs" in m.auto_tags
            # Detected signals still present alongside layout tags.
            assert "bust" in m.auto_tags

    def test_no_layout_tags_leaves_auto_tags_unchanged(self, db, tmp_path):
        creator_dir = tmp_path / "Abe3D"
        _stl(creator_dir / "Cloud" / "Bust")
        creator = make_creator(db, "Abe3D")

        _walk(db, creator, creator_dir)

        for m in _models(db, creator):
            assert "sci-fi" not in m.auto_tags

    def test_layout_tags_indexed_in_model_tags(self, db, tmp_path):
        """Layout tags flow through sync_model_tags into the model_tags index
        so they're filterable in the Library."""
        from app.models import ModelTag

        creator_dir = tmp_path / "Abe3D"
        _stl(creator_dir / "Cloud" / "Bust")
        creator = make_creator(db, "Abe3D")

        scanner._walk_for_models(
            folder=creator_dir, creator=creator, db=db,
            creator_boundary=creator_dir, character=None,
            stl_cache={}, last_scanned=None,
            layout_tags=["Sci-Fi"],
        )

        tags = {t.tag for t in db.query(ModelTag).all()}
        assert "sci-fi" in tags


# ---------------------------------------------------------------------------
# Variant grouping (character assignment)
# ---------------------------------------------------------------------------

class TestVariantGrouping:
    def test_variants_group_under_real_character(self, db, tmp_path):
        """Scale/support/container folders must not become the character — all
        of a character's variants share the character folder name."""
        creator_dir = tmp_path / "Creator"
        char = creator_dir / "Auron - Final Fantasy X"
        _stl(char / "STL" / "Bust")
        _stl(char / "STL" / "75mm Miniature")
        _stl(char / "Presupport" / "Bust")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 3
        assert {m.character for m in models} == {"Auron - Final Fantasy X"}

    def test_structural_folders_do_not_become_character(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Goblin" / "Unsupported")
        _stl(creator_dir / "Goblin" / "Supported")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {m.character for m in _models(db, creator)}
        assert chars == {"Goblin"}          # not "Unsupported"/"Supported"

    def test_support_variant_subfolders_group_across_parents(self, db, tmp_path):
        """DakkaDakka-style: a product whose 'supported' copy is one level shallower
        than its (double-nested) 'unsupported' copy must still group as one character."""
        creator_dir = tmp_path / "Creator"
        apc = creator_dir / "Crimson Wings" / "APC"
        _stl(apc / "Crimson Wings APC supported")
        # unsupported copy is double-nested, as the creator zipped it
        _stl(apc / "Crimson Wings APC unsupported" / "Crimson Wings APC unsupported")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 2
        assert len({m.character for m in models}) == 1     # one shared character → grouped

    def test_distinct_products_under_support_folder_stay_separate(self, db, tmp_path):
        """Loot-style: a Supported/Unsupported folder holding many *distinct* items
        must yield one character per item (grouping its support variants), not one
        giant bucket per support folder."""
        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Tavern Pack"
        for support in ("Environment_32mm_Supported_Solid", "Environment_32mm_UnSupported"):
            for item in ("AleCask", "Barrel", "Bench"):
                _stl(pack / support / f"{item}_32mm_{support.split('_')[-1]}")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        chars = {m.character for m in models}
        assert chars == {"AleCask", "Barrel", "Bench"}     # one character per item
        # each item has both support variants grouped under it
        from collections import Counter
        counts = Counter(m.character for m in models)
        assert all(c == 2 for c in counts.values())

    def test_ca3d_scale_variants_group_under_one_character(self, db, tmp_path):
        """CA3D-style: a character folder whose variant leaves carry the scale, the
        word 'scale', a creator tag, and a stray bust must collapse to ONE character,
        labelled by the clean character-folder name (not 'scale Ada Wong CA3D')."""
        creator_dir = tmp_path / "CA 3D Studios"
        char = creator_dir / "Ada Wong"
        _stl(char / "1-6 Ada Wong CA3D")
        _stl(char / "1-6 Ada Wong CA3D - Pre Supported")
        _stl(char / "1-9 scale Ada Wong CA3D")
        _stl(char / "1-9 scale Uncut Ada Wong CA3D")
        _stl(char / "STL Ada Wong Bust")
        creator = make_creator(db, "CA 3D Studios")

        _walk(db, creator, creator_dir)

        chars = {m.character for m in _models(db, creator)}
        assert chars == {"Ada Wong"}

    def test_flat_supported_unsupported_pair_groups(self, db, tmp_path):
        """DM Stash / Stepanov-style flat layout: variant folders sit DIRECTLY under
        the creator (no character folder). A Supported/Unsupported (or _STL/_NSFW_STL)
        pair sharing a normalised name must still group into one character."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Achtum of the Meadow - Supported")
        _stl(creator_dir / "Achtum of the Meadow - Unsupported")
        _stl(creator_dir / "Ahsoka_STL")
        _stl(creator_dir / "Ahsoka_NSFW_STL")
        _stl(creator_dir / "Angela Hardvin - Supported")   # a genuine singleton
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        from collections import Counter
        counts = Counter(m.character for m in _models(db, creator))
        # the two pairs collapse to one character each (2 models apiece)…
        assert counts.get("Achtum of the Meadow") == 2
        assert counts.get("Ahsoka") == 2
        # …and the singleton stays on its own
        assert counts.get("Angela Hardvin") == 1

    def test_faction_units_stay_separate_under_collection_folder(self, db, tmp_path):
        """Wargaming-style: a depth-1 folder is a faction of DISTINCT units, not a
        single character. Units must NOT collapse into one faction card even though
        each has support variants; faction context in the leaf name is preserved."""
        creator_dir = tmp_path / "One Page Rules"
        faction = creator_dir / "Human Defense Force"
        for unit in ("HDF - APC", "HDF - Bikers", "HDF - Commander"):
            _stl(faction / unit / f"{unit} supported")
            _stl(faction / unit / f"{unit} unsupported")
        creator = make_creator(db, "One Page Rules")

        _walk(db, creator, creator_dir)

        from collections import Counter
        counts = Counter(m.character for m in _models(db, creator))
        assert len(counts) == 3                       # one character per unit, not 1 faction
        assert all(c == 2 for c in counts.values())   # each unit groups its 2 support variants
        assert "Human Defense Force" not in counts    # the faction is not the character

    def test_model_directly_under_creator_singleton(self, db, tmp_path):
        """A lone product directly under the creator forms a single-member group
        (its own normalised name) — harmless, and renders as an individual card."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Solo Dragon")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 1
        # No grouping partner → either None or its own unique key; never merged.
        assert models[0].character in (None, "Solo Dragon")

    def test_pack_collapses_by_default(self, db, tmp_path):
        """By default a pack folder with a stray STL collapses into one model —
        splitting it into per-character models is an explicit, opt-in action
        (see TestSplitPack), not automatic."""
        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Six"
        _stl(pack, "head_new_hair.stl")          # stray loose part keeps it a single leaf
        for char in ("Electro", "Sandman", "Spiderman"):
            _stl(pack / char / "supported")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        names = {Path(m.folder_path).name for m in _models(db, creator)}
        assert "Sinister Six" in names


# ---------------------------------------------------------------------------
# Opt-in pack split (PackOverride)
# ---------------------------------------------------------------------------

class TestSplitPack:
    def test_pack_override_forces_split(self, db, tmp_path, monkeypatch):
        """A folder registered as a pack override is treated as a boundary on a
        normal walk — each child becomes its own model under its own name. This is
        the durable path that keeps an opt-in split applied across rescans."""
        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Six"
        _stl(pack, "stray.stl")                  # stray loose part is ignored
        for char in ("Electro", "Sandman", "Spiderman"):
            _stl(pack / char / "supported")
            _stl(pack / char / "unsupported")
        creator = make_creator(db, "Creator")

        monkeypatch.setattr(scanner, "_pack_overrides", {str(pack)})
        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert {m.character for m in models} == {"Electro", "Sandman", "Spiderman"}
        assert "Sinister Six" not in {Path(m.folder_path).name for m in models}

    def test_split_pack_replaces_model_and_records_override(self, db, tmp_path, monkeypatch):
        """split_pack() deletes the collapsed model, indexes each child, and
        persists a PackOverride so a later rescan stays split."""
        from sqlalchemy.orm import sessionmaker
        from app.models import PackOverride
        # split_pack opens its own SessionLocal(); use one factory on the test
        # engine for setup, the call, and assertions (fresh sessions each time).
        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)

        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Six"
        for char in ("Electro", "Sandman", "Spiderman"):
            _stl(pack / char / "supported")

        setup = Session()
        creator = Creator(name="Creator")
        setup.add(creator); setup.flush()
        creator_id = creator.id
        collapsed = Model(name="Sinister Six", folder_path=str(pack), creator_id=creator_id)
        setup.add(collapsed); setup.flush()
        collapsed_id = collapsed.id
        setup.add(STLFile(model_id=collapsed_id, path=str(pack / "x.stl"), filename="x.stl"))
        setup.commit(); setup.close()

        result = scanner.split_pack(collapsed_id)

        assert result["ok"] is True
        assert result["created"] == 3
        check = Session()
        # The pack folder itself is no longer a model (the original was replaced;
        # SQLite may reuse the freed id, so assert by folder_path, not id).
        assert check.query(Model).filter(Model.folder_path == str(pack)).first() is None
        chars = {m.character for m in check.query(Model).filter(Model.creator_id == creator_id)}
        assert chars == {"Electro", "Sandman", "Spiderman"}
        assert check.query(PackOverride).filter(PackOverride.path == str(pack)).count() == 1
        check.close()

    def test_split_pack_reports_error_on_unreadable_child(self, db, tmp_path, monkeypatch):
        """A child folder that fails to list (drive hiccup, permission blip)
        must come back as a clean {"ok": False, ...} the caller can show, not
        an unhandled 500 (#894-follow-up)."""
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)

        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Six"
        _stl(pack / "Electro", "head.stl")

        setup = Session()
        creator = Creator(name="Creator")
        setup.add(creator); setup.flush()
        collapsed = Model(name="Sinister Six", folder_path=str(pack), creator_id=creator.id)
        setup.add(collapsed); setup.flush()
        collapsed_id = collapsed.id
        setup.add(STLFile(model_id=collapsed_id, path=str(pack / "x.stl"), filename="x.stl"))
        setup.commit(); setup.close()

        monkeypatch.setattr(scanner, "_has_stls", lambda *a, **k: (_ for _ in ()).throw(OSError("simulated")))

        result = scanner.split_pack(collapsed_id)

        assert result["ok"] is False
        assert "try again" in result["message"]


# ---------------------------------------------------------------------------
# User-excluded models survive rescans
# ---------------------------------------------------------------------------

class TestExcludedPersistence:
    def test_rescan_does_not_resurrect_excluded_model(self, db, tmp_path):
        """A model the user excluded must stay excluded after a rescan of its
        folder — the walk skips it instead of re-indexing and clearing the flag."""
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Junk Cube"
        _stl(model_dir)
        creator = make_creator(db, "Creator")

        # First scan indexes the model, then the user excludes it.
        _walk(db, creator, creator_dir)
        model = _models(db, creator)[0]
        model.excluded = True
        db.commit()

        # Re-walk the same tree (a normal rescan).
        _walk(db, creator, creator_dir)

        db.refresh(model)
        assert model.excluded is True
        # Still exactly one model row; it was not duplicated or un-excluded.
        assert len(_models(db, creator)) == 1


# ---------------------------------------------------------------------------
# Regression: thumbnail discovery must not raise (the stl_cache NameError)
# ---------------------------------------------------------------------------

class TestRegressions:
    def test_thumbnail_discovery_does_not_raise(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        char = creator_dir / "Cloud Strife"
        _stl(char / "STL")
        _img(char / "Renders")                 # thumbnail to discover, no NameError
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)        # would raise NameError pre-fix

        assert len(_models(db, creator)) >= 1


# ---------------------------------------------------------------------------
# Phantom prune
# ---------------------------------------------------------------------------

class TestPrunePhantoms:
    def test_prunes_models_without_stls(self, db, tmp_path):
        creator = make_creator(db, "Creator")
        real = Model(name="real", folder_path="/x/real", creator_id=creator.id)
        phantom = Model(name="phantom", folder_path="/x/phantom", creator_id=creator.id)
        db.add_all([real, phantom])
        db.flush()
        db.add(STLFile(model_id=real.id, path="/x/real/a.stl", filename="a.stl"))
        db.commit()

        scanner._prune_phantoms(db)

        names = {m.name for m in db.query(Model).all()}
        assert names == {"real"}

    def test_safety_cap_skips_when_most_models_empty(self, db, tmp_path):
        """If >50% of models look empty, assume an indexing failure and prune nothing."""
        creator = make_creator(db, "Creator")
        real = Model(name="real", folder_path="/x/real", creator_id=creator.id)
        empties = [Model(name=f"e{i}", folder_path=f"/x/e{i}", creator_id=creator.id) for i in range(3)]
        db.add_all([real, *empties])
        db.flush()
        db.add(STLFile(model_id=real.id, path="/x/real/a.stl", filename="a.stl"))
        db.commit()

        scanner._prune_phantoms(db)        # 3/4 empty -> over the 50% cap

        assert db.query(Model).count() == 4   # nothing pruned

    def test_creator_scoped_prune_leaves_other_creators_alone(self, db, tmp_path):
        c1 = make_creator(db, "C1")
        c2 = make_creator(db, "C2")
        # c1 has a phantom; c2 has a phantom that must NOT be touched
        m1 = Model(name="c1-phantom", folder_path="/x/c1", creator_id=c1.id)
        m2 = Model(name="c2-phantom", folder_path="/x/c2", creator_id=c2.id)
        real = Model(name="c1-real", folder_path="/x/c1/real", creator_id=c1.id)
        db.add_all([m1, m2, real])
        db.flush()
        db.add(STLFile(model_id=real.id, path="/x/c1/real/a.stl", filename="a.stl"))
        db.commit()

        scanner._prune_phantoms(db, creator_id=c1.id)

        names = {m.name for m in db.query(Model).all()}
        assert names == {"c1-real", "c2-phantom"}

    def test_prune_removes_model_whose_stl_rows_were_cleared(self, db, tmp_path):
        """Simulates the stale-row case: a phantom model had STL rows from a
        previous scan. After scan_creator clears those rows and re-walks (finding
        no STLs), the model must have zero rows and _prune_phantoms must delete it."""
        creator = make_creator(db, "LA Figures")
        phantom = Model(name="phantom-with-stale-rows", folder_path="/x/phantom", creator_id=creator.id)
        real = Model(name="real", folder_path="/x/real", creator_id=creator.id)
        db.add_all([phantom, real])
        db.flush()
        # Phantom has a stale STL row; real has a live one
        db.add(STLFile(model_id=phantom.id, path="/x/phantom/old.stl", filename="old.stl"))
        db.add(STLFile(model_id=real.id, path="/x/real/a.stl", filename="a.stl"))
        db.commit()

        # Simulate what scan_creator does: clear all STL rows, then re-walk
        # (re-walk only re-adds real's file, not phantom's)
        from app.models import STLFile as SF
        db.query(SF).filter(SF.model_id.in_([phantom.id, real.id])).delete(synchronize_session=False)
        db.commit()
        db.add(STLFile(model_id=real.id, path="/x/real/a.stl", filename="a.stl"))
        db.commit()

        scanner._prune_phantoms(db, creator_id=creator.id)

        names = {m.name for m in db.query(Model).all()}
        assert names == {"real"}


# ---------------------------------------------------------------------------
# Stale-model prune (#53)
# ---------------------------------------------------------------------------

class TestPruneStaleModels:
    def test_prunes_unvisited_models_under_scanned_root(self, db, tmp_path):
        """Models under a scanned root whose updated_at predates the scan start
        were not visited and must be pruned after a full scan."""
        from datetime import timedelta
        from app.utils import utcnow

        root = str(tmp_path)
        creator = make_creator(db, "Creator")
        old_ts = utcnow() - timedelta(hours=1)
        stale = Model(name="stale", folder_path=str(tmp_path / "stale"),
                      creator_id=creator.id, updated_at=old_ts)
        fresh = Model(name="fresh", folder_path=str(tmp_path / "fresh"),
                      creator_id=creator.id, updated_at=utcnow())
        db.add_all([stale, fresh])
        db.flush()
        db.add(STLFile(model_id=stale.id, path=str(tmp_path / "stale/a.stl"), filename="a.stl"))
        db.add(STLFile(model_id=fresh.id, path=str(tmp_path / "fresh/a.stl"), filename="a.stl"))
        db.commit()

        scan_start = utcnow() - timedelta(minutes=30)
        scanner._prune_stale_models(db, scan_start, [root])

        names = {m.name for m in db.query(Model).all()}
        assert "stale" not in names
        assert "fresh" in names

    def test_protected_creator_models_are_never_pruned(self, db, tmp_path):
        """A creator whose walk failed this run only partially re-indexed its models,
        so an old updated_at reflects a transient error, not a deleted folder. Those
        models must be exempt from the stale prune (STUDIO-79) — otherwise a lock or
        mount hiccup silently wipes live data. Models under other creators still
        prune normally."""
        from datetime import timedelta
        from app.utils import utcnow

        root = str(tmp_path)
        failed = make_creator(db, "FailedCreator")
        ok = make_creator(db, "OkCreator")
        old_ts = utcnow() - timedelta(hours=1)

        # Both look "stale" (updated_at predates scan_start), but only OkCreator's
        # walk completed cleanly this run.
        protected = Model(name="protected", folder_path=str(tmp_path / "protected"),
                          creator_id=failed.id, updated_at=old_ts)
        prunable = Model(name="prunable", folder_path=str(tmp_path / "prunable"),
                         creator_id=ok.id, updated_at=old_ts)
        # Two fresh OkCreator models keep prunable at 1/3 of the eligible set, below
        # the 50% safety cap (protected is excluded from the count entirely).
        fresh1 = Model(name="fresh1", folder_path=str(tmp_path / "fresh1"),
                       creator_id=ok.id, updated_at=utcnow())
        fresh2 = Model(name="fresh2", folder_path=str(tmp_path / "fresh2"),
                       creator_id=ok.id, updated_at=utcnow())
        db.add_all([protected, prunable, fresh1, fresh2])
        db.commit()

        scan_start = utcnow() - timedelta(minutes=30)
        scanner._prune_stale_models(
            db, scan_start, [root], protected_creator_ids={failed.id}
        )

        names = {m.name for m in db.query(Model).all()}
        assert "protected" in names     # walk failed → shielded despite stale ts
        assert "prunable" not in names  # clean walk, not visited → pruned

    def test_safety_cap_skips_when_most_models_stale(self, db, tmp_path):
        """If >50% of models under the root were not visited, assume a failed scan
        and skip pruning."""
        from datetime import timedelta
        from app.utils import utcnow

        root = str(tmp_path)
        creator = make_creator(db, "Creator")
        old_ts = utcnow() - timedelta(hours=1)
        scan_start = utcnow() - timedelta(minutes=30)

        # 3 stale, 1 fresh → 75% stale → safety cap triggers
        for i in range(3):
            m = Model(name=f"stale{i}", folder_path=str(tmp_path / f"s{i}"),
                      creator_id=creator.id, updated_at=old_ts)
            db.add(m)
        fresh = Model(name="fresh", folder_path=str(tmp_path / "fresh"),
                      creator_id=creator.id, updated_at=utcnow())
        db.add(fresh)
        db.commit()

        scanner._prune_stale_models(db, scan_start, [root])

        assert db.query(Model).count() == 4   # nothing pruned

    def test_models_outside_scanned_roots_are_not_touched(self, db, tmp_path):
        """Models under a different root must never be pruned even if their
        updated_at predates the scan start."""
        from datetime import timedelta
        from app.utils import utcnow

        root_a = tmp_path / "rootA"
        root_b = tmp_path / "rootB"
        creator = make_creator(db, "Creator")
        old_ts = utcnow() - timedelta(hours=1)
        scan_start = utcnow() - timedelta(minutes=30)

        # One stale + two fresh under root_a (33% stale → below safety cap)
        stale1 = Model(name="stale1", folder_path=str(root_a / "s1"),
                       creator_id=creator.id, updated_at=old_ts)
        fresh1 = Model(name="fresh1", folder_path=str(root_a / "f1"),
                       creator_id=creator.id, updated_at=utcnow())
        fresh2 = Model(name="fresh2", folder_path=str(root_a / "f2"),
                       creator_id=creator.id, updated_at=utcnow())
        in_b = Model(name="in_b", folder_path=str(root_b / "model"),
                     creator_id=creator.id, updated_at=old_ts)
        db.add_all([stale1, fresh1, fresh2, in_b])
        db.flush()
        for m, rel in [(stale1, root_a / "s1"), (fresh1, root_a / "f1"),
                       (fresh2, root_a / "f2"), (in_b, root_b / "model")]:
            db.add(STLFile(model_id=m.id, path=str(rel / "a.stl"), filename="a.stl"))
        db.commit()

        # Only scanning root_a
        scanner._prune_stale_models(db, scan_start, [str(root_a)])

        names = {m.name for m in db.query(Model).all()}
        assert "stale1" not in names    # under scanned root, not visited → pruned
        assert "fresh1" in names        # visited → kept
        assert "fresh2" in names
        assert "in_b" in names          # outside scanned root → preserved

    def test_excluded_models_are_never_pruned(self, db, tmp_path):
        """A user-excluded model keeps an old updated_at (the walk returns before
        bumping it), so it must be exempt from the stale prune — otherwise a later
        scan would resurrect the folder as a brand-new, non-excluded model."""
        from datetime import timedelta
        from app.utils import utcnow

        root = str(tmp_path)
        creator = make_creator(db, "Creator")
        old_ts = utcnow() - timedelta(hours=1)
        scan_start = utcnow() - timedelta(minutes=30)

        excluded = Model(name="excluded", folder_path=str(tmp_path / "excluded"),
                         creator_id=creator.id, updated_at=old_ts, excluded=True)
        fresh = Model(name="fresh", folder_path=str(tmp_path / "fresh"),
                      creator_id=creator.id, updated_at=utcnow())
        db.add_all([excluded, fresh])
        db.commit()

        scanner._prune_stale_models(db, scan_start, [root])

        names = {m.name for m in db.query(Model).all()}
        assert "excluded" in names      # exempt despite stale updated_at
        assert "fresh" in names

    def test_sibling_root_sharing_name_prefix_not_matched(self, db, tmp_path):
        """A scan root must only match its true descendants, not a sibling whose
        name merely shares a string prefix ('STL' vs 'STLBackup')."""
        from datetime import timedelta
        from app.utils import utcnow

        scanned = tmp_path / "STL"
        sibling = tmp_path / "STLBackup"      # NOT a scan root, never walked
        creator = make_creator(db, "Creator")
        old_ts = utcnow() - timedelta(hours=1)
        scan_start = utcnow() - timedelta(minutes=30)

        # 1 stale + 2 fresh under the scanned root (below the 50% cap)
        stale = Model(name="stale", folder_path=str(scanned / "s"),
                      creator_id=creator.id, updated_at=old_ts)
        f1 = Model(name="f1", folder_path=str(scanned / "f1"),
                   creator_id=creator.id, updated_at=utcnow())
        f2 = Model(name="f2", folder_path=str(scanned / "f2"),
                   creator_id=creator.id, updated_at=utcnow())
        in_sibling = Model(name="in_sibling", folder_path=str(sibling / "m"),
                           creator_id=creator.id, updated_at=old_ts)
        db.add_all([stale, f1, f2, in_sibling])
        db.commit()

        scanner._prune_stale_models(db, scan_start, [str(scanned)])

        names = {m.name for m in db.query(Model).all()}
        assert "stale" not in names         # true descendant, not visited → pruned
        assert "in_sibling" in names        # prefix-sharing sibling → never matched

    def test_null_updated_at_is_not_pruned(self, db, tmp_path):
        """A model with no updated_at timestamp is not "stale" — it must be left
        alone. Pins the NULL-timestamp filter after the two prune queries were
        collapsed into a single fetch + Python filter (#653)."""
        from datetime import timedelta
        from app.utils import utcnow

        root = str(tmp_path)
        creator = make_creator(db, "Creator")
        scan_start = utcnow() - timedelta(minutes=30)

        no_ts = Model(name="no_ts", folder_path=str(tmp_path / "no_ts"),
                      creator_id=creator.id)
        fresh = Model(name="fresh", folder_path=str(tmp_path / "fresh"),
                      creator_id=creator.id, updated_at=utcnow())
        db.add_all([no_ts, fresh])
        db.commit()
        # Column default=utcnow fills updated_at on INSERT; force a true NULL to
        # exercise the "no timestamp" branch (explicit value overrides onupdate).
        db.query(Model).filter(Model.name == "no_ts").update({Model.updated_at: None})
        db.commit()

        scanner._prune_stale_models(db, scan_start, [root])

        names = {m.name for m in db.query(Model).all()}
        assert "no_ts" in names          # NULL updated_at → not stale → preserved
        assert "fresh" in names

    def test_wildcard_chars_in_root_path_match_literally(self, db, tmp_path):
        """Root/folder names routinely contain '_', a SQL LIKE wildcard. Matching
        must be literal so an unrelated path doesn't get pulled into the prune."""
        from datetime import timedelta
        from app.utils import utcnow

        root = tmp_path / "3D_STLs"            # '_' would be a LIKE wildcard
        creator = make_creator(db, "Creator")
        old_ts = utcnow() - timedelta(hours=1)
        scan_start = utcnow() - timedelta(minutes=30)

        # Under the real root: 1 stale + 2 fresh (below cap)
        stale = Model(name="stale", folder_path=str(root / "s"),
                      creator_id=creator.id, updated_at=old_ts)
        f1 = Model(name="f1", folder_path=str(root / "f1"),
                   creator_id=creator.id, updated_at=utcnow())
        f2 = Model(name="f2", folder_path=str(root / "f2"),
                   creator_id=creator.id, updated_at=utcnow())
        # A path that a LIKE '3D_STLs%' pattern would wrongly match ('_' = any char)
        decoy = Model(name="decoy", folder_path=str(tmp_path / "3DXSTLs" / "m"),
                      creator_id=creator.id, updated_at=old_ts)
        db.add_all([stale, f1, f2, decoy])
        db.commit()

        scanner._prune_stale_models(db, scan_start, [str(root)])

        names = {m.name for m in db.query(Model).all()}
        assert "stale" not in names         # genuine descendant → pruned
        assert "decoy" in names             # only matched by a '_' wildcard → preserved


# ---------------------------------------------------------------------------
# Mount-detach guard — never destructively prune an offline root
# ---------------------------------------------------------------------------

class TestRootAvailable:
    def test_existing_nonempty_dir_is_available(self, tmp_path):
        (tmp_path / "creator").mkdir()
        assert scanner._root_available(str(tmp_path)) is True

    def test_empty_dir_is_unavailable(self, tmp_path):
        """A detached bind/network mount leaves an empty mountpoint behind —
        emptiness is the unmount signal, not absence."""
        empty = tmp_path / "mnt"
        empty.mkdir()
        assert scanner._root_available(str(empty)) is False

    def test_missing_path_is_unavailable(self, tmp_path):
        assert scanner._root_available(str(tmp_path / "gone")) is False


class TestPruneStalePaths:
    def _model(self, db, creator, name, folder: Path, on_disk: bool = True):
        m = Model(name=name, folder_path=str(folder), creator_id=creator.id)
        db.add(m)
        db.flush()
        db.add(STLFile(model_id=m.id, path=str(folder / "a.stl"), filename="a.stl"))
        if on_disk:
            _stl(folder)
        db.commit()
        return m

    def test_renamed_folder_under_online_root_is_pruned(self, db, tmp_path):
        """Legit behaviour preserved: under a mounted root, a model whose folder
        was renamed away (now missing) is pruned, siblings kept."""
        creator = make_creator(db, "Creator")
        self._model(db, creator, "kept1", tmp_path / "kept1")
        self._model(db, creator, "kept2", tmp_path / "kept2")
        self._model(db, creator, "renamed", tmp_path / "old_name", on_disk=False)

        assert scanner._prune_stale_paths(db, [str(tmp_path)]) == 1
        names = {m.name for m in db.query(Model).all()}
        assert names == {"kept1", "kept2"}

    def test_detached_mount_prunes_nothing(self, db, tmp_path):
        """The incident: an offline (empty/missing) root must yield NO available
        paths, so every model under it is protected even though its folder is gone."""
        creator = make_creator(db, "Creator")
        root = tmp_path / "mnt" / "drive1"
        for i in range(3):
            self._model(db, creator, f"m{i}", root / f"m{i}", on_disk=False)

        # No available roots passed (mount detached) → nothing pruned.
        assert scanner._prune_stale_paths(db, []) == 0
        assert db.query(Model).count() == 3
        assert db.query(STLFile).count() == 3

    def test_collection_links_survive_detached_mount(self, db, tmp_path):
        """Direct regression for the data loss: collection memberships must not be
        cascade-deleted when a mount detaches."""
        from app.models import Collection, CollectionModel
        creator = make_creator(db, "Creator")
        root = tmp_path / "mnt" / "drive1"
        m = self._model(db, creator, "m", root / "m", on_disk=False)
        coll = Collection(name="Favourites")
        db.add(coll)
        db.flush()
        db.add(CollectionModel(collection_id=coll.id, model_id=m.id))
        db.commit()

        scanner._prune_stale_paths(db, [])  # offline root → no available paths

        assert db.query(CollectionModel).count() == 1
        assert db.query(Model).count() == 1

    def test_only_offline_root_models_protected_others_pruned(self, db, tmp_path):
        """Two roots: the online one still gets its legit rename cleanup; the
        offline one's models are left untouched."""
        creator = make_creator(db, "Creator")
        online = tmp_path / "online"
        offline = tmp_path / "offline"
        # online root: 1 missing (rename) + 2 present → 33%, below cap → pruned
        self._model(db, creator, "on_kept1", online / "k1")
        self._model(db, creator, "on_kept2", online / "k2")
        self._model(db, creator, "on_renamed", online / "old", on_disk=False)
        # offline root models (folders gone with the mount)
        self._model(db, creator, "off1", offline / "o1", on_disk=False)
        self._model(db, creator, "off2", offline / "o2", on_disk=False)

        # Only the online root is reported available.
        removed = scanner._prune_stale_paths(db, [str(online)])
        assert removed == 1
        names = {m.name for m in db.query(Model).all()}
        assert names == {"on_kept1", "on_kept2", "off1", "off2"}

    def test_safety_cap_blocks_mass_delete(self, db, tmp_path):
        """Even under an online root, deleting >50% looks like a botched run, so
        the shared cap blocks it."""
        creator = make_creator(db, "Creator")
        self._model(db, creator, "kept", tmp_path / "kept")
        self._model(db, creator, "gone1", tmp_path / "g1", on_disk=False)
        self._model(db, creator, "gone2", tmp_path / "g2", on_disk=False)

        assert scanner._prune_stale_paths(db, [str(tmp_path)]) == 0
        assert db.query(Model).count() == 3

    def test_models_outside_any_online_root_untouched(self, db, tmp_path):
        """A model whose folder is gone but sits under no available root is left
        alone (errs toward keeping data)."""
        creator = make_creator(db, "Creator")
        online = tmp_path / "online"
        self._model(db, creator, "kept1", online / "k1")
        self._model(db, creator, "kept2", online / "k2")
        orphan = tmp_path / "elsewhere"
        self._model(db, creator, "orphan", orphan / "o", on_disk=False)

        assert scanner._prune_stale_paths(db, [str(online)]) == 0
        assert "orphan" in {m.name for m in db.query(Model).all()}


class TestPruneStaleStlFiles:
    """_index_stl_files only ever adds rows by exact path — a file renamed
    outside the app (e.g. a bulk lowercase/hyphenate pass) leaves its old
    STLFile row behind forever, pointing at a path that no longer exists,
    even though the model's folder is fine and the file is right there under
    its new name. _prune_stale_stl_files is the cleanup for that."""

    def _model_with_files(self, db, creator, name, folder: Path, stale_count: int = 1, live_count: int = 1):
        m = Model(name=name, folder_path=str(folder), creator_id=creator.id)
        db.add(m)
        db.flush()
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(live_count):
            fname = f"live_{i}.stl"
            (folder / fname).write_bytes(b"solid x\nendsolid x\n")
            db.add(STLFile(model_id=m.id, path=str(folder / fname), filename=fname))
        for i in range(stale_count):
            # Recorded path never created on disk — simulates a file that's
            # since been renamed/removed outside the app.
            db.add(STLFile(model_id=m.id, path=str(folder / f"Stale_Old_Name_{i}.stl"), filename=f"Stale_Old_Name_{i}.stl"))
        db.commit()
        return m

    def test_stale_row_removed_live_row_kept(self, db, tmp_path):
        creator = make_creator(db, "Creator")
        self._model_with_files(db, creator, "m", tmp_path / "m", stale_count=1, live_count=1)

        removed = scanner._prune_stale_stl_files(db, [str(tmp_path)])

        assert removed == 1
        paths = {f.path for f in db.query(STLFile).all()}
        assert len(paths) == 1
        assert "live_0.stl" in list(paths)[0]

    def test_model_with_no_stale_rows_untouched(self, db, tmp_path):
        creator = make_creator(db, "Creator")
        self._model_with_files(db, creator, "m", tmp_path / "m", stale_count=0, live_count=2)

        assert scanner._prune_stale_stl_files(db, [str(tmp_path)]) == 0
        assert db.query(STLFile).count() == 2

    def test_detached_mount_prunes_nothing(self, db, tmp_path):
        """Mirrors _prune_stale_paths: no available roots (mount detached) must
        protect every row, even ones that would otherwise look stale."""
        creator = make_creator(db, "Creator")
        self._model_with_files(db, creator, "m", tmp_path / "m", stale_count=2, live_count=1)

        assert scanner._prune_stale_stl_files(db, []) == 0
        assert db.query(STLFile).count() == 3

    def test_model_whose_own_folder_is_missing_is_skipped(self, db, tmp_path):
        """A model with no folder at all is _prune_stale_paths's job, not this
        one — pruning its STL rows here too would just be redundant work on
        data about to be cascade-deleted anyway, so this prune leaves it alone."""
        creator = make_creator(db, "Creator")
        folder = tmp_path / "gone"
        m = Model(name="m", folder_path=str(folder), creator_id=creator.id)
        db.add(m)
        db.flush()
        db.add(STLFile(model_id=m.id, path=str(folder / "a.stl"), filename="a.stl"))
        db.commit()

        assert scanner._prune_stale_stl_files(db, [str(tmp_path)]) == 0
        assert db.query(STLFile).count() == 1

    def test_protected_creator_untouched(self, db, tmp_path):
        creator = make_creator(db, "Creator")
        m = self._model_with_files(db, creator, "m", tmp_path / "m", stale_count=1, live_count=1)

        removed = scanner._prune_stale_stl_files(db, [str(tmp_path)], protected_creator_ids={creator.id})

        assert removed == 0
        assert db.query(STLFile).filter(STLFile.model_id == m.id).count() == 2

    def test_models_outside_any_online_root_untouched(self, db, tmp_path):
        creator = make_creator(db, "Creator")
        online = tmp_path / "online"
        self._model_with_files(db, creator, "in_root", online / "m", stale_count=1, live_count=1)
        elsewhere = tmp_path / "elsewhere"
        self._model_with_files(db, creator, "outside", elsewhere / "m", stale_count=1, live_count=1)

        removed = scanner._prune_stale_stl_files(db, [str(online)])

        assert removed == 1
        # The outside-root model's stale row survives untouched.
        outside_model = db.query(Model).filter(Model.name == "outside").one()
        assert db.query(STLFile).filter(STLFile.model_id == outside_model.id).count() == 2

    def test_safety_cap_blocks_mass_delete(self, db, tmp_path):
        creator = make_creator(db, "Creator")
        # 1 live + 3 stale = 75% stale, above the shared 50% cap.
        self._model_with_files(db, creator, "m", tmp_path / "m", stale_count=3, live_count=1)

        assert scanner._prune_stale_stl_files(db, [str(tmp_path)]) == 0
        assert db.query(STLFile).count() == 4


class TestScanAllRootsMountGate:
    """The gate lives in scan_all_roots: only roots confirmed online may feed the
    destructive prunes. _scan_root and the prunes are stubbed so we can assert the
    paths handed to them without spinning up worker-thread DB sessions."""

    def _wire(self, db, monkeypatch):
        captured: dict = {}

        def _cap(key):
            def _fn(_db, *args, **kwargs):
                captured[key] = args[-1]
                return 0
            return _fn

        monkeypatch.setattr(scanner, "_scan_root", lambda *a, **k: set())
        monkeypatch.setattr(scanner, "_prune_stale_models", _cap("stale_models"))
        monkeypatch.setattr(scanner, "_prune_stale_paths", _cap("stale_paths"))
        monkeypatch.setattr(scanner, "_prune_ignored", _cap("ignored"))
        monkeypatch.setattr(scanner, "_prune_slicer_files", lambda *a, **k: None)
        monkeypatch.setattr(scanner, "_prune_phantoms", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "prune_empty_creators", lambda *a, **k: None)
        return captured

    def test_offline_root_excluded_from_prunes(self, db, tmp_path, monkeypatch):
        from app.models import ScanRoot
        db.add(ScanRoot(path=str(tmp_path), enabled=True))  # empty → offline
        db.commit()
        captured = self._wire(db, monkeypatch)

        scanner.scan_all_roots(db)

        assert captured["stale_paths"] == []
        assert captured["stale_models"] == []
        assert captured["ignored"] == []
        assert scanner.get_status()["offline_roots"] == [str(tmp_path)]

    def test_online_root_feeds_prunes(self, db, tmp_path, monkeypatch):
        from app.models import ScanRoot
        (tmp_path / "creator").mkdir()  # non-empty → online
        db.add(ScanRoot(path=str(tmp_path), enabled=True))
        db.commit()
        captured = self._wire(db, monkeypatch)

        scanner.scan_all_roots(db)

        assert captured["stale_paths"] == [str(tmp_path)]
        assert captured["stale_models"] == [str(tmp_path)]


# ---------------------------------------------------------------------------
# Per-creator bootstrap (#50)
# ---------------------------------------------------------------------------

class TestCreatorDirsByName:
    def test_finds_creator_folder_under_scan_root(self, db, tmp_path):
        """_creator_dirs_by_name returns the matching creator directory when the
        creator has zero indexed models (bootstrap case)."""
        from app.models import ScanRoot

        creator_dir = tmp_path / "Abe3D"
        creator_dir.mkdir()
        (creator_dir / "Cloud" / "STL").mkdir(parents=True)

        root = ScanRoot(path=str(tmp_path), layout="{creator}", enabled=True)
        db.add(root)
        db.commit()

        results = scanner._creator_dirs_by_name("Abe3D", db)
        paths = [str(p) for p, *_ in results]
        assert str(creator_dir) in paths

    def test_case_insensitive_name_match(self, db, tmp_path):
        """Name matching is case-insensitive — 'abe3d' matches 'Abe3D' on disk."""
        from app.models import ScanRoot

        creator_dir = tmp_path / "Abe3D"
        creator_dir.mkdir()

        root = ScanRoot(path=str(tmp_path), layout="{creator}", enabled=True)
        db.add(root)
        db.commit()

        results = scanner._creator_dirs_by_name("abe3d", db)
        assert any(p == creator_dir for p, *_ in results)

    def test_no_match_returns_empty(self, db, tmp_path):
        """Returns an empty list when no creator folder matches the name."""
        from app.models import ScanRoot

        (tmp_path / "SomeOtherCreator").mkdir()
        root = ScanRoot(path=str(tmp_path), layout="{creator}", enabled=True)
        db.add(root)
        db.commit()

        results = scanner._creator_dirs_by_name("NonExistent", db)
        assert results == []


# ---------------------------------------------------------------------------
# resolve_creator (#217)
# ---------------------------------------------------------------------------

class TestResolveCreator:
    def test_case_insensitive_match(self, db):
        existing = make_creator(db, name="abe3d")
        assert scanner.resolve_creator("Abe3D", db).id == existing.id

    def test_underscore_is_not_a_wildcard(self, db):
        # ilike treated _ as 'any char': 'My_Studio' matched 'MyXStudio' (#217)
        decoy = make_creator(db, name="MyXStudio")
        resolved = scanner.resolve_creator("My_Studio", db)
        assert resolved.id != decoy.id
        assert resolved.name == "My_Studio"

    def test_percent_is_not_a_wildcard(self, db):
        decoy = make_creator(db, name="Anything At All")
        resolved = scanner.resolve_creator("%", db)
        assert resolved.id != decoy.id
        assert resolved.name == "%"

    def test_distinct_rows_for_wildcard_lookalikes(self, db):
        # Acceptance case from the issue: ab_cd and abXcd stay distinct.
        a = scanner.resolve_creator("ab_cd", db)
        b = scanner.resolve_creator("abXcd", db)
        assert a.id != b.id

    def test_creates_when_missing(self, db):
        created = scanner.resolve_creator("Brand New", db)
        assert created.id is not None
        assert scanner.resolve_creator("brand new", db).id == created.id


# ---------------------------------------------------------------------------
# Slicer project file exclusion (#206)
# ---------------------------------------------------------------------------

class TestSlicerFileExclusion:
    def test_walk_indexes_stl_but_not_slicer_files(self, db, tmp_path):
        """A model folder holding printable geometry plus slicer projects must
        index only the printable files."""
        creator_dir = tmp_path / "Creator"
        folder = creator_dir / "Dragon"
        _stl(folder, "dragon.stl")
        (folder / "dragon.lys").write_bytes(b"lychee project")
        (folder / "dragon.chitubox").write_bytes(b"chitubox project")
        (folder / "dragon.ctb").write_bytes(b"sliced output")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        filenames = {f.filename for f in db.query(STLFile).all()}
        assert filenames == {"dragon.stl"}

    def test_indexed_stl_gets_a_part_name_derived_from_its_filename(self, db, tmp_path):
        """A freshly indexed file gets a real, saved part_name immediately —
        not just the dimmed filename-derived placeholder the UI otherwise
        shows for a genuinely empty one."""
        creator_dir = tmp_path / "Creator"
        folder = creator_dir / "Dragon"
        _stl(folder, "blazing-quartz-lanterns-and-horseshoes.stl")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        f = db.query(STLFile).filter(STLFile.filename == "blazing-quartz-lanterns-and-horseshoes.stl").one()
        assert f.part_name == "Blazing Quartz Lanterns And Horseshoes"

    def test_reindexing_never_overwrites_an_already_set_part_name(self, db, tmp_path):
        """_index_stl_files is additive-only — it must never touch an
        existing row, including one whose part_name a user has since edited
        by hand (or an AI Organize suggestion changed) to something that
        no longer matches the filename-derived auto-name."""
        creator_dir = tmp_path / "Creator"
        folder = creator_dir / "Dragon"
        _stl(folder, "dragon.stl")
        creator = make_creator(db, "Creator")
        _walk(db, creator, creator_dir)

        f = db.query(STLFile).filter(STLFile.filename == "dragon.stl").one()
        f.part_name = "Custom Renamed Part"
        db.commit()

        _walk(db, creator, creator_dir)  # rescan — file already indexed

        db.refresh(f)
        assert f.part_name == "Custom Renamed Part"

    def test_prune_removes_indexed_slicer_rows_only(self, db):
        """Rows indexed by older scanner versions are pruned; printable rows
        and the owning model survive."""
        creator = make_creator(db, "Creator")
        m = Model(name="m", folder_path="/x/m", creator_id=creator.id)
        db.add(m)
        db.flush()
        db.add(STLFile(model_id=m.id, path="/x/m/a.stl", filename="a.stl"))
        db.add(STLFile(model_id=m.id, path="/x/m/a.chitubox", filename="a.chitubox"))
        db.add(STLFile(model_id=m.id, path="/x/m/UPPER.LYS", filename="UPPER.LYS"))
        db.add(STLFile(model_id=m.id, path="/x/m/b.pwx", filename="b.pwx"))
        db.commit()

        scanner._prune_slicer_files(db)

        filenames = {f.filename for f in db.query(STLFile).all()}
        assert filenames == {"a.stl"}
        assert db.query(Model).count() == 1

    def test_prune_noop_when_no_slicer_rows(self, db):
        creator = make_creator(db, "Creator")
        m = Model(name="m", folder_path="/x/m", creator_id=creator.id)
        db.add(m)
        db.flush()
        db.add(STLFile(model_id=m.id, path="/x/m/a.stl", filename="a.stl"))
        db.commit()

        scanner._prune_slicer_files(db)

        assert db.query(STLFile).count() == 1

    def test_full_scan_order_lets_phantom_prune_remove_emptied_model(self, db):
        """A model whose only file was a slicer project: after the slicer prune
        it has zero STL rows, so the phantom prune (which runs after it in
        scan_all_roots) deletes the model in the same pass."""
        creator = make_creator(db, "Creator")
        real = Model(name="real", folder_path="/x/real", creator_id=creator.id)
        ghost = Model(name="ghost", folder_path="/x/ghost", creator_id=creator.id)
        db.add_all([real, ghost])
        db.flush()
        db.add(STLFile(model_id=real.id, path="/x/real/a.stl", filename="a.stl"))
        db.add(STLFile(model_id=ghost.id, path="/x/ghost/a.lys", filename="a.lys"))
        db.commit()

        scanner._prune_slicer_files(db)
        scanner._prune_phantoms(db)

        names = {m.name for m in db.query(Model).all()}
        assert names == {"real"}


# ---------------------------------------------------------------------------
# Scan completion summary + prune return counts (#223)
# ---------------------------------------------------------------------------

class TestScanCompletionSummary:
    def test_prune_phantoms_returns_count(self, db):
        from tests.conftest import make_model, make_stl_file
        creator = make_creator(db, "Creator")
        # Two real models (with STL rows) keep us under the 50% safety cap so the
        # single phantom is actually pruned and counted.
        for i in range(2):
            m = make_model(db, creator, name=f"real{i}")
            make_stl_file(db, m, filename=f"real{i}.stl", path=f"/tmp/real{i}.stl")
        make_model(db, creator, name="phantom")  # no STL files
        db.commit()

        assert scanner._prune_phantoms(db) == 1

    def test_prune_returns_zero_when_nothing_removed(self, db):
        from tests.conftest import make_model, make_stl_file
        creator = make_creator(db, "Creator")
        m = make_model(db, creator, name="real")
        make_stl_file(db, m)
        db.commit()

        assert scanner._prune_phantoms(db) == 0

    def _run_with_stubs(self, db, tmp_path, monkeypatch, *, models, files, removed):
        """Run scan_all_roots with the root walk and prunes stubbed out, so we can
        assert the completion-summary message without touching the real DB engine
        the worker threads would otherwise use."""
        from app.models import ScanRoot
        db.add(ScanRoot(path=str(tmp_path), enabled=True))
        db.commit()

        def fake_scan_root(root, _db):
            # Counters live on the active job handle now; _bump adds to the
            # zero-initialised progress the scan set at start.
            scanner._bump(models_found=models, files_found=files)
            return set()

        monkeypatch.setattr(scanner, "_scan_root", fake_scan_root)
        monkeypatch.setattr(scanner, "_prune_stale_models", lambda *a, **k: removed)
        monkeypatch.setattr(scanner, "_prune_stale_paths", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "_prune_slicer_files", lambda *a, **k: None)
        monkeypatch.setattr(scanner, "_prune_phantoms", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "prune_empty_creators", lambda *a, **k: None)

        scanner.scan_all_roots(db)
        return scanner.get_status()

    def test_summary_includes_removed_count(self, db, tmp_path, monkeypatch):
        status = self._run_with_stubs(db, tmp_path, monkeypatch, models=5, files=12, removed=3)
        assert status["message"] == "done — 5 models, 12 files, 3 removed"
        assert status["running"] is False

    def test_summary_omits_removed_when_zero(self, db, tmp_path, monkeypatch):
        status = self._run_with_stubs(db, tmp_path, monkeypatch, models=4, files=9, removed=0)
        assert status["message"] == "done — 4 models, 9 files"


# ---------------------------------------------------------------------------
# Folder-driven grouping (opt-in "Group variants by character")
# ---------------------------------------------------------------------------

class TestGroupByCharacterFolder:
    def test_everything_under_a_char_folder_is_one_group(self, db, tmp_path):
        """With the option on, all models under a character folder share that
        folder's name as their character — even distinctly-named siblings the
        heuristic would otherwise split into separate groups."""
        creator_dir = tmp_path / "Abe3D"
        _stl(creator_dir / "Goblin King" / "Goblin King 32mm")
        _stl(creator_dir / "Goblin King" / "Throne Diorama")          # distinct name
        _stl(creator_dir / "Goblin King" / "Pre-Supported" / "STL")   # nested
        creator = make_creator(db, "Abe3D")

        _walk(db, creator, creator_dir, group_by_character=True)

        models = _models(db, creator)
        assert {m.character for m in models} == {"Goblin King"}  # one group for the subtree
        assert len(models) >= 2

    def test_distinct_char_folders_are_separate_groups(self, db, tmp_path):
        creator_dir = tmp_path / "Abe3D"
        _stl(creator_dir / "Goblin King" / "Goblin King 32mm")
        _stl(creator_dir / "Dragon" / "Dragon 75mm")
        creator = make_creator(db, "Abe3D")

        _walk(db, creator, creator_dir, group_by_character=True)

        models = _models(db, creator)
        assert {m.character for m in models} == {"Goblin King", "Dragon"}
        for m in models:
            top = Path(m.folder_path).relative_to(creator_dir).parts[0]
            assert m.character == top  # character == the first folder below the creator

    def test_off_by_default_uses_heuristic(self, db, tmp_path):
        """Same tree, option off: two distinctly-named children do NOT collapse
        onto a single shared character (the heuristic keeps them apart)."""
        creator_dir = tmp_path / "Abe3D"
        _stl(creator_dir / "Goblin King" / "Goblin King 32mm")
        _stl(creator_dir / "Goblin King" / "Throne Diorama")
        creator = make_creator(db, "Abe3D")

        _walk(db, creator, creator_dir, group_by_character=False)

        chars = {m.character for m in _models(db, creator)}
        assert chars != {"Goblin King"}                 # not force-grouped


# ---------------------------------------------------------------------------
# Clean display name + structured parsed_attributes (#608)
# ---------------------------------------------------------------------------

class TestCleanNameAndAttributes:
    def _model_at(self, db, creator, leaf: Path) -> Model:
        return next(m for m in _models(db, creator) if Path(m.folder_path) == leaf)

    def test_new_model_gets_clean_display_name(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        leaf = creator_dir / "Ada Wong 1-6 Unsupported"
        _stl(leaf)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert self._model_at(db, creator, leaf).name == "Ada Wong"

    def test_parsed_attributes_populated(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        leaf = creator_dir / "Ada Wong 1-6 Unsupported Hollow Chitubox v2"
        _stl(leaf)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert self._model_at(db, creator, leaf).parsed_attributes == {
            "support_status": "unsupported",
            "cut_status": "hollow",
            "slicer": "chitubox",
            "version": "v2",
        }

    def test_structural_leaf_named_after_product(self, db, tmp_path):
        # A structural leaf ("75mm Unsupported") under a product is named after the
        # product (its character), not the structural folder name (#641).
        creator_dir = tmp_path / "Creator"
        leaf = creator_dir / "Goblin" / "75mm Unsupported"
        _stl(leaf)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert self._model_at(db, creator, leaf).name == "Goblin"

    def test_stored_name_is_rederived_on_rescan(self, db, tmp_path):
        # STUDIO-290: was test_user_rename_not_clobbered_on_rescan, which asserted
        # the opposite. Model.name is scanner-owned — ModelUpdate exposes no `name`
        # field, so no API or UI can rename a model and the "user rename" this
        # protected cannot occur. The guard's real effect was to freeze names that
        # an older parser derived, making them immune to later fixes.
        creator_dir = tmp_path / "Creator"
        leaf = creator_dir / "Ada Wong 1-6 Unsupported"
        _stl(leaf)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)
        m = self._model_at(db, creator, leaf)
        derived = m.name
        m.name = "My Custom Name"
        db.commit()

        _walk(db, creator, creator_dir)

        assert self._model_at(db, creator, leaf).name == derived

    def test_untouched_name_refreshes_on_rescan(self, db, tmp_path):
        # A model whose name still equals the scanner derivation should pick up
        # parser improvements — simulate a legacy row holding the raw folder name.
        creator_dir = tmp_path / "Creator"
        leaf = creator_dir / "Ada Wong 1-6 Unsupported"
        _stl(leaf)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)
        m = self._model_at(db, creator, leaf)
        m.name = leaf.name          # legacy raw-folder-name value
        db.commit()

        _walk(db, creator, creator_dir)

        assert self._model_at(db, creator, leaf).name == "Ada Wong"


# ---------------------------------------------------------------------------
# Structural leaf folders are named after their product, not "STL" (#641)
# ---------------------------------------------------------------------------

class TestStructuralLeafNaming:
    def _names(self, db, creator):
        return {m.name for m in _models(db, creator)}

    def test_stl_leaf_named_after_product_character(self, db, tmp_path):
        # {creator}/{product}/STL/*.stl — the model must be "Absolute Batman", not "STL".
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Absolute Batman" / "STL", name="b.stl")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        names = self._names(db, creator)
        assert "STL" not in names
        assert "Absolute Batman" in names

    def test_supported_unsupported_named_after_product(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Goblin" / "supported", name="g.stl")
        _stl(creator_dir / "Goblin" / "unsupported", name="g.stl")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        names = self._names(db, creator)
        assert names == {"Goblin"}  # both variants named after the product
        assert "supported" not in names and "unsupported" not in names

    def test_nonstructural_leaf_name_unchanged(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Dragon Bust", name="d.stl")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert "Dragon" in self._names(db, creator)  # display_name strips the "Bust" type token


class TestGenericNameQualification:
    """STUDIO-287: a leaf whose derived name is a bare parts word ("Bases") has no
    identity of its own and collides with every other such folder. It must be
    qualified by the owning release/product instead."""

    def _names(self, db, creator):
        return {m.name for m in _models(db, creator)}

    def test_generic_leaf_qualified_by_release_skipping_container(self, db, tmp_path):
        # {creator}/{release}/Models/NN - Bases {support} — "Models" is a pure
        # container and must be skipped, so the qualifier is the release. Without
        # the skip these would be named "Models", which is worse than "Bases".
        creator_dir = tmp_path / "Titan Forge Miniatures"
        _stl(creator_dir / "52 - OCTOBER 2024 REANIMATION" / "Models" / "05 - Bases Supported", name="b.stl")
        _stl(creator_dir / "52 - OCTOBER 2024 REANIMATION" / "Models" / "05 - Bases Unsupported", name="b.stl")
        creator = make_creator(db, "Titan Forge Miniatures")

        _walk(db, creator, creator_dir)

        names = self._names(db, creator)
        assert names == {"October 2024 Reanimation Bases"}
        assert "Bases" not in names
        assert "Models" not in names

    def test_generic_leaf_qualified_by_structural_looking_product(self, db, tmp_path):
        # {creator}/RPG Bases/RPG Bases {support} — "RPG Bases" is a genuine
        # product even though every token is a parts/type word. The qualifier
        # comes from the RAW folder name, and must not double up into
        # "RPG Bases Bases".
        creator_dir = tmp_path / "Titan Forge Miniatures"
        _stl(creator_dir / "RPG Bases" / "RPG Bases Supported", name="b.stl")
        _stl(creator_dir / "RPG Bases" / "RPG Bases Unsupported", name="b.stl")
        creator = make_creator(db, "Titan Forge Miniatures")

        _walk(db, creator, creator_dir)

        names = self._names(db, creator)
        assert names == {"RPG Bases"}
        assert "Bases" not in names
        assert "RPG Bases Bases" not in names

    def test_distinct_releases_do_not_collide(self, db, tmp_path):
        # The actual defect: two unrelated releases' base folders both derived to
        # "Bases" and shared one variant group.
        creator_dir = tmp_path / "Titan Forge Miniatures"
        _stl(creator_dir / "RPG Bases" / "RPG Bases Supported", name="b.stl")
        _stl(creator_dir / "59 - October 24 - Orc and Carnival 2 Bases" / "03 - Bases", name="b.stl")
        creator = make_creator(db, "Titan Forge Miniatures")

        _walk(db, creator, creator_dir)

        names = self._names(db, creator)
        assert len(names) == 2, f"releases collided: {names}"
        assert "RPG Bases" in names
        assert "October 24 Orc And Carnival 2 Bases" in names

    def test_sibling_release_name_does_not_bleed(self, db, tmp_path):
        # STUDIO-289: the walk `character` survives across sibling subtrees, so a
        # structural leaf under one release could be named after a DIFFERENT
        # release walked earlier. The nearest owning ancestor must win over the
        # carried character. Without the fix "RPG Bases Supported" is named
        # "October Orc And Carnival Bases".
        creator_dir = tmp_path / "Titan Forge Miniatures"
        _stl(creator_dir / "59 - October 24 - Orc and Carnival 2 Bases" / "03 - Bases", name="b.stl")
        _stl(creator_dir / "RPG Bases" / "RPG Bases Supported", name="b.stl")
        creator = make_creator(db, "Titan Forge Miniatures")

        _walk(db, creator, creator_dir)

        by_path = {_rel(m, creator_dir): m.name for m in _models(db, creator)}
        rpg = next(v for k, v in by_path.items() if k.startswith("RPG Bases"))
        assert rpg == "RPG Bases", f"sibling release bled in: {rpg!r}"
        assert "October" not in rpg

    def test_variant_cut_ancestor_does_not_outrank_the_figure(self, db, tmp_path):
        # STUDIO-291: regression from STUDIO-287's ancestor-over-character change.
        # "Alternative_Cut" is a variant folder, not a product — before the fix a
        # structural leaf beneath it was named "Alternative" instead of the figure,
        # while its sibling one level shallower was named correctly.
        creator_dir = tmp_path / "Tanuki Figures"
        _stl(creator_dir / "Gohan_SSJ2_TanukiFigures" / "Supported" / "Alternative_Cut" / "STL", name="g.stl")
        _stl(creator_dir / "Gohan_SSJ2_TanukiFigures" / "No_Supported" / "Alternative_Cut", name="g.stl")
        creator = make_creator(db, "Tanuki Figures")

        _walk(db, creator, creator_dir)

        names = self._names(db, creator)
        assert names == {"Gohan SSJ2"}, names
        assert "Alternative" not in names

    def test_no_cuts_folder_resolves_to_the_figure(self, db, tmp_path):
        # The uncut member of the Full_cutted/Semi_cutted family (STUDIO-288) was
        # never listed, so "No_cuts" read as a product.
        creator_dir = tmp_path / "PolyMind Studios"
        _stl(creator_dir / "Cloud" / "No_cuts", name="c.stl")
        _stl(creator_dir / "Kratos" / "No_Cuts", name="k.stl")
        creator = make_creator(db, "PolyMind Studios")

        _walk(db, creator, creator_dir)

        names = self._names(db, creator)
        assert names == {"Cloud", "Kratos"}, names

    def test_identifying_leaf_name_untouched(self, db, tmp_path):
        # Regression guard: a correctly derived name never enters the qualifier
        # branch, so it keeps its bare product name.
        creator_dir = tmp_path / "Titan Forge Miniatures"
        _stl(creator_dir / "52 - OCTOBER 2024 REANIMATION" / "Models" / "01 - Gridrunner supported", name="g.stl")
        _stl(creator_dir / "52 - OCTOBER 2024 REANIMATION" / "Models" / "02 - Grim Realms Supported", name="g.stl")
        creator = make_creator(db, "Titan Forge Miniatures")

        _walk(db, creator, creator_dir)

        names = self._names(db, creator)
        assert "Gridrunner" in names
        assert "Grim Realms" in names
        assert not any(n.startswith("October 2024") for n in names)


class TestCaseInsensitiveIdentity:
    """STUDIO-78: a case-only path change (Windows rename of an ancestor folder)
    must reuse the existing model in place, not orphan+recreate it — which would
    wipe user metadata and empty manual variant groups.

    _normpath is monkeypatched to a case-folding normalizer so the scenario is
    deterministic on case-sensitive CI filesystems too; the real os.rename below
    gives the walk a genuinely different-cased path to index."""

    def _case_fold(self, monkeypatch):
        monkeypatch.setattr(scanner, "_normpath", lambda p: os.path.normpath(p).lower())

    def test_case_change_reuses_model_and_preserves_metadata(self, db, tmp_path, monkeypatch):
        self._case_fold(monkeypatch)
        creator = make_creator(db, "Creator")
        leaf = tmp_path / "polymind studios" / "Auron"
        _stl(leaf, name="auron.stl")

        _walk(db, creator, tmp_path / "polymind studios")
        models = _models(db, creator)
        assert len(models) == 1
        model = models[0]
        original_id = model.id

        # User-owned metadata + a manual variant group.
        group = VariantGroup(creator_id=creator.id, label="Auron", source="manual")
        db.add(group)
        db.flush()
        model.variant_group_id = group.id
        model.tags = ["favorite"]
        model.notes = "hand-primed"
        model.nsfw = True
        db.commit()

        # Rename the ancestor folder case-only (same folder to a case-insensitive OS).
        os.rename(tmp_path / "polymind studios", tmp_path / "PolyMind Studios")

        _walk(db, creator, tmp_path / "PolyMind Studios")

        models = _models(db, creator)
        assert len(models) == 1, "case change must not create a duplicate model"
        reused = models[0]
        assert reused.id == original_id, "same row reused in place"
        assert reused.folder_path == str(tmp_path / "PolyMind Studios" / "Auron")
        assert reused.variant_group_id == group.id, "manual group membership preserved"
        assert reused.tags == ["favorite"]
        assert reused.notes == "hand-primed"
        assert reused.nsfw is True

    def test_case_change_recases_stl_paths_without_duplicates(self, db, tmp_path, monkeypatch):
        self._case_fold(monkeypatch)
        creator = make_creator(db, "Creator")
        leaf = tmp_path / "creator root" / "Barbatos"
        _stl(leaf, name="barbatos.stl")

        _walk(db, creator, tmp_path / "creator root")
        model = _models(db, creator)[0]
        stls = db.query(STLFile).filter(STLFile.model_id == model.id).all()
        assert len(stls) == 1

        os.rename(tmp_path / "creator root", tmp_path / "Creator Root")
        _walk(db, creator, tmp_path / "Creator Root")

        stls = db.query(STLFile).filter(STLFile.model_id == model.id).all()
        assert len(stls) == 1, "STL rows re-cased in place, not duplicated"
        assert stls[0].path == str(tmp_path / "Creator Root" / "Barbatos" / "barbatos.stl")


# ---------------------------------------------------------------------------
# Busy-library launch gate (STUDIO-83)
# ---------------------------------------------------------------------------

def test_creator_rescan_refreshes_automatic_groups(db, tmp_path, monkeypatch):
    """Creator-level rescans run the same post-walk grouping pass as full scans."""
    creator = make_creator(db, "Creator")
    creator_id = creator.id
    db.commit()
    Session = sessionmaker(bind=db.get_bind())
    calls: list[int] = []

    monkeypatch.setattr(scanner, "SessionLocal", Session)
    monkeypatch.setattr(scanner, "_load_pack_overrides", lambda _db: None)
    monkeypatch.setattr(scanner, "_load_scan_rules", lambda _db: None)
    monkeypatch.setattr(scanner, "_creator_dirs_for", lambda _creator, _db: [(tmp_path, [], False)])
    monkeypatch.setattr(scanner, "_walk_for_models", lambda *args, **kwargs: None)
    monkeypatch.setattr(scanner, "_prune_phantoms", lambda _db, creator_id=None: 0)
    monkeypatch.setattr(scanner.grouping, "regroup_creator", lambda _db, cid: calls.append(cid))
    monkeypatch.setattr(scanner.grouping, "prune_empty_groups", lambda _db: 0)
    monkeypatch.setattr(scanner.write_lock, "release_scan", lambda: None)

    job = JobHandle(key="creator-rescan-test", _lock=threading.Lock(), state=JobState.RUNNING)
    scanner._creator_scan(job, creator_id)

    assert calls == [creator_id]
    assert job.payload()["state"] == "done"


def test_start_scans_return_false_when_write_lock_held():
    """start_full_scan / start_creator_scan report False (not a silent no-op)
    when the write lock is already held, so the router can answer 409 instead of
    a misleading 200 (STUDIO-83)."""
    from app.services import write_lock

    assert write_lock.try_acquire_for_scan() is True
    try:
        assert scanner.start_full_scan() is False
        assert scanner.start_creator_scan(1) is False
    finally:
        write_lock.release_scan()


class TestStructuralNameHealing:
    """STUDIO-282/290: a model's stored name is scanner-owned and is re-derived on
    every rescan, so parser improvements always reach existing rows."""

    def _one_leaf_model(self, db, creator, creator_dir):
        # Two structural-variant leaves under one character → each is its own
        # model, named after the character via the #641 leaf-naming.
        _stl(creator_dir / "Auron" / "STL")
        _stl(creator_dir / "Auron" / "Supported STL")
        _walk(db, creator, creator_dir)
        models = _models(db, creator)
        assert len(models) == 2
        assert all(m.name == "Auron" for m in models), [m.name for m in models]
        return models

    def test_stale_structural_name_is_refreshed(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        creator = make_creator(db, "Creator")
        models = self._one_leaf_model(db, creator, creator_dir)
        # Simulate stale pre-fix data: the folder was once "LYS" and the name stuck
        # across a rename, so it no longer matches the folder or derived name.
        stale = models[0]
        stale.name = "LYS"
        db.flush()

        _walk(db, creator, creator_dir)
        db.refresh(stale)

        assert stale.name == "Auron"
        assert not name_parser.is_structural_folder(stale.name)

    def test_stale_derived_fragment_is_refreshed(self, db, tmp_path):
        # STUDIO-290: the defect the old predicate caused. A name an OLDER parser
        # derived ("Semi" from "Semi_cutted") matches neither the folder name nor
        # the current derivation, and is not itself structural — so it used to be
        # mistaken for a user rename and pinned forever, silently immune to every
        # later fix. STUDIO-288 shipped correct and changed nothing on rescan.
        creator_dir = tmp_path / "Creator"
        creator = make_creator(db, "Creator")
        models = self._one_leaf_model(db, creator, creator_dir)
        stale = models[0]
        stale.name = "Semi"
        db.flush()

        _walk(db, creator, creator_dir)
        db.refresh(stale)

        assert stale.name == "Auron"

    def test_arbitrary_stale_name_is_refreshed(self, db, tmp_path):
        # Model.name is scanner-owned end to end — set at creation and in the
        # healing branch, nowhere else. ModelUpdate exposes no `name` field, so no
        # API or UI can rename a model; any stored name is therefore some past run
        # of this derivation and is safe to refresh unconditionally.
        #
        # This replaces the old test_user_edited_name_is_preserved, which pinned
        # the opposite behavior. That test encoded a guard against a user rename
        # that cannot occur, and the guard is what froze stale names. If a rename
        # feature is added, record the intent explicitly and reinstate a test for
        # it — do NOT restore shape-based inference.
        creator_dir = tmp_path / "Creator"
        creator = make_creator(db, "Creator")
        models = self._one_leaf_model(db, creator, creator_dir)
        edited = models[0]
        edited.name = "Some Entirely Unrelated Name"
        db.flush()

        _walk(db, creator, creator_dir)
        db.refresh(edited)

        assert edited.name == "Auron"

    def test_correct_name_is_stable_across_rescans(self, db, tmp_path):
        # Unconditional refresh must be idempotent — a correctly derived name is
        # rewritten to the same value, not churned.
        creator_dir = tmp_path / "Creator"
        creator = make_creator(db, "Creator")
        models = self._one_leaf_model(db, creator, creator_dir)
        target = models[0]

        _walk(db, creator, creator_dir)
        _walk(db, creator, creator_dir)
        db.refresh(target)

        assert target.name == "Auron"

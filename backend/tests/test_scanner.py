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

import pytest

from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from app.models import Creator, Model, STLFile, VariantGroup
from app.services import scanner, name_parser
from app.services.job_runner import JobHandle, JobState
from app.services.scan_rules import IgnoreMatcher
from app.utils import utcnow
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


def _walk(
    db,
    creator: Creator,
    creator_dir: Path,
    group_by_character: bool = False,
    rules: scanner.ScanRules | None = None,
) -> None:
    """Run the real walk. `rules` defaults to an empty rule set — no pack
    overrides, no ignore patterns — which is what most tests want; pass an
    explicit ScanRules to exercise either (STUDIO-231)."""
    scanner._walk_for_models(
        folder=creator_dir, creator=creator, db=db,
        creator_boundary=creator_dir, character=None,
        stl_cache={}, last_scanned=None,
        rules=rules if rules is not None else scanner.ScanRules(),
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

    def test_scan_does_not_sweep_sibling_products_no_stl_images_into_gallery(
        self, db, tmp_path,
    ):
        """STUDIO-377: a sibling product folder that (at scan time) has only
        marketing images and no STL files yet must not have those images swept
        into every OTHER model's gallery. This is exactly what happened with CA
        3D Studios' "Darth Vader Samurai" and "Regina" — both had images
        uploaded before their STLs were added, and a creator scan run during
        that window pushed their whole galleries into unrelated sibling models,
        because the old boundary reached all the way up to the creator root."""
        creator_dir = tmp_path / "Creator"
        _img(creator_dir / "ImageOnlyProduct", "cover.jpg")  # no STL yet
        model_dir = creator_dir / "RealProduct"
        _stl(model_dir)
        _img(model_dir, "own.jpg")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        model = _models(db, creator)[0]
        assert model.name == "RealProduct" or "RealProduct" in model.folder_path
        assert model.image_paths == [str(model_dir / "own.jpg")]

    def test_scan_does_not_sweep_loose_creator_root_image_into_gallery(
        self, db, tmp_path,
    ):
        """STUDIO-377: a stray image dropped directly in the creator's own
        folder (not inside any product folder) must not bleed into every
        model's gallery under that creator — the real-world case was a loose
        "RPG Pack - Names.jpg" reference image sitting at a creator's root,
        which every model under that creator picked up on every scan."""
        creator_dir = tmp_path / "Creator"
        (creator_dir).mkdir(parents=True, exist_ok=True)
        (creator_dir / "loose_reference.jpg").write_bytes(b"\x89PNG\r\n")
        model_dir = creator_dir / "Knight"
        _stl(model_dir)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        model = _models(db, creator)[0]
        assert model.image_paths == []

    def test_scan_still_shares_images_within_the_same_product_tree(self, db, tmp_path):
        """The boundary tightening (STUDIO-377) must not break the legitimate
        case it was designed to support: a product-level images folder shared
        by a model nested one level deeper under the SAME product — e.g. CA 3D
        Studios' "2B/2B - Images" shared by "2B/2B - 1_4" and "2B/2B - 1_6"."""
        creator_dir = tmp_path / "Creator"
        product_dir = creator_dir / "Product"
        _img(product_dir / "Images", "shared.jpg")
        model_dir = product_dir / "ModelFolder" / "STL"
        _stl(model_dir)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        model = _models(db, creator)[0]
        assert model.image_paths == [str(product_dir / "Images" / "shared.jpg")]

    def test_images_cache_avoids_rewalking_the_shared_boundary_per_sibling(
        self, db, tmp_path, monkeypatch,
    ):
        """STUDIO-299: sibling variant models sharing a character boundary each
        walk from their own leaf up to that boundary — without a shared
        images_cache, the boundary folder's own image subdir gets re-walked
        once per sibling instead of once per scan."""
        creator_dir = tmp_path / "Creator"
        character_dir = creator_dir / "Character"
        _img(character_dir / "Renders", "shared.jpg")
        _stl(character_dir / "VariantA")
        _stl(character_dir / "VariantB")
        creator = make_creator(db, "Creator")

        calls: list[Path] = []
        real = scanner._image_files_recursive

        def _counting(folder):
            calls.append(folder)
            return real(folder)

        monkeypatch.setattr(scanner, "_image_files_recursive", _counting)

        scanner._walk_for_models(
            folder=creator_dir, creator=creator, db=db,
            creator_boundary=creator_dir, character=None,
            stl_cache={}, last_scanned=None, rules=scanner.ScanRules(),
            images_cache={},
        )

        models = {_rel(m, creator_dir): m for m in _models(db, creator)}
        shared = str(character_dir / "Renders" / "shared.jpg")
        assert models[str(Path("Character") / "VariantA")].image_paths == [shared]
        assert models[str(Path("Character") / "VariantB")].image_paths == [shared]

        renders_calls = [c for c in calls if c == character_dir / "Renders"]
        assert len(renders_calls) == 1, (
            f"expected the shared boundary's image dir to be walked once, got {len(renders_calls)}"
        )


class TestThreeMfOtherFiles:
    """.3mf is a slicer project/bundle format, not a single printable part —
    many creators do ship real geometry that way, so it must still count as
    "this folder has printable content" for leaf detection (a lone .3mf
    folder must still become a model), but it's filed as other_files rather
    than getting its own STLFile row."""

    def test_lone_3mf_folder_becomes_a_model_with_no_stl_rows(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Combo Print"
        model_dir.mkdir(parents=True)
        (model_dir / "AllParts_Colored.3mf").write_bytes(b"fake 3mf")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 1
        model = models[0]
        assert model.other_files == [str(model_dir / "AllParts_Colored.3mf")]
        assert db.query(STLFile).filter(STLFile.model_id == model.id).count() == 0

    def test_3mf_alongside_stl_files_splits_correctly(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Knight"
        _stl(model_dir, "head.stl")
        _stl(model_dir, "body.stl")
        (model_dir / "project.3mf").write_bytes(b"fake 3mf")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        model = _models(db, creator)[0]
        assert model.other_files == [str(model_dir / "project.3mf")]
        stl_paths = {
            f.path for f in db.query(STLFile).filter(STLFile.model_id == model.id)
        }
        assert stl_paths == {str(model_dir / "head.stl"), str(model_dir / "body.stl")}

    def test_rescan_does_not_duplicate_3mf_in_other_files(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Combo Print"
        model_dir.mkdir(parents=True)
        (model_dir / "AllParts_Colored.3mf").write_bytes(b"fake 3mf")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)
        _walk(db, creator, creator_dir)

        model = _models(db, creator)[0]
        assert model.other_files == [str(model_dir / "AllParts_Colored.3mf")]

    def test_rescan_heals_a_3mf_indexed_before_this_behaviour_existed(self, db, tmp_path):
        """A .3mf indexed as an STLFile row by an older scan (before .3mf was
        routed to other_files) must not linger forever — _index_stl_files
        never revisits an already-known path, so without an explicit cleanup
        it would show up as both a tracked file AND an other_file after this
        change ships. A rescan must remove the stale row and fold the path
        into other_files instead."""
        from tests.conftest import make_stl_file

        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Combo Print"
        model_dir.mkdir(parents=True)
        threemf = model_dir / "AllParts_Colored.3mf"
        threemf.write_bytes(b"fake 3mf")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)
        model = _models(db, creator)[0]
        # Simulate the legacy state: pre-fix code indexed the .3mf as a
        # tracked STLFile row instead of other_files.
        make_stl_file(db, model, filename=threemf.name, path=str(threemf))
        model.other_files = []
        db.commit()

        _walk(db, creator, creator_dir)
        db.refresh(model)

        assert model.other_files == [str(threemf)]
        assert db.query(STLFile).filter(STLFile.model_id == model.id).count() == 0


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

        rules = scanner.ScanRules(ignore=IgnoreMatcher(("wip",)))
        _walk(db, creator, creator_dir, rules=rules)

        paths = {_rel(m, creator_dir) for m in _models(db, creator)}
        assert any("Knight" in p for p in paths)
        assert not any("WIP" in p for p in paths)

    def test_creator_root_is_never_ignored(self, db, tmp_path, monkeypatch):
        """A pattern matching the creator boundary itself must not drop the whole
        creator — ignore is for sub-folders, not entire creators."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Knight" / "STL")
        creator = make_creator(db, "Creator")

        rules = scanner.ScanRules(ignore=IgnoreMatcher(("creator",)))
        _walk(db, creator, creator_dir, rules=rules)

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

        rules = scanner.ScanRules(ignore=IgnoreMatcher(("wip",)))
        removed = scanner._prune_ignored(db, [str(tmp_path)], rules.ignore)

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

        rules = scanner.ScanRules(ignore=IgnoreMatcher(("wip*",)))
        removed = scanner._prune_ignored(db, [str(tmp_path)], rules.ignore)

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

        rules = scanner.ScanRules(ignore=IgnoreMatcher(("wip",)))
        removed = scanner._prune_ignored(db, [str(tmp_path)], rules.ignore)

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

        rules = scanner.ScanRules(
            parser_rules=name_parser.ParserRules(
                tag_rules=((re.compile(r"\bAztec\b", re.I), "civ"),),
            )
        )
        _walk(db, creator, creator_dir, rules=rules)

        m = next(m for m in _models(db, creator) if "Aztec" in m.folder_path)
        assert "civ" in (m.auto_tags or [])

    def test_no_rules_leaves_auto_tags_unchanged(self, db, tmp_path):
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

        _walk(db, creator, creator_dir)

        assert any("Bust" in _rel(m, creator_dir) for m in _models(db, creator))

    def test_user_parts_folder_folds_into_parent_product(self, db, tmp_path):
        """With 'bust' configured as a parts name, the same layout collapses to a
        single 'Golem' model — the parts sub-folder is no longer split out."""
        creator_dir = tmp_path / "B"
        _stl(creator_dir / "Golem")
        _stl(creator_dir / "Golem" / "Bust")
        creator = make_creator(db, "B")

        rules = scanner.ScanRules(
            parser_rules=name_parser.ParserRules(parts_names=frozenset({"bust"}))
        )
        _walk(db, creator, creator_dir, rules=rules)

        paths = {_rel(m, creator_dir) for m in _models(db, creator)}
        assert paths == {"Golem"}

    def test_is_structural_folder_honors_user_names(self):
        rules = name_parser.ParserRules(parts_names=frozenset({"sprues"}))
        assert name_parser.is_structural_folder("Sprues", rules) is True
        # omitted → built-ins only, no longer structural
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


class TestPresupportedPackBoundary:
    """STUDIO-371: a pre-supported pack layout puts every STL one level down in
    named format subfolders ("STL", "Supported STL") and leaves the product's
    own folder with no direct STLs and no name signal — the real
    'One Page Rules / Alien Hives / AH - Carnivorex' layout from the ticket."""

    def _product(self, creator_dir: Path, name: str) -> Path:
        product = creator_dir / "Alien Hives" / name
        _stl(product / "STL", name="body.stl")
        _stl(product / "Supported STL", name="body_supported.stl")
        (product / "Supported LYS").mkdir(parents=True, exist_ok=True)
        (product / "Supported LYS" / "body.lys").write_bytes(b"lychee")
        return product

    def test_product_with_no_direct_stls_resolves_to_one_model(self, db, tmp_path):
        creator_dir = tmp_path / "OPR"
        product = self._product(creator_dir, "AH - Carnivorex")
        creator = make_creator(db, "OPR")

        _walk(db, creator, creator_dir)

        by_path = {Path(m.folder_path) for m in _models(db, creator)}
        assert by_path == {product}
        model = _models(db, creator)[0]
        assert {f.filename for f in model.stl_files} == {"body.stl", "body_supported.stl"}

    def test_sibling_part_subfolders_do_not_become_phantom_models(self, db, tmp_path):
        creator_dir = tmp_path / "OPR"
        product = self._product(creator_dir, "AH - Carnivorex")
        creator = make_creator(db, "OPR")

        _walk(db, creator, creator_dir)

        by_path = {Path(m.folder_path) for m in _models(db, creator)}
        assert product / "STL" not in by_path
        assert product / "Supported STL" not in by_path
        assert product / "Supported LYS" not in by_path

    def test_real_product_sibling_still_splits_off(self, db, tmp_path):
        """Bases is a genuine sub-product (its own scale signal) sitting next
        to the format subfolders — it must still resolve as its own model,
        not get folded into the parent or dropped."""
        creator_dir = tmp_path / "OPR"
        product = self._product(creator_dir, "AH - Carnivorex")
        bases = product / "Bases 120mm (Oval+Rectangle)"
        _stl(bases, name="oval.stl")
        creator = make_creator(db, "OPR")

        _walk(db, creator, creator_dir)

        by_path = {Path(m.folder_path) for m in _models(db, creator)}
        assert by_path == {product, bases}

    def test_grouping_folder_without_signal_still_resolves_one_model_per_character(
        self, db, tmp_path,
    ):
        """The discriminating case: an intermediate folder with no name signal
        and no direct STLs (like 'Alien Hives') must NOT be swept up into this
        promotion just because it recurses into folders holding STLs — only a
        folder whose STL-bearing child is *itself* a recognised parts folder
        qualifies. A plain character-name child must keep resolving on its own."""
        creator_dir = tmp_path / "OPR"
        carnivorex = self._product(creator_dir, "AH - Carnivorex")
        ravenous = self._product(creator_dir, "AH - Ravenous")
        creator = make_creator(db, "OPR")

        _walk(db, creator, creator_dir)

        by_path = {Path(m.folder_path) for m in _models(db, creator)}
        assert by_path == {carnivorex, ravenous}
        assert (creator_dir / "Alien Hives") not in by_path

    def test_rescan_converges_without_duplicating(self, db, tmp_path):
        creator_dir = tmp_path / "OPR"
        product = self._product(creator_dir, "AH - Carnivorex")
        creator = make_creator(db, "OPR")

        _walk(db, creator, creator_dir)
        _walk(db, creator, creator_dir)

        by_path = [Path(m.folder_path) for m in _models(db, creator)]
        assert by_path == [product]


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
            stl_cache={}, last_scanned=None, rules=scanner.ScanRules(),
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
            stl_cache={}, last_scanned=None, rules=scanner.ScanRules(),
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

    def test_bare_img_gallery_folder_does_not_vote_as_a_product(self, db, tmp_path):
        """STUDIO-432 cause 2: `Images` has always been structural vocabulary but
        `img` was not, so a gallery folder counted as a real voter in the
        sibling-identity vote.

        The three real children here are 2-vs-1, which IS a strict majority of
        three. `img` makes it four voters, `2 * 2 > 4` is false, and the vote
        falls through to `leaf` where every child keeps its own key — the
        character folder's own perfectly good name goes unused and `Left Arm fix`
        becomes a product of one. Measured on the 3503-model library: 27 bare
        `img` folders, not one holding a mesh; eight character folders change
        vote strategy and seven of those change a stored character.

        Deliberately isolates the img token — there is no creator tag anywhere in
        this tree, so the assertion cannot start passing for the wrong reason if
        STUDIO-432's *other* cause (a mid-string creator token surviving
        `character_key`) is fixed later. Reverting the vocabulary entry must fail
        this test.

        Scope note: this fix reaches a folder named exactly `img`, NOT one named
        `img <something>` — `is_structural_folder` requires every token to be
        structural, which is also why `Images Barbarella` has always voted. That
        larger shape is its own ticket; see TestIsStructuralFolder for the pin.

        The STLs sit one level below each variant folder for the same reason as
        `test_lone_odd_sibling_does_not_hijack_the_character` — with them directly
        inside, the character folder collapses to one model and no vote runs.
        """
        creator_dir = tmp_path / "Abe3d"
        char = creator_dir / "Samus Aran"
        for variant in ("1_4 Samus Aran", "1_6 Samus Aran", "Left Arm fix"):
            _stl(char / variant / "STL")
        _img(char / "img")          # gallery only, no mesh — the shape on disk
        creator = make_creator(db, "Abe3d")

        _walk(db, creator, creator_dir)

        # Pin each folder's exact value rather than the set. STUDIO-428's lesson:
        # a set-shaped assertion ("one distinct character") stays true under a
        # mutation that merely relabels a member, so it kills nothing.
        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        assert chars == {
            str(Path("Samus Aran/1_4 Samus Aran")): "Samus Aran",
            str(Path("Samus Aran/1_6 Samus Aran")): "Samus Aran",
            str(Path("Samus Aran/Left Arm fix")): "Samus Aran",
        }, "the img gallery folder voted as a product and broke the majority"

    def test_lone_odd_sibling_does_not_hijack_the_character(self, db, tmp_path):
        """STUDIO-410: parts/structural children are skipped from the identity
        vote, so a character folder holding structural variants plus ONE
        oddly-named child leaves that child as the only voter. Its key must not
        become the character of its siblings — that overwrote the character
        folder's own perfectly good name, and welded two different characters
        into one group named after a variant folder.

        The STLs sit one level below each variant folder (the common
        pre-supported pack shape): with them directly inside, the whole
        character folder collapses to a single model and the vote never runs.
        """
        creator_dir = tmp_path / "Creator"
        for character in ("Goblin", "Orc"):
            for variant in ("Supported", "Unsupported", "Nude V2"):
                _stl(creator_dir / character / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        # The structural siblings keep the character folder's name…
        assert chars[str(Path("Goblin/Supported"))] == "Goblin"
        assert chars[str(Path("Goblin/Unsupported"))] == "Goblin"
        assert chars[str(Path("Orc/Supported"))] == "Orc"
        assert chars[str(Path("Orc/Unsupported"))] == "Orc"
        # …and STUDIO-412 lands the odd sibling in its own character's group
        # rather than in a singleton of its own, so the two characters can never
        # share one group and neither leaves a model behind.
        assert chars[str(Path("Goblin/Nude V2"))] == "Goblin"
        assert chars[str(Path("Orc/Nude V2"))] == "Orc"

    def test_lone_sibling_extending_the_parent_name_still_labels_the_group(self, db, tmp_path):
        """The single-key branch must still win when the lone child's identity
        *extends* the parent's — "Crimson Wings" holding a "Crimson Wings APC"
        is one product carrying context, not a hijack, so every sibling shares
        the parent's label. Guards the carve-out that keeps STUDIO-410's fix
        from being simplified down to "only at the creator root"."""
        creator_dir = tmp_path / "Creator"
        char = creator_dir / "Crimson Wings"
        for variant in ("Supported", "Unsupported", "Crimson Wings APC"):
            _stl(char / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {m.character for m in _models(db, creator)}
        assert chars == {"Crimson Wings"}

    def test_lone_odd_sibling_rejoins_its_own_product(self, db, tmp_path):
        """STUDIO-412: STUDIO-410 stopped the odd child hijacking its siblings
        but left the child itself carrying its own folder name — a character of
        its own, therefore a singleton, therefore ungrouped. The one model in
        the tree whose identity was recoverable was the only one with no group.

        There is a single character folder here, so
        `_disambiguate_colliding_characters` has nothing to collide and never
        runs: the split is made by the walk, not by the disambiguator the ticket
        named. The structural siblings are what make this decidable — a folder
        whose other children inherit its identity is a product, not a container
        of products, so the odd one out is one more of its variants."""
        creator_dir = tmp_path / "Creator"
        for variant in ("Supported", "Unsupported", "Nude V2"):
            _stl(creator_dir / "Ada Wong" / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        assert chars == {
            str(Path("Ada Wong/Supported")): "Ada Wong",
            str(Path("Ada Wong/Unsupported")): "Ada Wong",
            str(Path("Ada Wong/Nude V2")): "Ada Wong",
        }

    def test_odd_sibling_rejoins_a_character_carried_through_a_structural_level(self, db, tmp_path):
        """The same rule reached through a folder that *carries* an identity
        rather than owning one: `Supported` is structural, so it holds Ada Wong's
        name on behalf of its ancestor, and the odd child beneath it belongs to
        Ada Wong just as much. This is the shape the fix's comment cites, and
        the likeliest one in a real library."""
        creator_dir = tmp_path / "Creator"
        supported = creator_dir / "Ada Wong" / "Supported"
        _stl(supported / "Nude V2")
        _stl(supported / "Lychee")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {m.character for m in _models(db, creator)}
        assert chars == {"Ada Wong"}

    def test_two_odd_siblings_keep_their_own_names(self, db, tmp_path):
        """The boundary on STUDIO-412, and the reason it is narrowed to a lone
        odd child. This layout is structurally identical to the case above — a
        folder with its own identity, a structural child inheriting it, and
        oddly-named children that do not — except there are TWO of them, and
        nothing in the names distinguishes two variants of one product from two
        products in a pack. Handing them the folder's name would weld two
        different characters into one group, which is the failure this epic
        exists to remove, so they keep their own."""
        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Pack"
        _stl(pack / "Supported" / "STL")
        for char in ("Electro", "Sandman"):
            _stl(pack / char / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        assert chars == {
            str(Path("Sinister Pack/Supported")): "Sinister Pack",
            str(Path("Sinister Pack/Electro")): "Electro",
            str(Path("Sinister Pack/Sandman")): "Sandman",
        }

    def test_lone_product_with_no_skipped_siblings_keeps_its_own_name(self, db, tmp_path):
        """The other half of STUDIO-412's narrowing, and it needs its own test:
        a mutant that drops the skipped-children requirement and hands every
        vetoed lone child its parent's name passed the entire suite, because
        nothing pinned this shape. With no structural sibling there is no
        evidence that the outer folder is a product rather than a pack holding
        one, so the child keeps the name it brought — the conservative reading,
        and the one STUDIO-410 settled on."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Sinister Pack" / "Electro" / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {m.character for m in _models(db, creator)}
        assert chars == {"Electro"}

    def test_lone_product_beside_a_structural_sibling_takes_the_folder_name(self, db, tmp_path):
        """The same narrowing seen from the other side, and the one shape whose
        behaviour STUDIO-412 changes outside the character-folder case it was
        filed for: a folder holding one structural child and one oddly-named
        child is one product however it is named, because the structural child's
        contents can only belong to that product. Both models therefore share
        the folder's name and group, where before they were two ungrouped
        singletons."""
        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Pack"
        _stl(pack / "Supported" / "STL")
        _stl(pack / "Electro" / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {m.character for m in _models(db, creator)}
        assert chars == {"Sinister Pack"}

    def test_case_variant_siblings_are_one_product(self, db, tmp_path):
        """STUDIO-413: the sibling vote compared product keys case-sensitively,
        so a creator who typed one folder in caps split their own character into
        three products. `product_key` has always folded case, which is why
        hierarchy grouping papered over this — with hierarchy off it is a real
        miss, and the stored characters disagree either way.

        Pins both halves of the fix, not just the fold: folding the vote alone
        would store "ADA WONG" here (the alphabetical winner of a three-way tie),
        so this also fails if the parent-casing rule goes. Shape-isolated in
        `test_the_folders_own_casing_wins_a_case_only_match`."""
        creator_dir = tmp_path / "Creator"
        for variant in ("Ada Wong Supported", "ADA WONG Unsupported", "ada wong Hollow"):
            _stl(creator_dir / "Ada Wong" / variant)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        # The parent folder's own casing names the product — it is the most
        # authoritative label available and never a machine-lowercased key.
        assert {m.character for m in _models(db, creator)} == {"Ada Wong"}

    def test_the_folders_own_casing_wins_a_case_only_match(self, db, tmp_path):
        """The half of STUDIO-413 that needs no folding at all to go wrong: a
        lone child already reaches the "common" strategy here, and the label
        guard requires the folder's key to be a *strictly shorter* prefix of the
        shared one. A case-only difference is the same length, so the guard
        cannot fire and every model under "Ada Wong" was stored as "ADA WONG"."""
        creator_dir = tmp_path / "Creator"
        for variant in ("Supported", "Unsupported", "ADA WONG"):
            _stl(creator_dir / "Ada Wong" / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert {m.character for m in _models(db, creator)} == {"Ada Wong"}

    def test_case_variant_siblings_at_the_creator_root_pick_one_casing(self, db, tmp_path):
        """At the creator root there is no parent name to borrow, so the vote
        falls back to the most frequent casing among the children, ties broken
        alphabetically — the same rule as `grouping_policy._most_common`
        (STUDIO-248). All three tie here, and ASCII sorts caps first, so the
        shouty one wins. Deliberate: reproducibility outranks prettiness, and
        the value is still a real folder's casing."""
        creator_dir = tmp_path / "Creator"
        for variant in ("Ada Wong Supported", "ADA WONG Unsupported", "ada wong Hollow"):
            _stl(creator_dir / variant)
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert {m.character for m in _models(db, creator)} == {"ADA WONG"}

    def test_case_only_siblings_beside_a_structural_folder_are_one_product(self, db, tmp_path):
        """The boundary shape, and the reason this is an extension rather than a
        new class: with the siblings identically cased this folder already flips
        to "common" and hands the structural child their character instead of
        the pack's name. Case-only siblings reached "leaf" instead and left all
        three ungrouped — strictly worse, for no reason a user could see."""
        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Pack"
        for variant in ("Supported", "ADA WONG Unsupported", "ada wong Hollow"):
            _stl(pack / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert {m.character for m in _models(db, creator)} == {"ADA WONG"}

    def test_type_worded_product_does_not_inherit_a_siblings_character(self, db, tmp_path):
        """STUDIO-414: a folder whose every token is a type keyword ("Chibi Hero",
        "Bust") reads as structural, so it is skipped from the identity vote — and
        then the "common" strategy hands it the winner's label anyway. A real
        product therefore landed in an unrelated character's variant group, which
        is the false merge STUDIO-410 exists to prevent, reached from the other
        side. At the creator root nothing above supplies an identity, so such a
        folder names itself."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Chibi Hero" / "Supported" / "STL")
        _stl(creator_dir / "Chibi Hero" / "Unsupported" / "STL")
        for variant in ("Supported", "Unsupported"):
            _stl(creator_dir / "Goblin" / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        assert chars[str(Path("Chibi Hero"))] == "Chibi Hero"
        assert chars[str(Path("Goblin/Supported"))] == "Goblin"
        assert chars[str(Path("Goblin/Unsupported"))] == "Goblin"

    def test_type_worded_product_keeps_its_own_models_together(self, db, tmp_path):
        """The multi-model form of the same bug. A type keyword also makes the
        folder a product boundary (scanner.py step 1), so its children with
        signals of their own become separate models — every one of which took the
        unrelated sibling's character, not just one."""
        creator_dir = tmp_path / "Creator"
        for variant in ("Bust", "Statue"):
            _stl(creator_dir / "Chibi Hero" / variant / "STL")
        for variant in ("Supported", "Unsupported"):
            _stl(creator_dir / "Goblin" / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        assert chars[str(Path("Chibi Hero/Bust"))] == "Chibi Hero"
        assert chars[str(Path("Chibi Hero/Statue"))] == "Chibi Hero"
        assert chars[str(Path("Goblin/Supported"))] == "Goblin"

    def test_type_worded_product_alone_still_gets_a_character(self, db, tmp_path):
        """With no sibling to inherit from, the same folder left its models with
        no character at all — nothing for the CHARACTER signal to group on, and
        no rescan reaches an existing library to fix it."""
        creator_dir = tmp_path / "Creator"
        for variant in ("Bust", "Statue"):
            _stl(creator_dir / "Chibi Hero" / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert {m.character for m in _models(db, creator)} == {"Chibi Hero"}

    def test_an_underscore_joined_type_worded_product_is_rescued_too(self, db, tmp_path):
        """Underscore is a word character, so the type patterns never fire on
        the raw name — but is_structural_folder splits on it and skips the
        folder anyway. Without normalising separators the fix would miss the
        most common real-library spelling of exactly the names it targets.

        This spelling also shows the bug at its worst. parse() reads the raw
        name too, so it finds no type signal and the folder is NOT promoted to a
        product boundary the way "Chibi Hero" is — it keeps recursing, and every
        model underneath took the unrelated sibling's character, not just one.
        """
        creator_dir = tmp_path / "Creator"
        for variant in ("Supported", "Unsupported"):
            _stl(creator_dir / "Chibi_Hero" / variant / "STL")
            _stl(creator_dir / "Goblin" / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        assert chars[str(Path("Chibi_Hero/Supported"))] == "Chibi_Hero"
        assert chars[str(Path("Chibi_Hero/Unsupported"))] == "Chibi_Hero"
        assert chars[str(Path("Goblin/Supported"))] == "Goblin"
        assert chars[str(Path("Goblin/Unsupported"))] == "Goblin"

    def test_two_type_worded_folders_beside_a_two_variant_product(self, db, tmp_path):
        """The arithmetic spillover, measured rather than assumed. Letting these
        folders vote grows the majority denominator: 2 of 2 was a strict
        majority, 2 of 4 is not. Ada Wong's own two variants still group, and
        the two type-worded folders become products instead of being absorbed
        into her — which is the same fix in a different costume, not a new
        class of behaviour."""
        creator_dir = tmp_path / "Creator"
        for variant in ("Ada Wong Supported", "Ada Wong Unsupported"):
            _stl(creator_dir / variant / "STL")
        _stl(creator_dir / "Bust" / "STL")
        _stl(creator_dir / "Statue" / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        assert chars[str(Path("Ada Wong Supported"))] == "Ada Wong"
        assert chars[str(Path("Ada Wong Unsupported"))] == "Ada Wong"
        assert chars[str(Path("Bust"))] == "Bust"
        assert chars[str(Path("Statue"))] == "Statue"

    def test_a_genuinely_structural_folder_still_takes_the_shared_character(self, db, tmp_path):
        """The guard on the fix, and the reason it keys on the token rule rather
        than on position alone. "Renders" and "Supported" are listed structural
        names, not type-keyword names, so they keep inheriting the creator's one
        real product — they are that product's render/format folders, not
        products of their own."""
        creator_dir = tmp_path / "Creator"
        for variant in ("Supported", "Unsupported"):
            _stl(creator_dir / "Goblin" / variant / "STL")
        _stl(creator_dir / "Renders" / "STL")
        _stl(creator_dir / "Supported" / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert {m.character for m in _models(db, creator)} == {"Goblin"}

    def test_a_type_worded_variant_under_a_real_character_is_not_a_product(self, db, tmp_path):
        """The regression the fix is designed around. "Bust" and "Statue" are
        variants of Ada Wong, not two products — the folder above them supplies
        the identity, so the token rule must not fire there. Splitting these is
        what a name-only fix would have done."""
        creator_dir = tmp_path / "Creator"
        for variant in ("Bust", "Statue", "Supported"):
            _stl(creator_dir / "Ada Wong" / variant / "STL")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert {m.character for m in _models(db, creator)} == {"Ada Wong"}

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

    def test_sibling_variant_folders_with_identical_leaf_names_disambiguate(self, db, tmp_path):
        """Real incident: two sibling top-level variant folders ("Mult Color
        Filament" / "One Color Filament") each hold their own identically-named
        per-part subfolders (EchoMasteryTracker/HealthTracker/RoundTracker).
        The leaf strategy assigns character purely from the child's own folder
        name, with no memory of which branch it came from, so both branches'
        "EchoMasteryTracker" collided onto the same character/destination —
        "Mult Color Filament" could never import because "One Color Filament"
        had already claimed that destination. Each must disambiguate by its
        own immediate parent folder name."""
        creator_dir = tmp_path / "Malediction"
        pack = creator_dir / "Malediction Trackers"
        for variant in ("Mult Color Filament", "One Color Filament"):
            for part in ("EchoMasteryTracker", "HealthTracker", "RoundTracker"):
                _stl(pack / variant / part)
        creator = make_creator(db, "Malediction")

        _walk(db, creator, creator_dir)

        chars = {m.character for m in _models(db, creator)}
        assert chars == {
            "Mult Color Filament — EchoMasteryTracker",
            "Mult Color Filament — HealthTracker",
            "Mult Color Filament — RoundTracker",
            "One Color Filament — EchoMasteryTracker",
            "One Color Filament — HealthTracker",
            "One Color Filament — RoundTracker",
        }

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

    def test_a_folder_extending_its_ancestor_keeps_the_ancestors_character(
            self, db, tmp_path):
        """STUDIO-429: a model's character must not depend on how deep it sits
        below the character folder.

        Transcribed from a real library tree (creator `Abe3d`, character folder
        `2B`) — seven model folders at mixed depths under one character folder,
        with the file counts per folder checked against the source. Depth-1
        folders inherited `2B`,
        but every folder that merely *extends* that identity
        (`1_4 2B YoRHa - Abe3D`) discarded it and named itself, so its own
        children keyed to `2B YoRHa` instead. One character folder, four
        characters, three of them wrong.

        `character_key` strips the scale prefix and the creator suffix, so the
        two spellings collapse to `2B` and `2B YoRHa` — two product keys, and
        with the hierarchy boundary on they cannot merge (see the companion
        grouping test). Hierarchy off, the FILENAME signal welded all seven
        anyway, which is why this went unnoticed: the character was already
        wrong in both modes, and it is user-visible in the Library and in
        Reorganize's `{character}` token.
        """
        creator_dir = tmp_path / "Abe3d"
        char = creator_dir / "2B"
        for scale in ("1_4", "1_6"):
            _stl(char / f"{scale} 2B YoRHa - Abe3D")
            _stl(char / f"{scale} 2B YoRHa - Abe3D" / "Alternative")
            _stl(char / "2B YoRHa - Abe3D NSFW" / f"{scale} 2B YoRHa - Abe3D NSFW")
        _stl(char / "1_4 update v1.1 - skirt narrow v2")
        creator = make_creator(db, "Abe3d")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 7
        assert {m.character for m in models} == {"2B"}

    def test_a_folder_whose_name_merely_repeats_its_ancestor_still_names_itself(
            self, db, tmp_path):
        """The carve-out that keeps STUDIO-429 from flattening punctuation.

        A folder whose key *equals* the one it inherited is the folder the
        ancestor was pointing at, so its raw spelling wins — the inherited value
        is a normalised `character_key` with dashes stripped, and it is the raw
        name that reaches the Library and Reorganize. Keep only "does my key
        extend the inherited one" and this reads `Auron Final Fantasy X`.

        Guards against widening the rule to `startswith` alone, which is true
        for equal keys too.
        """
        creator_dir = tmp_path / "Creator"
        char = creator_dir / "Auron - Final Fantasy X"
        _stl(char / "STL" / "Bust")
        _stl(char / "Presupport" / "Bust")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        assert {m.character for m in _models(db, creator)} == {
            "Auron - Final Fantasy X"}

    def test_an_unrelated_sibling_still_names_itself_however_short_the_inherited_key(
            self, db, tmp_path):
        """The other half of STUDIO-429's rule: inheriting is for folders that
        *extend* the ancestor, never for every folder that happens to sit under
        a shorter name.

        `Orc` wins the majority vote here (two of the three children key to it),
        so `Goblin Warrior` is handed a character it has nothing to do with.
        Its key is longer than the inherited one but does not extend it, so it
        must name itself — otherwise the model beneath it is filed under *Orc*,
        which is STUDIO-410's weld arriving by a new route.
        """
        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Set"
        _stl(pack / "Orc")
        _stl(pack / "Orc - Creator")
        _stl(pack / "Goblin Warrior" / "Alternative")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        assert chars[str(Path("Set/Goblin Warrior/Alternative"))] == "Goblin Warrior"
        assert chars[str(Path("Set/Orc"))] == "Orc"

    def test_extending_the_ancestor_is_judged_case_insensitively(self, db, tmp_path):
        """STUDIO-413's rule, applied to STUDIO-429's test: one creator typing a
        single folder in a different case must not split their own character.

        `character_key` preserves the creator's casing — it returns `2B YoRHa`,
        not `2b yorha` — so comparing the two keys raw makes `1_4 2B YoRHa`
        stop extending a character folder typed `2b`. It would then name itself,
        and the model below it would key to `2B YoRHa` while its shallower
        siblings key to `2b`: the depth split all over again, triggered by one
        capital letter. The sibling vote folds case for this exact reason.
        """
        creator_dir = tmp_path / "Abe3d"
        char = creator_dir / "2b"                     # lower-case character folder
        for scale in ("1_4", "1_6"):
            _stl(char / f"{scale} 2B YoRHa - Abe3D")
        _stl(char / "1_4 2B YoRHa - Abe3D" / "Alternative")
        creator = make_creator(db, "Abe3d")

        _walk(db, creator, creator_dir)

        assert {m.character for m in _models(db, creator)} == {"2b"}

    def test_a_mesh_repair_pair_is_one_product(self, db, tmp_path):
        """STUDIO-428: `Original` and `Repaired` name one product twice.

        Transcribed from a real library tree (creator `Zenith Studios`), which
        ships a fixed mesh beside the sculptor's untouched one for 26 characters
        and spells the pair `<Character>_STL_Original` / `…_STL_Repaired`. The
        `_STL_` sits mid-name — the ticket's own example writes `Ciri Original`,
        which is the *derived* character, not the folder on disk, and a test
        against the tidied spelling would not exercise the real string.

        Before the fix the two folders keyed to `Ciri Original` and
        `Ciri Repaired`: two products, and the sibling vote saw no majority, so
        each named itself. Hierarchy off a content signal welds them anyway, so
        the visible damage is the label; hierarchy on, the product boundary makes
        the split permanent. That is 49 of the 132 groupings STUDIO-427 measured
        as the cost of turning the flag on.
        """
        creator_dir = tmp_path / "Zenith Studios"
        char = creator_dir / "Ciri"
        _stl(char / "Ciri_STL_Original")
        _stl(char / "Ciri_STL_Repaired")
        creator = make_creator(db, "Zenith Studios")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 2
        assert {m.character for m in models} == {"Ciri"}

    def test_the_singular_repair_spelling_groups_with_its_pair(self, db, tmp_path):
        """The same creator typed one of the 26 pairs `_STL_Repair`, singular.

        Worth its own test rather than a parametrize: `repair(?:ed)?` relies on
        the trailing `\\b` forcing a backtrack into the optional group, so a
        "simplification" to `repair` or `repaired` alone silently drops one
        spelling — and this is the only folder in the library that would notice.
        """
        creator_dir = tmp_path / "Zenith Studios"
        char = creator_dir / "Dexter Morgan"
        _stl(char / "Dexter_STL_Original")
        _stl(char / "Dexter_STL_Repair")
        creator = make_creator(db, "Zenith Studios")

        _walk(db, creator, creator_dir)

        assert {m.character for m in _models(db, creator)} == {"Dexter"}

    def test_a_bare_repaired_folder_level_does_not_become_a_character(
            self, db, tmp_path):
        """The other half of STUDIO-428: the same prep state one level up.

        Transcribed from `ZEZ Studios/Trapjaw`, where the repaired mesh is a
        folder *level* rather than a name suffix. Before the fix that folder
        carried `character='Repaired'` — a product of one, ungrouped, while its
        two siblings sat together — and a second creator spelling a folder the
        same way would have welded two unrelated characters into one bucket, the
        cross-character collapse `_STRUCTURAL_EXACT` exists to prevent
        (STUDIO-281/288/291).

        Asserting "every model here shares one character" rather than naming the
        winner: the point is that the prep word is not one of them, and pinning
        the exact label would re-pin the sibling vote's tie-breaking, which is
        STUDIO-429's business and not this ticket's.
        """
        creator_dir = tmp_path / "ZEZ Studios"
        char = creator_dir / "Trapjaw"
        # Transcribed rather than reduced to one dummy STL each, because the file
        # list is load-bearing twice over. `base_1-2_0.stl` is a two-part base,
        # but `_SCALE_RATIO` reads "1-2" as a 1:2 scale, so `parse_folder` calls
        # the Repaired folder a product and it becomes a boundary child with a
        # model of its own — which is the only reason there is a stray character
        # here to fix. A one-file stand-in makes the folder vanish into its parent
        # and the test then passes against any code at all.
        parts = ["base_1-2", "base_2-2", "head", "torso", "left_arm", "full_base"]
        for p in parts:
            _stl(char / "trap jaw 1-6", f"{p}.stl")
            _stl(char / "trap jaw 1-6" / "Repaired", f"{p}_0.stl")
        _stl(char / "trapjaw bust")
        creator = make_creator(db, "ZEZ Studios")

        _walk(db, creator, creator_dir)

        chars = {_rel(m, creator_dir): m.character for m in _models(db, creator)}
        assert len(chars) == 3, chars
        assert "Repaired" not in chars.values(), chars
        # It inherits the product it sits under. Comparing keys rather than the
        # raw labels: the label is the sibling vote's business (STUDIO-429/413),
        # and grouping compares `character_key`, which is what has to match.
        repaired = chars[str(Path("Trapjaw/trap jaw 1-6/Repaired"))]
        parent = chars[str(Path("Trapjaw/trap jaw 1-6"))]
        assert name_parser.character_key(repaired) == name_parser.character_key(
            parent) != "", chars

    def test_a_container_named_original_still_holds_distinct_products(
            self, db, tmp_path):
        """STUDIO-428's counter-case, and the reason the change was measured
        rather than assumed safe.

        `Mod Innovations` uses `Original` as a *load-bearing* container name —
        it means "the legacy bolts, not the V2 ones" — and the folder holds four
        genuinely different products beside a sibling container. Stripping the
        word takes its key from `Modi Bolts Original` to `Modi Bolts`, which is
        exactly one of its own children's keys. That is STUDIO-422's failure
        shape reached through this ticket's vocabulary, so it needs pinning
        rather than a paragraph saying it is fine.

        It survives because the sibling vote takes `leaf` when the children carry
        distinct keys, and the container's own key is unread on that path.

        What this test actually kills, measured rather than asserted: handing
        distinct-keyed children the container's name instead of their own, and
        the prep words landing in `_MODIFIERS` (which moves `parse()` and with it
        the product-boundary decision). It does NOT kill a relaxed majority rule
        — four children each holding one vote never reach a majority under any
        variant of that arithmetic — so that guard belongs to STUDIO-410/412's
        tests, not this one.

        The two identically-named `ExtraStrong Modi Bolts` leaves are the sharp
        end: they are distinguished by nothing but their container, so if the
        containers ever collapse these two merge silently.
        """
        creator_dir = tmp_path / "Mod Innovations"
        legacy = creator_dir / "Z. Legacy Bolts"
        for leaf in ("ExtraStrong Modi Bolts", "Modi Bolts",
                     "Modi Bolts with Locks", "Modi locks"):
            _stl(legacy / "Modi Bolts Original" / leaf)
        for leaf in ("ExtraStrong Modi Bolts", "Pop Bolts"):
            _stl(legacy / "Modi Pop Bolts" / leaf)
        creator = make_creator(db, "Mod Innovations")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 6
        chars = {_rel(m, creator_dir): m.character for m in models}
        legacy_rel = Path("Z. Legacy Bolts")
        # Pinned as exact values rather than "four distinct ones". Distinctness
        # is too weak to notice the coincidence this fix introduces: the
        # container's key becomes `Modi Bolts`, which is byte-identical to the
        # `Modi Bolts` child's. A leaf path that let an equal-keyed child inherit
        # the container's name instead relabels that child and still leaves four
        # distinct values, so it passed a distinctness assertion — and passed the
        # whole 560-test suite — while quietly changing behaviour.
        assert {
            leaf: chars[str(legacy_rel / "Modi Bolts Original" / leaf)]
            for leaf in ("ExtraStrong Modi Bolts", "Modi Bolts",
                         "Modi Bolts with Locks", "Modi locks")
        } == {
            # Qualified by the container's RAW name (STUDIO-287), which this
            # change does not touch — `qualifier_from_folder` deliberately skips
            # the strip pipeline, so the container keeps "Original" in the label
            # even though its grouping key no longer carries it.
            "ExtraStrong Modi Bolts": "Modi Bolts Original — ExtraStrong Modi Bolts",
            "Modi Bolts": "Modi Bolts",
            "Modi Bolts with Locks": "Modi Bolts with Locks",
            "Modi locks": "Modi locks",
        }, chars
        # The two same-named leaves are told apart only by their container.
        assert (chars[str(legacy_rel / "Modi Bolts Original" / "ExtraStrong Modi Bolts")]
                != chars[str(legacy_rel / "Modi Pop Bolts" / "ExtraStrong Modi Bolts")])


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

        rules = scanner.ScanRules(pack_overrides=frozenset({str(pack)}))
        _walk(db, creator, creator_dir, rules=rules)

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

    def test_split_pack_honours_root_group_by_character(self, db, tmp_path, monkeypatch):
        """split_pack's re-walk must thread the owning root's group_by_character
        flag through to _walk_for_models (STUDIO-297) — otherwise a pack under a
        folder-grouped root loses that behavior until the next full scan.

        "32mm" suffixes make the fixture discriminating: with the flag correctly
        honoured, each split child's character is the RAW folder name (unnormalised,
        per group_by_character semantics); with the flag silently dropped (the bug),
        the default name-heuristic strips "32mm" via character_key instead.
        """
        from sqlalchemy.orm import sessionmaker
        from app.models import ScanRoot
        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)

        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Six"
        for char in ("Electro 32mm", "Sandman 32mm", "Spiderman 32mm"):
            _stl(pack / char)

        setup = Session()
        setup.add(ScanRoot(path=str(tmp_path), layout="{creator}", enabled=True, group_by_character=True))
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
        chars = {m.character for m in check.query(Model).filter(Model.creator_id == creator_id)}
        assert chars == {"Electro 32mm", "Sandman 32mm", "Spiderman 32mm"}
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

    def test_model_under_failed_creator_walk_is_protected(self, db, tmp_path):
        """STUDIO-296: a creator whose walk raised mid-scan was only partially
        re-indexed — its untouched models' folders can look stale for reasons
        that have nothing to do with an actual deletion (a transient error
        partway through, same STUDIO-79 rationale as the other two prunes).
        Model.folder_path missing under a protected creator must survive."""
        creator = make_creator(db, "Creator")
        protected_missing = self._model(db, creator, "protected", tmp_path / "gone", on_disk=False)
        clean_creator = make_creator(db, "OtherCreator")
        clean_missing = self._model(db, clean_creator, "unprotected", tmp_path / "also_gone", on_disk=False)
        # Kept under the UNPROTECTED creator: the cap check only sees models
        # left after excluding the protected creator, so it needs its own
        # non-stale sibling to stay under the 50% cap.
        self._model(db, clean_creator, "kept", tmp_path / "kept")
        protected_id, clean_missing_id = protected_missing.id, clean_missing.id

        removed = scanner._prune_stale_paths(
            db, [str(tmp_path)], protected_creator_ids={creator.id},
        )

        assert removed == 1
        remaining_ids = {m.id for m in db.query(Model).all()}
        assert protected_id in remaining_ids, "protected creator's missing-folder model must survive"
        assert clean_missing_id not in remaining_ids, "unprotected creator's missing-folder model still pruned"

    def test_no_protected_ids_behaves_as_before(self, db, tmp_path):
        """Default param (no protected_creator_ids) matches pre-STUDIO-296
        behaviour exactly — existing positional-arg call sites/tests unaffected."""
        creator = make_creator(db, "Creator")
        self._model(db, creator, "kept", tmp_path / "kept")
        self._model(db, creator, "renamed", tmp_path / "old_name", on_disk=False)

        assert scanner._prune_stale_paths(db, [str(tmp_path)]) == 1


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
                # Capture the root-paths list explicitly. The prunes take it at
                # different positions and _prune_ignored now takes an ignore
                # matcher after it, so a positional heuristic (args[-1]) grabs
                # the wrong argument.
                captured[key] = next(a for a in args if isinstance(a, list))
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


class TestScanRootLastScannedBaseline:
    """STUDIO-295: root.last_scanned must only advance when the root was
    online AND its creator walk raised no errors this run — otherwise a file
    changed during the offline/failed window compares against a baseline
    that's newer than reality and is wrongly treated as unchanged forever
    (compounds the STUDIO-294 skip check)."""

    def _stub_prunes(self, monkeypatch):
        monkeypatch.setattr(scanner, "_prune_stale_models", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "_prune_stale_paths", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "_prune_stale_stl_files", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "_prune_ignored", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "_prune_slicer_files", lambda *a, **k: None)
        monkeypatch.setattr(scanner, "_prune_phantoms", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "prune_empty_creators", lambda *a, **k: None)

    def test_offline_root_leaves_last_scanned_unchanged(self, db, tmp_path, monkeypatch):
        from datetime import timedelta
        from app.models import ScanRoot

        prior = utcnow() - timedelta(days=1)
        root = ScanRoot(path=str(tmp_path), enabled=True, last_scanned=prior)  # empty dir → offline
        db.add(root)
        db.commit()
        self._stub_prunes(monkeypatch)

        scanner.scan_all_roots(db)
        db.refresh(root)

        assert root.last_scanned == prior, "offline root must not advance its baseline"

    def test_failed_creator_walk_leaves_last_scanned_unchanged(self, db, tmp_path, monkeypatch):
        from datetime import timedelta
        from app.models import ScanRoot

        (tmp_path / "creator").mkdir()  # non-empty → online
        prior = utcnow() - timedelta(days=1)
        root = ScanRoot(path=str(tmp_path), enabled=True, last_scanned=prior)
        db.add(root)
        db.commit()
        self._stub_prunes(monkeypatch)
        monkeypatch.setattr(scanner, "_scan_root", lambda root, _db, _rules: {999})  # simulate a failed creator

        scanner.scan_all_roots(db)
        db.refresh(root)

        assert root.last_scanned == prior, "root with a failed creator walk must not advance its baseline"

    def test_clean_online_walk_advances_last_scanned_to_scan_start(self, db, tmp_path, monkeypatch):
        from datetime import timedelta
        from app.models import ScanRoot

        (tmp_path / "creator").mkdir()  # non-empty → online
        prior = utcnow() - timedelta(days=1)
        root = ScanRoot(path=str(tmp_path), enabled=True, last_scanned=prior)
        db.add(root)
        db.commit()
        self._stub_prunes(monkeypatch)
        monkeypatch.setattr(scanner, "_scan_root", lambda root, _db, _rules: set())

        before = utcnow()
        scanner.scan_all_roots(db)
        after = utcnow()
        db.refresh(root)

        assert root.last_scanned is not None and root.last_scanned != prior
        assert before <= root.last_scanned <= after, (
            "baseline must be the pre-walk scan_start timestamp, not stale, "
            "not from mid/post-walk"
        )


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

    def test_returns_all_case_variant_directories(self, db, tmp_path, monkeypatch):
        """Case-sensitive hosts may contain both spellings of one creator."""
        from app.models import ScanRoot

        class CaseSensitiveDir:
            def __init__(self, path: str):
                self.path = path
                self.name = path.rsplit("/", 1)[-1]

            def exists(self) -> bool:
                return True

        upper = CaseSensitiveDir("/library/Abe3D")
        lower = CaseSensitiveDir("/library/abe3d")
        root = ScanRoot(path=str(tmp_path), layout="{creator}", enabled=True)
        db.add(root)
        db.commit()
        monkeypatch.setattr(
            scanner.layout,
            "iter_creator_dirs",
            lambda *_args: [(upper, []), (lower, [])],
        )

        results = scanner._creator_dirs_by_name("Abe3D", db)

        assert [directory.path for directory, *_ in results] == [
            "/library/Abe3D",
            "/library/abe3d",
        ]

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
# _get_or_create_creator case handling (STUDIO-298)
# ---------------------------------------------------------------------------

class TestGetOrCreateCreatorCaseInsensitive:
    """Folder-derived creator lookup must dedup on case like resolve_creator.

    The reported failure: a creator stored by the scraper as "Abe3d" plus an
    on-disk folder "abe3d" made every scan insert a second Creator row, which
    prune_empty_creators then cleaned up after the fact.
    """

    def test_reuses_a_creator_stored_with_different_casing(self, db):
        existing = make_creator(db, name="Abe3d")
        assert scanner._get_or_create_creator("abe3d", db).id == existing.id

    def test_repeated_scans_do_not_fork_a_duplicate_row(self, db):
        make_creator(db, name="Abe3d")
        for spelling in ("abe3d", "ABE3D", "Abe3D"):
            scanner._get_or_create_creator(spelling, db)
        db.flush()
        assert db.query(Creator).filter(func.lower(Creator.name) == "abe3d").count() == 1

    def test_creates_with_the_folder_casing_when_no_match_exists(self, db):
        created = scanner._get_or_create_creator("BrandNewCreator", db)
        assert created.name == "BrandNewCreator"

    def test_case_variant_adoption_is_logged(self, db, caplog):
        """On Linux this can merge two genuinely distinct artists, so it must
        leave a trace even though it is harmless in the common case."""
        make_creator(db, name="Abe3d")
        with caplog.at_level("WARNING"):
            scanner._get_or_create_creator("ABE3D", db)
        assert any("differs only by case" in r.getMessage() for r in caplog.records)

    def test_an_exact_match_logs_nothing(self, db, caplog):
        make_creator(db, name="Abe3d")
        with caplog.at_level("WARNING"):
            scanner._get_or_create_creator("Abe3d", db)
        assert not caplog.records

    def test_creating_a_new_creator_logs_nothing(self, db, caplog):
        with caplog.at_level("WARNING"):
            scanner._get_or_create_creator("Totally New", db)
        assert not caplog.records

    def test_wildcard_characters_in_folder_names_are_literal(self, db):
        # Inherited from resolve_creator's lowered-equality rule (#217): a
        # folder named "My_Studio" must not adopt an existing "MyXStudio".
        decoy = make_creator(db, name="MyXStudio")
        assert scanner._get_or_create_creator("My_Studio", db).id != decoy.id

    def test_a_full_scan_indexes_case_variant_folders_under_one_creator(self, db, tmp_path):
        """End-to-end: two case-distinct creator folders, one Creator row.

        Chosen over host-sensitive folder identity deliberately — see the
        STUDIO-298 decision recorded on the ticket. Each model still keeps its
        own folder_path, so no model is lost by sharing a creator.
        """
        root = tmp_path / "library"
        _stl(root / "Abe3d" / "model-a", name="a.stl")
        _stl(root / "abe3d" / "model-b", name="b.stl")

        first = scanner._get_or_create_creator("Abe3d", db)
        second = scanner._get_or_create_creator("abe3d", db)
        db.flush()

        assert first.id == second.id
        _walk(db, first, root / "Abe3d")
        _walk(db, second, root / "abe3d")
        assert len(_models(db, first)) == 2, "both folders' models land on one creator"


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

        def fake_scan_root(root, _db, _rules):
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

    def test_multiple_part_siblings_collapse_to_one_model(self, db, tmp_path):
        # STUDIO-371: before the boundary fix, "STL" and "Supported STL" each
        # independently qualified as their own leaf model (both cosmetically
        # renamed to the character), producing duplicate-looking rows. They
        # must now collapse into the single product-folder model.
        creator_dir = tmp_path / "Creator"
        product = creator_dir / "Auron"
        _stl(product / "STL", name="a.stl")
        _stl(product / "Supported STL", name="b.stl")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert [Path(m.folder_path) for m in models] == [product]
        assert {f.filename for f in models[0].stl_files} == {"a.stl", "b.stl"}

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
    monkeypatch.setattr(scanner.ScanRules, "load", classmethod(lambda cls, _db: cls()))
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
        # A structural-variant leaf under a plain character folder — no direct
        # STLs of its own, everything lives in "STL" — named after the
        # character via the #641 leaf-naming. Prior to STUDIO-371 this shape
        # (with a "Supported STL" sibling added) produced two separate rows
        # both cosmetically named "Auron"; the boundary fix collapses it to
        # the one row STUDIO-371 requires, which is what these name-healing
        # tests need — a single mutable model to test refresh behavior on.
        _stl(creator_dir / "Auron" / "STL")
        _walk(db, creator, creator_dir)
        models = _models(db, creator)
        assert len(models) == 1
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


class TestIncrementalSkipBaseline:
    """STUDIO-294: the folder-unchanged skip compares st_mtime (POSIX epoch)
    against last_scanned (naive UTC). Converting last_scanned with .timestamp()
    read it as LOCAL time, inflating the baseline by the host's UTC offset —
    folders changed within that window after a scan were wrongly skipped and
    their new files never indexed. utc_timestamp() must be used instead."""

    def _rewalk(self, db, creator, creator_dir, last_scanned):
        scanner._walk_for_models(
            folder=creator_dir, creator=creator, db=db,
            creator_boundary=creator_dir, character=None,
            stl_cache={}, last_scanned=last_scanned, rules=scanner.ScanRules(),
        )

    def _stl_count(self, db, creator):
        model = _models(db, creator)[0]
        return db.query(STLFile).filter(STLFile.model_id == model.id).count()

    def test_folder_changed_after_baseline_is_reindexed(self, db, tmp_path):
        from datetime import timedelta
        from app.utils import utcnow

        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Auron", name="a.stl")
        creator = make_creator(db, "Creator")
        _walk(db, creator, creator_dir)
        assert self._stl_count(db, creator) == 1

        # New file lands after the recorded baseline → must be re-indexed. With
        # the pre-fix local-time reading of a naive-UTC baseline, any change
        # within ~|UTC offset| of the baseline looked "unchanged" and was
        # skipped; a 1-minute-old baseline sits squarely inside that window on
        # every non-UTC host, so this fails without the fix (and is a plain
        # correctness check on UTC hosts).
        baseline = utcnow() - timedelta(minutes=1)
        _stl(creator_dir / "Auron", name="b.stl")

        self._rewalk(db, creator, creator_dir, last_scanned=baseline)
        assert self._stl_count(db, creator) == 2, "change after baseline must be indexed"

    def test_folder_unchanged_since_baseline_skips_file_indexing(self, db, tmp_path):
        from datetime import timedelta
        from app.utils import utcnow

        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Auron", name="a.stl")
        creator = make_creator(db, "Creator")
        _walk(db, creator, creator_dir)

        # Baseline far in the future relative to the folder's mtime → the skip
        # path must engage (this is the intended fast path, unchanged by the fix).
        baseline = utcnow() + timedelta(days=1)
        # Sneak a file in without the walk noticing wouldn't be possible with a
        # real mtime bump, so instead delete the STL row: a skipped folder never
        # re-runs _index_stl_files, so the row must stay gone.
        model = _models(db, creator)[0]
        db.query(STLFile).filter(STLFile.model_id == model.id).delete()
        db.commit()

        self._rewalk(db, creator, creator_dir, last_scanned=baseline)
        assert self._stl_count(db, creator) == 0, "unchanged folder must skip file indexing"


# ---------------------------------------------------------------------------
# Read-failure reporting (STUDIO-358)
# ---------------------------------------------------------------------------

class _RaisingEntry:
    """A DirEntry stand-in whose is_dir() raises, as a too-long or broken path does."""

    def __init__(self, path: str, error: OSError):
        self.path = path
        self.name = os.path.basename(path)
        self._error = error

    def is_dir(self):
        raise self._error


class _FakeScandir:
    """Context-manager iterator matching os.scandir()'s protocol."""

    def __init__(self, entries):
        self._entries = entries

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, *exc):
        return False


def _inject_entry_failure(monkeypatch, target: Path, bad_name: str, error: OSError):
    """Make one entry of *target* raise on is_dir(); every other folder reads normally."""
    real_scandir = os.scandir

    def fake_scandir(path):
        if Path(path) == target:
            entries = list(real_scandir(path))
            entries.append(_RaisingEntry(str(target / bad_name), error))
            return _FakeScandir(entries)
        return real_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", fake_scandir)


class TestListDir:
    def test_per_entry_failure_is_recorded_not_raised(self, tmp_path, monkeypatch):
        _stl(tmp_path / "Good")
        _inject_entry_failure(monkeypatch, tmp_path, "TooLong.stl", OSError(63, "File name too long"))

        listing = scanner._list_dir(tmp_path)

        assert [d.name for d in listing.dirs] == ["Good"]
        assert len(listing.failures) == 1
        assert listing.failures[0].path.endswith("TooLong.stl")
        assert "too long" in listing.failures[0].error.lower()

    def test_whole_directory_failure_propagates(self, tmp_path, monkeypatch):
        """Must NOT be swallowed: the creator walk relies on this to shield its
        models from the stale prune (STUDIO-79)."""
        def boom(path):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(scanner.os, "scandir", boom)

        with pytest.raises(PermissionError):
            scanner._list_dir(tmp_path)

    def test_readable_folder_reports_no_failures(self, tmp_path):
        _stl(tmp_path / "Good")
        (tmp_path / "notes.txt").write_text("x")

        listing = scanner._list_dir(tmp_path)

        assert listing.failures == []
        assert [d.name for d in listing.dirs] == ["Good"]
        assert [f.name for f in listing.files] == ["notes.txt"]

    def test_empty_folder_is_not_a_failure(self, tmp_path):
        listing = scanner._list_dir(tmp_path)
        assert listing == scanner.DirListing(dirs=[], files=[], failures=[])


class TestWalkReadFailures:
    def test_walk_records_failure_and_still_indexes(self, db, tmp_path, monkeypatch):
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Auron")
        creator = make_creator(db, "Creator")
        _inject_entry_failure(
            monkeypatch, creator_dir, "Deep.stl", OSError(63, "File name too long"),
        )

        failures: list[scanner.ReadFailure] = []
        scanner._walk_for_models(
            folder=creator_dir, creator=creator, db=db,
            creator_boundary=creator_dir, character=None,
            stl_cache={}, last_scanned=None, rules=scanner.ScanRules(),
            read_failures=failures,
        )

        assert len(failures) == 1, "the unreadable entry must be reported"
        assert [_rel(m, creator_dir) for m in _models(db, creator)] == ["Auron"], \
            "one bad entry must not abort indexing of the rest of the folder"

    def test_clean_walk_records_nothing(self, db, tmp_path):
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Auron")
        creator = make_creator(db, "Creator")

        failures: list[scanner.ReadFailure] = []
        scanner._walk_for_models(
            folder=creator_dir, creator=creator, db=db,
            creator_boundary=creator_dir, character=None,
            stl_cache={}, last_scanned=None, rules=scanner.ScanRules(),
            read_failures=failures,
        )

        assert failures == []

    def test_empty_folder_classifies_as_before(self, db, tmp_path):
        """A genuinely empty folder is not a model — unchanged by this ticket."""
        creator_dir = tmp_path / "Creator"
        (creator_dir / "Empty").mkdir(parents=True)
        creator = make_creator(db, "Creator")

        failures: list[scanner.ReadFailure] = []
        scanner._walk_for_models(
            folder=creator_dir, creator=creator, db=db,
            creator_boundary=creator_dir, character=None,
            stl_cache={}, last_scanned=None, rules=scanner.ScanRules(),
            read_failures=failures,
        )

        assert failures == []
        assert _models(db, creator) == []


class TestReadFailureReporting:
    """_report_read_failures writes onto the active job's progress payload.

    Asserted against the handle directly rather than get_status(), which reads the
    shared runner registry — these tests exercise the writer, and the end-to-end
    mapping through get_status() is covered by TestReadFailureStatus below.
    """

    def _job(self, monkeypatch):
        job = JobHandle(key="scan", _lock=threading.Lock())
        monkeypatch.setattr(scanner, "_active", job)
        return job

    def test_reports_count_and_samples(self, monkeypatch):
        job = self._job(monkeypatch)

        scanner._report_read_failures([
            scanner.ReadFailure(path="/lib/a.stl", error="too long"),
            scanner.ReadFailure(path="/lib/b.stl", error="too long"),
        ])

        prog = job.payload()["progress"]
        assert prog["read_failures"] == 2
        assert prog["read_failure_samples"] == ["/lib/a.stl", "/lib/b.stl"]

    def test_sample_is_capped_but_count_is_exact(self, monkeypatch):
        job = self._job(monkeypatch)
        limit = scanner.READ_FAILURE_SAMPLE_LIMIT

        scanner._report_read_failures([
            scanner.ReadFailure(path=f"/lib/{i}.stl", error="too long")
            for i in range(limit + 10)
        ])

        prog = job.payload()["progress"]
        assert prog["read_failures"] == limit + 10, "count must not be capped"
        assert len(prog["read_failure_samples"]) == limit

    def test_repeated_reports_accumulate_without_exceeding_cap(self, monkeypatch):
        job = self._job(monkeypatch)
        limit = scanner.READ_FAILURE_SAMPLE_LIMIT

        for _ in range(3):
            scanner._report_read_failures([
                scanner.ReadFailure(path=f"/lib/{i}.stl", error="too long")
                for i in range(limit)
            ])

        prog = job.payload()["progress"]
        assert prog["read_failures"] == limit * 3
        assert len(prog["read_failure_samples"]) == limit

    def test_nothing_reported_when_clean(self, monkeypatch):
        job = self._job(monkeypatch)

        scanner._report_read_failures([])

        assert job.payload()["progress"] == {}


class TestReadFailureStatus:
    """_scan_root fans out to worker threads that open their own SessionLocal(),
    so it must be pointed at the test engine — same idiom as the other tests that
    exercise the real parallel walk."""

    def _bind(self, db, monkeypatch):
        monkeypatch.setattr(scanner, "SessionLocal", sessionmaker(bind=db.get_bind()))

    def test_status_surfaces_read_failures_end_to_end(self, db, tmp_path, monkeypatch):
        from app.models import ScanRoot

        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Auron")
        db.add(ScanRoot(path=str(tmp_path), enabled=True))
        db.commit()
        self._bind(db, monkeypatch)
        _inject_entry_failure(
            monkeypatch, creator_dir, "Deep.stl", OSError(63, "File name too long"),
        )

        scanner.scan_all_roots(db)

        status = scanner.get_status()
        assert status["read_failures"] >= 1
        assert any(p.endswith("Deep.stl") for p in status["read_failure_samples"])

    def test_status_reports_zero_on_a_clean_scan(self, db, tmp_path, monkeypatch):
        from app.models import ScanRoot

        _stl(tmp_path / "Creator" / "Auron")
        db.add(ScanRoot(path=str(tmp_path), enabled=True))
        db.commit()
        self._bind(db, monkeypatch)

        scanner.scan_all_roots(db)

        status = scanner.get_status()
        assert status["read_failures"] == 0
        assert status["read_failure_samples"] == []


class TestReadFailureProtectsPrune:
    def test_creator_with_read_failure_is_shielded_from_stale_prune(
        self, db, tmp_path, monkeypatch
    ):
        """A short listing may have changed classification, so anything not
        rediscovered this run must not be assumed deleted (STUDIO-79 protection)."""
        from app.models import ScanRoot

        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Auron")
        db.add(ScanRoot(path=str(tmp_path), enabled=True))
        db.commit()
        monkeypatch.setattr(scanner, "SessionLocal", sessionmaker(bind=db.get_bind()))
        _inject_entry_failure(
            monkeypatch, creator_dir, "Deep.stl", OSError(63, "File name too long"),
        )

        root = db.query(ScanRoot).first()
        failed = scanner._scan_root(root, db, scanner.ScanRules())

        creator = db.query(Creator).filter(Creator.name == "Creator").one()
        assert creator.id in failed, \
            "an unreadable entry must protect the creator's models from the stale prune"


# ---------------------------------------------------------------------------
# Shared path-boundary migration (STUDIO-230)
# ---------------------------------------------------------------------------

class TestPruneBoundarySharedBehavior:
    """All four prune helpers now share one root-membership implementation
    (services/path_boundary.PathBoundary). These pin the boundary behaviors that
    would fail SILENTLY if a call site were wired to the wrong method: a
    prefix-sharing sibling being treated as a descendant, or an empty root list
    being treated as "everything".

    _prune_stale_models already had sibling coverage; this extends the same
    assertion to the three helpers that previously carried their own copies.
    """

    def _model(self, db, creator, folder: Path, name: str, stale: bool = False):
        from datetime import timedelta
        ts = utcnow() - timedelta(hours=1) if stale else utcnow()
        m = Model(name=name, folder_path=str(folder), creator_id=creator.id, updated_at=ts)
        db.add(m)
        db.commit()
        return m

    def test_stale_paths_ignores_prefix_sharing_sibling(self, db, tmp_path):
        """A row under 'STLBackup' must not be pruned when only 'STL' is online —
        an unanchored prefix match would delete a whole parallel library."""
        scanned = tmp_path / "STL"
        scanned.mkdir()
        sibling = tmp_path / "STLBackup"
        creator = make_creator(db, "Creator")
        # Both folders are missing on disk; only the one under the online root
        # is eligible. Keep one live row so the 50% cap isn't tripped.
        (scanned / "live").mkdir()
        self._model(db, creator, scanned / "live", "live")
        self._model(db, creator, scanned / "gone", "gone")
        self._model(db, creator, sibling / "gone", "in_sibling")

        scanner._prune_stale_paths(db, [str(scanned)])

        names = {m.name for m in db.query(Model).all()}
        assert "gone" not in names, "missing folder under the online root should prune"
        assert "in_sibling" in names, "prefix-sharing sibling must never match"

    def test_stale_stl_files_ignores_prefix_sharing_sibling(self, db, tmp_path):
        scanned = tmp_path / "STL"
        sibling = tmp_path / "STLBackup"
        live = scanned / "live"
        live.mkdir(parents=True)
        sib_dir = sibling / "m"
        sib_dir.mkdir(parents=True)
        creator = make_creator(db, "Creator")

        m_in = self._model(db, creator, live, "in_root")
        m_out = self._model(db, creator, sib_dir, "in_sibling")
        db.add_all([
            STLFile(model_id=m_in.id, filename="a.stl", path=str(live / "a.stl")),
            STLFile(model_id=m_in.id, filename="b.stl", path=str(live / "b.stl")),
            STLFile(model_id=m_out.id, filename="c.stl", path=str(sib_dir / "c.stl")),
        ])
        db.commit()
        # Only b.stl exists on disk; a.stl and c.stl are stale rows.
        (live / "b.stl").write_bytes(b"x")

        scanner._prune_stale_stl_files(db, [str(scanned)])

        remaining = {r.filename for r in db.query(STLFile).all()}
        assert "a.stl" not in remaining, "missing file under the online root should prune"
        assert "c.stl" in remaining, "row under a prefix-sharing sibling must not match"

    def test_ignore_walkup_stops_at_the_scan_root(self, db, tmp_path, monkeypatch):
        """The walk-up uses is_root() (exact), not contains() (exact-or-descendant).

        With contains(), the very first iteration would match the model's own
        folder — it IS under the root — ending the climb immediately and silently
        disabling ignore rules for everything nested. Here the pattern only matches
        an ANCESTOR, so it is reachable solely by a climb that does not stop early.
        """
        root = tmp_path / "STL"
        creator_dir = root / "Creator"
        _stl(creator_dir / "WIP" / "HalfDone" / "Deep")
        _stl(creator_dir / "Knight")
        creator = make_creator(db, "Creator")
        _walk(db, creator, creator_dir)
        assert len(_models(db, creator)) == 2

        rules = scanner.ScanRules(ignore=IgnoreMatcher(("wip",)))
        removed = scanner._prune_ignored(db, [str(root)], rules.ignore)

        assert removed == 1, "a model nested below an ignored ancestor must be pruned"
        assert not any("WIP" in m.folder_path for m in _models(db, creator))

    def test_ignore_never_prunes_when_the_root_itself_matches(self, db, tmp_path, monkeypatch):
        """The climb stops ON the root without testing it — ignoring a whole scan
        root is not this feature's job, and doing so would wipe the library."""
        root = tmp_path / "wip"          # the ROOT's own name matches the pattern
        creator_dir = root / "Creator"
        _stl(creator_dir / "Knight")
        creator = make_creator(db, "Creator")
        _walk(db, creator, creator_dir)
        before = len(_models(db, creator))

        rules = scanner.ScanRules(ignore=IgnoreMatcher(("wip",)))
        removed = scanner._prune_ignored(db, [str(root)], rules.ignore)

        assert removed == 0
        assert len(_models(db, creator)) == before

    def test_empty_root_list_prunes_nothing(self, db, tmp_path):
        """'No roots' must never decay into 'everything'."""
        creator = make_creator(db, "Creator")
        self._model(db, creator, tmp_path / "gone", "gone", stale=True)

        assert scanner._prune_stale_paths(db, []) == 0
        assert scanner._prune_stale_stl_files(db, []) == 0
        assert scanner._prune_stale_models(db, utcnow(), []) == 0
        assert {m.name for m in db.query(Model).all()} == {"gone"}

    def test_blank_root_entry_prunes_nothing(self, db, tmp_path):
        """A blank root normalizes to '.', which as a boundary would match every
        relative path. PathBoundary.from_paths drops it instead."""
        creator = make_creator(db, "Creator")
        self._model(db, creator, tmp_path / "gone", "gone", stale=True)

        assert scanner._prune_stale_paths(db, [""]) == 0
        assert scanner._prune_stale_models(db, utcnow(), [""]) == 0
        assert {m.name for m in db.query(Model).all()} == {"gone"}


# ---------------------------------------------------------------------------
# Explicit scan-rules context (STUDIO-231)
# ---------------------------------------------------------------------------

class TestScanRules:
    """The per-run rule context that replaced the _pack_overrides /
    _ignore_matcher module globals."""

    def test_defaults_are_inert(self):
        """An empty context must mean 'no overrides, no ignore patterns, no user
        parser rules' — the state a fresh scan starts from."""
        rules = scanner.ScanRules()
        assert rules.pack_overrides == frozenset()
        assert rules.ignore.patterns == ()
        assert rules.parser_rules == name_parser.ParserRules()

    def test_is_immutable(self):
        """Frozen so the four parallel creator workers share read-only state by
        construction rather than by convention."""
        rules = scanner.ScanRules()
        with pytest.raises(Exception):
            rules.pack_overrides = frozenset({"/x"})  # type: ignore[misc]

    def test_load_reads_overrides_and_ignore_patterns(self, db):
        from app.models import AppSetting, PackOverride
        db.add(PackOverride(path="/lib/Creator/Pack"))
        db.add(AppSetting(key="scan_ignore_patterns", value=["wip"]))
        db.commit()

        rules = scanner.ScanRules.load(db)

        assert rules.pack_overrides == frozenset({"/lib/Creator/Pack"})
        # User patterns append to the built-in defaults (STUDIO-435 seeded
        # "__MACOSX"); they never replace them.
        assert rules.ignore.patterns == ("__macosx", "wip")

    def test_load_on_an_empty_db_is_inert(self, db):
        """"Inert" means no *user* configuration is applied. It stopped meaning
        "no ignore patterns at all" when STUDIO-435 seeded the built-in defaults,
        which are deliberately not user-removable."""
        rules = scanner.ScanRules.load(db)
        assert rules.pack_overrides == frozenset()
        assert rules.ignore.patterns == ("__macosx",)
        assert rules.parser_rules == name_parser.ParserRules()

    def test_load_reads_tag_rules_and_parts_names(self, db):
        """STUDIO-363: ScanRules.load() must populate parser_rules itself —
        no side effect on name_parser module state."""
        from app.models import AppSetting

        db.add(AppSetting(
            key="scan_tag_rules",
            value=[{"keyword": "Aztec", "tag": "civ"}],
        ))
        db.add(AppSetting(key="scan_parts_names", value=["sprues"]))
        db.commit()

        rules = scanner.ScanRules.load(db)

        assert rules.parser_rules.parts_names == frozenset({"sprues"})
        assert len(rules.parser_rules.tag_rules) == 1
        pattern, tag = rules.parser_rules.tag_rules[0]
        assert tag == "civ"
        assert pattern.search("Aztec Warrior")

        # A caller that never received this ScanRules still sees built-ins only —
        # ScanRules.load() must not have leaked state into name_parser globally.
        assert name_parser.is_structural_folder("Sprues") is False

    def test_walk_requires_rules(self, db, tmp_path):
        """Required, not defaulted: omitting them would silently walk with no
        pack splits and no ignore rules, which is what the globals allowed."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Knight")
        creator = make_creator(db, "Creator")

        with pytest.raises(TypeError):
            scanner._walk_for_models(
                folder=creator_dir, creator=creator, db=db,
                creator_boundary=creator_dir, character=None,
                stl_cache={}, last_scanned=None,
            )


class TestSplitPackHonoursIgnoreRules:
    def test_split_pack_applies_configured_ignore_patterns(self, db, tmp_path, monkeypatch):
        """split_pack now loads the FULL rule set (STUDIO-231).

        It previously loaded only pack overrides, so the re-walk consulted
        whatever _ignore_matcher the module global happened to hold — the last
        scan's patterns in a long-lived process, empty in a fresh one. A split now
        honours the user's ignore rules deterministically, like every other entry
        point.
        """
        from sqlalchemy.orm import sessionmaker
        from app.models import AppSetting

        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)

        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Six"
        for char in ("Electro", "Sandman"):
            _stl(pack / char / "supported")
        _stl(pack / "WIP" / "supported")   # covered by the ignore pattern below

        setup = Session()
        setup.add(AppSetting(key="scan_ignore_patterns", value=["wip"]))
        creator = Creator(name="Creator")
        setup.add(creator); setup.flush()
        creator_id = creator.id
        collapsed = Model(name="Sinister Six", folder_path=str(pack), creator_id=creator_id)
        setup.add(collapsed); setup.flush()
        collapsed_id = collapsed.id
        setup.commit(); setup.close()

        result = scanner.split_pack(collapsed_id)

        assert result["ok"] is True
        assert result["created"] == 2, "the ignored child must not become a model"
        check = Session()
        chars = {m.character for m in check.query(Model).filter(Model.creator_id == creator_id)}
        check.close()
        assert chars == {"Electro", "Sandman"}, "the ignored child must not be indexed"


# ---------------------------------------------------------------------------
# Separator-insensitive stored-path identity (STUDIO-365)
# ---------------------------------------------------------------------------

class TestSeparatorInsensitiveIdentity:
    """A row stored with the other separator style must be matched, not duplicated.

    The real `_normpath` is `normcase(normpath(...))`, which folds separators only
    on Windows — so the whole code path is skipped on case-sensitive hosts and a
    Linux-only CI run would report a green skip while the bug was live. These
    tests therefore INJECT a Windows-like normalizer rather than skipping on
    platform, so CI actually exercises the branch.
    """

    def _windows_like_normpath(self, monkeypatch):
        monkeypatch.setattr(
            scanner, "_normpath",
            lambda p: os.path.normpath(p).replace("\\", "/").lower(),
        )

    def _index_one(self, db, creator, root):
        _walk(db, creator, root)
        models = _models(db, creator)
        assert len(models) == 1
        return models[0]

    def test_stored_backslash_row_is_reused_not_duplicated(self, db, tmp_path, monkeypatch):
        """The production shape: stored path in the other separator style AND a
        different case. Before the fix the SQL prefilter folded case only, so this
        row was invisible and a duplicate was inserted."""
        self._windows_like_normpath(monkeypatch)
        creator = make_creator(db, "Creator")
        leaf = tmp_path / "Creator" / "Auron"
        _stl(leaf, name="auron.stl")
        root = tmp_path / "Creator"

        model = self._index_one(db, creator, root)
        original_id = model.id
        model.tags = ["favorite"]
        model.notes = "hand-primed"
        model.folder_path = str(leaf).replace("/", "\\").lower()
        db.commit()

        _walk(db, creator, root)

        models = _models(db, creator)
        assert len(models) == 1, "separator-only difference must not create a duplicate"
        assert models[0].id == original_id, "the existing row is reused in place"
        assert models[0].folder_path == str(leaf), "path adopted in the walked form"
        assert models[0].tags == ["favorite"], "user metadata survives"
        assert models[0].notes == "hand-primed"

    def test_reverse_separator_direction_also_matches(self, db, tmp_path, monkeypatch):
        self._windows_like_normpath(monkeypatch)
        creator = make_creator(db, "Creator")
        leaf = tmp_path / "Creator" / "Auron"
        _stl(leaf, name="auron.stl")
        root = tmp_path / "Creator"

        model = self._index_one(db, creator, root)
        original_id = model.id
        # Store a path whose separators are already folded the other way.
        model.folder_path = str(leaf).replace("/", "\\")
        db.commit()

        _walk(db, creator, root)

        models = _models(db, creator)
        assert len(models) == 1
        assert models[0].id == original_id

    def test_stl_rows_are_recased_not_duplicated(self, db, tmp_path, monkeypatch):
        self._windows_like_normpath(monkeypatch)
        creator = make_creator(db, "Creator")
        leaf = tmp_path / "Creator" / "Auron"
        _stl(leaf, name="auron.stl")
        root = tmp_path / "Creator"

        model = self._index_one(db, creator, root)
        before = db.query(STLFile).filter(STLFile.model_id == model.id).count()
        model.folder_path = str(leaf).replace("/", "\\").lower()
        for stl in db.query(STLFile).filter(STLFile.model_id == model.id):
            stl.path = stl.path.replace("/", "\\").lower()
        db.commit()

        _walk(db, creator, root)

        model = _models(db, creator)[0]
        after = db.query(STLFile).filter(STLFile.model_id == model.id).count()
        assert after == before, "STL rows recased in place, not duplicated"

    def test_pre_existing_duplicates_are_reported(self, db, tmp_path, monkeypatch, caplog):
        """Rows already duplicated by the old bug: adopting one leaves the others
        stale and unprunable, so the condition must be logged rather than silently
        resolved."""
        self._windows_like_normpath(monkeypatch)
        creator = make_creator(db, "Creator")
        leaf = tmp_path / "Creator" / "Auron"
        _stl(leaf, name="auron.stl")
        root = tmp_path / "Creator"

        model = self._index_one(db, creator, root)
        model.folder_path = str(leaf).replace("/", "\\").lower()
        db.add(Model(name="dupe", folder_path=str(leaf).upper(), creator_id=creator.id))
        db.commit()

        with caplog.at_level("WARNING"):
            _walk(db, creator, root)

        assert any("resolve to the same folder" in r.message for r in caplog.records), \
            "duplicate rows for one folder must be surfaced"

    def test_case_sensitive_host_keeps_distinct_folders_distinct(self, db, tmp_path, monkeypatch):
        """With a case-SENSITIVE normalizer the fallback is skipped entirely, so
        two genuinely different folders stay two models (STUDIO-226)."""
        monkeypatch.setattr(scanner, "_normpath", lambda p: os.path.normpath(p))
        creator = make_creator(db, "Creator")
        _stl(tmp_path / "Creator" / "Auron", name="a.stl")
        _stl(tmp_path / "Creator" / "auron", name="b.stl")

        _walk(db, creator, tmp_path / "Creator")

        assert len(_models(db, creator)) == 2, "case-distinct folders remain distinct"


# ---------------------------------------------------------------------------
# STUDIO-233 — transaction and failure semantics (characterization)
# ---------------------------------------------------------------------------

def _run_pool_inline(monkeypatch):
    """Make _scan_root's worker pool run each creator inline, in order.

    These tests characterize TRANSACTION semantics, not thread scheduling, and
    real threading is actively misleading on this fixture: the `db` fixture
    builds its engine with StaticPool and check_same_thread=False, so every
    worker's `SessionLocal()` lands on the SAME connection and therefore the
    same transaction. One worker's rollback would then discard another's
    uncommitted work as a pure harness artifact that production — a file-backed
    SQLite database with a real pool — never reproduces. Running the pool inline
    makes the sessions sequential, which is what gives them genuine isolation
    here.

    _scan_root's post-pool grouping pass already runs single-threaded on its own
    `group_db`, so it behaves identically either way.
    """
    class _InlineFuture:
        def __init__(self, fn, args, kwargs):
            self._exc = None
            try:
                self._value = fn(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 — re-raised in result()
                self._value, self._exc = None, exc

        def result(self):
            if self._exc is not None:
                raise self._exc
            return self._value

    class _InlineExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def submit(self, fn, *args, **kwargs):
            return _InlineFuture(fn, args, kwargs)

    monkeypatch.setattr(scanner, "ThreadPoolExecutor", _InlineExecutor)
    monkeypatch.setattr(scanner, "as_completed", lambda futures: list(futures))


class TestScannerTransactionSemantics:
    """STUDIO-233: pin the scanner's CURRENT commit boundaries and failure
    behavior before STUDIO-234/235 move transaction ownership around.

    Several of these tests assert behavior that is arguably wrong — one of them
    says so outright. That is the point of a characterization suite: if a later
    ticket deliberately changes one of these boundaries, the matching test
    SHOULD go red and be updated as part of that change. Do not "fix" a test
    here to agree with new behavior without confirming the change was intended.

    The policy these tests describe is written up in scanner.py's module
    docstring, under "Transaction and failure policy".
    """

    # -- creator-walk failure -------------------------------------------------

    def test_raised_creator_walk_is_reported_for_prune_protection(
        self, db, tmp_path, monkeypatch
    ):
        """A creator whose walk raises comes back in _scan_root's failed set,
        which is what shields its models from the destructive stale prune
        (STUDIO-79). Covers AC1 (creator-walk failure) and AC2.

        Fail-first: assert `failed == set()` instead and this goes red, which is
        what proves the injected walk really raised rather than being skipped.
        """
        from app.models import ScanRoot
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)
        _run_pool_inline(monkeypatch)

        _stl(tmp_path / "Doomed Creator" / "Model A")

        def _boom(**kwargs):
            raise OSError("simulated mid-walk failure")

        monkeypatch.setattr(scanner, "_walk_for_models", _boom)
        monkeypatch.setattr(scanner.grouping, "regroup_creator", lambda _db, _cid: None)
        monkeypatch.setattr(scanner.grouping, "prune_empty_groups", lambda _db: 0)

        root = ScanRoot(path=str(tmp_path), enabled=True)
        db.add(root)
        db.commit()

        failed = scanner._scan_root(root, db, scanner.ScanRules())

        creator = db.query(Creator).filter(Creator.name == "Doomed Creator").one()
        assert failed == {creator.id}, (
            "a creator whose walk raised must be reported so the stale prune skips it"
        )

    def test_unreadable_entries_protect_a_creator_like_a_raised_walk(
        self, db, tmp_path, monkeypatch
    ):
        """A walk that COMPLETES but on an incomplete view of the disk is treated
        exactly like one that raised. Deliberate: a folder whose listing came
        back short may never have been reached, so its models must not look
        deleted this run.
        """
        from app.models import ScanRoot
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)
        _run_pool_inline(monkeypatch)

        creator_dir = tmp_path / "Flaky Creator"
        _stl(creator_dir / "Model A")

        def _short_listing(**kwargs):
            kwargs["read_failures"].append(
                scanner.ReadFailure(path=str(creator_dir), error="permission denied")
            )

        monkeypatch.setattr(scanner, "_walk_for_models", _short_listing)
        monkeypatch.setattr(scanner.grouping, "regroup_creator", lambda _db, _cid: None)
        monkeypatch.setattr(scanner.grouping, "prune_empty_groups", lambda _db: 0)

        root = ScanRoot(path=str(tmp_path), enabled=True)
        db.add(root)
        db.commit()

        failed = scanner._scan_root(root, db, scanner.ScanRules())

        creator = db.query(Creator).filter(Creator.name == "Flaky Creator").one()
        assert failed == {creator.id}, (
            "read failures must protect a creator's models exactly like a raised walk"
        )

    def test_partial_creator_walk_leaves_already_indexed_models_durable(
        self, db, tmp_path, monkeypatch
    ):
        """_index_model commits per model, so a walk that raises partway through
        leaves every model indexed BEFORE the failure durably committed. The
        failure is not all-or-nothing, which is precisely why the prune
        protection above has to exist at all.
        """
        from app.models import ScanRoot
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)
        _run_pool_inline(monkeypatch)

        creator_dir = tmp_path / "Half Creator"
        for name in ("Model A", "Model B", "Model C"):
            _stl(creator_dir / name)

        real_index = scanner._index_model
        indexed: list[str] = []

        def _index_then_fail(folder, creator, db_, *args, **kwargs):
            if len(indexed) >= 2:
                raise OSError("simulated failure after two models")
            indexed.append(folder.name)
            return real_index(folder, creator, db_, *args, **kwargs)

        monkeypatch.setattr(scanner, "_index_model", _index_then_fail)
        monkeypatch.setattr(scanner.grouping, "regroup_creator", lambda _db, _cid: None)
        monkeypatch.setattr(scanner.grouping, "prune_empty_groups", lambda _db: 0)

        root = ScanRoot(path=str(tmp_path), enabled=True)
        db.add(root)
        db.commit()

        failed = scanner._scan_root(root, db, scanner.ScanRules())

        creator = db.query(Creator).filter(Creator.name == "Half Creator").one()
        assert failed == {creator.id}, "the partial walk must still be reported as failed"
        db.expire_all()
        survived = db.query(Model).filter(Model.creator_id == creator.id).count()
        assert survived == 2, (
            "models committed before the failure stay durable — _index_model "
            f"commits per model; expected 2 survivors, got {survived}"
        )

    # -- grouping failure -----------------------------------------------------

    def test_grouping_failure_is_scoped_to_the_failing_creator(
        self, db, tmp_path, monkeypatch
    ):
        """AC1 (grouping failure). STUDIO-396: a creator whose regroup raises no
        longer drags down every creator regrouped before it.

        _scan_root commits `group_db` after EACH creator's regroup, inside the
        same try that catches the failure, so the rollback triggered by creator N
        can only reach creator N's own uncommitted work. Creators regrouped
        earlier are already durable; creators after it are untouched.

        Three creators walked in a pinned order: A succeeds, B raises, C
        succeeds. All three start holding a STALE auto group, so every outcome is
        measured the same way — regroup_creator calls _drop_auto_groups first, so
        a creator whose regroup stuck comes out with its stale group GONE, and a
        creator that was rolled back keeps it.

        Fail-first: with the per-creator commit removed, A's assertion goes red —
        B's rollback undoes A's drop and A's stale group survives the run. C's
        assertion stays green either way, since its drop happens after the
        rollback and is covered by the loop's final commit, which is exactly why
        A is the assertion that measures the fix. Deleting that commit is also
        the mutation this test is pinned against.
        """
        from app.models import ScanRoot, VariantGroup
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)
        _run_pool_inline(monkeypatch)

        names = ("A Creator", "B Creator", "C Creator")
        dirs: dict[str, Path] = {}
        for name in names:
            dirs[name] = tmp_path / name
            _stl(dirs[name] / "Model" / "supported")

        # Every creator starts with a stale AUTO group holding two members. The
        # members matter twice over: prune_empty_groups deletes member-less auto
        # groups after the loop, which would mask both the drops we expect AND
        # the rollback we are measuring — a surviving group has to survive for
        # the right reason.
        creator_ids: dict[str, int] = {}
        stale_ids: dict[str, int] = {}
        for name in names:
            creator = Creator(name=name)
            db.add(creator)
            db.flush()
            stale = VariantGroup(
                creator_id=creator.id, label=f"Stale Auto Group ({name})", source="auto"
            )
            db.add(stale)
            db.flush()
            # no_group=True is what makes regroup_creator take its early-return
            # branch — the ONLY path that calls _drop_auto_groups. Eligible models
            # instead go through materialise_proposals, which REUSES the existing
            # group rather than dropping it, so there would be no drop to roll
            # back and this test would pass without measuring anything.
            for i in (1, 2):
                db.add(Model(
                    name=f"{name} Stale Member {i}",
                    folder_path=str(dirs[name] / f"member-{i}"),
                    creator_id=creator.id,
                    variant_group_id=stale.id,
                    no_group=True,
                ))
            creator_ids[name], stale_ids[name] = creator.id, stale.id
        db.commit()

        # Pin the creator ORDER: _scan_root's regroup loop follows
        # iter_creator_dirs (dict.fromkeys preserves insertion order), and the fix
        # only shows if a creator SUCCEEDS before the one that raises.
        monkeypatch.setattr(
            scanner.layout, "iter_creator_dirs",
            lambda _root, _roles: [(dirs[n], []) for n in names],
        )

        real_regroup = scanner.grouping.regroup_creator
        failing_id = creator_ids["B Creator"]

        def _regroup(session, creator_id):
            # Run the REAL regroup FIRST so B's own _drop_auto_groups is actually
            # flushed before the raise. Raising instead of regrouping would leave
            # B with nothing to roll back, and B's assertion below would pass for
            # free — measuring a drop that never happened rather than one undone.
            real_regroup(session, creator_id)
            if creator_id == failing_id:
                raise RuntimeError("simulated regroup failure on the second creator")

        monkeypatch.setattr(scanner.grouping, "regroup_creator", _regroup)
        monkeypatch.setattr(scanner, "_walk_for_models", lambda **kwargs: None)

        root = ScanRoot(path=str(tmp_path), enabled=True)
        db.add(root)
        db.commit()

        scanner._scan_root(root, db, scanner.ScanRules())

        db.expire_all()
        assert db.get(VariantGroup, stale_ids["A Creator"]) is None, (
            "STUDIO-396: A regrouped cleanly BEFORE B raised, so its "
            "_drop_auto_groups must be durable — B's rollback must not reach it"
        )
        assert db.get(VariantGroup, stale_ids["C Creator"]) is None, (
            "C regrouped cleanly AFTER B raised; the loop must carry on and C's "
            "drop must stick"
        )
        assert db.get(VariantGroup, stale_ids["B Creator"]) is not None, (
            "B's own regroup raised, so B's drop is the one thing the rollback "
            "SHOULD discard — its stale group stands until a later clean run"
        )
        survivors = (
            db.query(Model)
            .filter(Model.variant_group_id == stale_ids["B Creator"])
            .count()
        )
        assert survivors == 2, (
            "B's rolled-back group must still hold its members, or "
            "prune_empty_groups would have swept it as empty and the assertion "
            f"above would pass for the wrong reason; got {survivors}"
        )

    def test_regroup_commit_failure_is_caught_like_a_regroup_failure(
        self, db, tmp_path, monkeypatch
    ):
        """STUDIO-396, second half: the per-creator commit sits INSIDE the try.

        Adding a commit to the loop adds a new way for the loop to raise. SQLite
        has one writer and this scanner already defends against lock transients
        everywhere else (STUDIO-79), so a commit that fails must be handled the
        same as a regroup that fails — logged, rolled back, loop carries on. If
        the commit sat after the try/except instead, that failure would escape
        _scan_root and abort the entire root, which is strictly worse than the
        bug this ticket set out to fix.

        Same three-creator shape as above, except B's regroup SUCCEEDS and its
        commit is what blows up. The rigged commit fires exactly once, on the
        call immediately after B's regroup returns, which is the per-creator
        commit and nothing else.

        Fail-first / mutation: move `group_db.commit()` outside the try and this
        test goes red — the simulated lock propagates out of _scan_root instead
        of being swallowed.
        """
        from app.models import ScanRoot, VariantGroup
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        state = {"boom": False}

        def _rigged_session():
            session = Session()
            real_commit = session.commit

            def _commit():
                if state["boom"]:
                    state["boom"] = False
                    raise RuntimeError("simulated commit failure (SQLite lock)")
                return real_commit()

            session.commit = _commit
            return session

        monkeypatch.setattr(scanner, "SessionLocal", _rigged_session)
        _run_pool_inline(monkeypatch)

        names = ("A Creator", "B Creator", "C Creator")
        dirs: dict[str, Path] = {}
        for name in names:
            dirs[name] = tmp_path / name
            _stl(dirs[name] / "Model" / "supported")

        creator_ids: dict[str, int] = {}
        stale_ids: dict[str, int] = {}
        for name in names:
            creator = Creator(name=name)
            db.add(creator)
            db.flush()
            stale = VariantGroup(
                creator_id=creator.id, label=f"Stale Auto Group ({name})", source="auto"
            )
            db.add(stale)
            db.flush()
            for i in (1, 2):
                db.add(Model(
                    name=f"{name} Stale Member {i}",
                    folder_path=str(dirs[name] / f"member-{i}"),
                    creator_id=creator.id,
                    variant_group_id=stale.id,
                    no_group=True,
                ))
            creator_ids[name], stale_ids[name] = creator.id, stale.id
        db.commit()

        monkeypatch.setattr(
            scanner.layout, "iter_creator_dirs",
            lambda _root, _roles: [(dirs[n], []) for n in names],
        )

        real_regroup = scanner.grouping.regroup_creator
        failing_id = creator_ids["B Creator"]

        def _regroup(session, creator_id):
            # B's regroup SUCCEEDS — including its _drop_auto_groups flush — and
            # arms the next commit instead. That is what makes the commit, and
            # only the commit, the thing under test.
            real_regroup(session, creator_id)
            if creator_id == failing_id:
                state["boom"] = True

        monkeypatch.setattr(scanner.grouping, "regroup_creator", _regroup)
        monkeypatch.setattr(scanner, "_walk_for_models", lambda **kwargs: None)

        root = ScanRoot(path=str(tmp_path), enabled=True)
        db.add(root)
        db.commit()

        # Must not raise. If this line propagates, the commit escaped the try.
        scanner._scan_root(root, db, scanner.ScanRules())

        assert state["boom"] is False, (
            "the rigged commit never fired — the test measured nothing"
        )
        db.expire_all()
        assert db.get(VariantGroup, stale_ids["A Creator"]) is None, (
            "A committed cleanly before B's commit failed and must stay durable"
        )
        assert db.get(VariantGroup, stale_ids["C Creator"]) is None, (
            "the loop must carry on past a commit failure, so C still regroups"
        )
        assert db.get(VariantGroup, stale_ids["B Creator"]) is not None, (
            "B's own work is the only thing the rollback should discard"
        )

    # -- session ownership ----------------------------------------------------

    def test_caller_owned_session_is_left_open_after_a_failure(
        self, db, tmp_path, monkeypatch
    ):
        """AC3. _full_scan(db=caller_db) never rolls back or closes a session it
        does not own — it logs, marks the job ERROR, and hands the session back
        exactly as the failure left it. Synchronous callers (tests, and
        scan_all_roots(db)) therefore inherit any partial state and own the
        cleanup themselves.
        """
        from app.models import ScanRoot

        (tmp_path / "creator").mkdir()
        root = ScanRoot(path=str(tmp_path), enabled=True)
        db.add(root)
        db.commit()

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated scan failure")

        monkeypatch.setattr(scanner, "_scan_root", _boom)
        monkeypatch.setattr(scanner.write_lock, "release_scan", lambda: None)

        # Record close/rollback rather than inferring from usability: a closed
        # SQLAlchemy Session is still usable (it just begins a new transaction),
        # so "did a later query work" would measure nothing and would stay green
        # even if the scanner started closing sessions it does not own.
        closed: list[bool] = []
        rolled_back: list[bool] = []
        real_close, real_rollback = db.close, db.rollback
        monkeypatch.setattr(db, "close", lambda: (closed.append(True), real_close())[1])
        monkeypatch.setattr(db, "rollback", lambda: (rolled_back.append(True), real_rollback())[1])

        job = JobHandle(key="caller-owned-session", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._full_scan(job, db=db)

        assert job.payload()["state"] == "error"
        assert closed == [], "the scanner must not close a session it does not own"
        assert rolled_back == [], (
            "the scanner must not roll back a caller-owned session — the caller "
            "inherits the partial state and owns the cleanup"
        )
        assert db.query(ScanRoot).count() == 1, "session still usable afterwards"

    def test_scanner_owned_session_is_closed_after_a_failure(
        self, db, tmp_path, monkeypatch
    ):
        """AC3, the other half: when _full_scan opens its own session it always
        closes it in the finally, failure or not. Rollback is still never called
        — closing is what discards the uncommitted remainder.
        """
        from app.models import ScanRoot
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        (tmp_path / "creator").mkdir()
        root = ScanRoot(path=str(tmp_path), enabled=True)
        db.add(root)
        db.commit()

        closed: list[bool] = []
        rolled_back: list[bool] = []

        def _tracking_session():
            session = Session()
            real_close, real_rollback = session.close, session.rollback
            # Record rather than assert-by-exception: a closed SQLAlchemy Session
            # is still usable (it simply begins a new transaction), so "did it
            # raise on use" would not measure anything.
            session.close = lambda: (closed.append(True), real_close())[1]
            session.rollback = lambda: (rolled_back.append(True), real_rollback())[1]
            return session

        monkeypatch.setattr(scanner, "SessionLocal", _tracking_session)
        monkeypatch.setattr(
            scanner, "_scan_root",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated scan failure")),
        )
        monkeypatch.setattr(scanner.write_lock, "release_scan", lambda: None)

        job = JobHandle(key="scanner-owned-session", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._full_scan(job)

        assert job.payload()["state"] == "error"
        assert closed == [True], "a scanner-owned session must be closed exactly once"
        assert rolled_back == [], (
            "current behavior: the scanner never rolls back — the close is what "
            "discards uncommitted work"
        )

    # -- prune phases ---------------------------------------------------------

    def test_each_prune_phase_commits_independently(self, db, tmp_path, monkeypatch):
        """AC1 (prune failure). Every prune helper commits internally, so a later
        prune raising does NOT undo an earlier one: the run ends with partial,
        durable deletion rather than an all-or-nothing rollback.

        Fail-first note, and a real limit of this harness: the shared StaticPool
        fixture puts every session on ONE connection, so a flush is visible to
        any other session exactly like a commit. Turning _cascade_delete_models
        commit -> flush alone therefore leaves this test GREEN. It only goes red
        under the compound mutation (that flush PLUS a rollback in _full_scan s
        handler), which is what actually demonstrates the internal commit is
        load-bearing. Do not read a green run here as proof of a COMMIT
        specifically; it proves the deletion is not undone by the later failure.
        """
        from app.models import ScanRoot

        (tmp_path / "creator").mkdir()
        db.add(ScanRoot(path=str(tmp_path), enabled=True))
        creator = make_creator(db, "Prune Creator")
        gone = Model(name="Gone", folder_path=str(tmp_path / "missing"), creator_id=creator.id)
        db.add(gone)
        db.commit()
        gone_id = gone.id

        def _first_prune(_db, *args, **kwargs):
            scanner._cascade_delete_models(_db, [gone_id])
            return 1

        def _second_prune(*args, **kwargs):
            raise RuntimeError("simulated prune failure")

        monkeypatch.setattr(scanner, "_scan_root", lambda *a, **k: set())
        monkeypatch.setattr(scanner, "_prune_stale_models", _first_prune)
        monkeypatch.setattr(scanner, "_prune_stale_paths", _second_prune)
        monkeypatch.setattr(scanner.write_lock, "release_scan", lambda: None)

        job = JobHandle(key="prune-durability", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._full_scan(job, db=db)

        assert job.payload()["state"] == "error"
        db.expire_all()
        assert db.get(Model, gone_id) is None, (
            "an earlier prune's deletion is committed and survives a later prune failing"
        )

    # -- creator rescan: per-model STL rebuild (STUDIO-397) ------------------

    def _rescan_fixture(self, db, tmp_path, monkeypatch, model_names):
        """A creator on disk and in the DB, every model carrying one ORIGINAL
        STL row whose filename is a marker that no rebuild can reproduce.

        A model that the walk re-indexed ends up with `part.stl` and no marker;
        a model the walk never reached still has its marker. That is what makes
        "kept its original rows" distinguishable from "was rebuilt", rather than
        just counting rows.
        """
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)
        monkeypatch.setattr(scanner.ScanRules, "load", classmethod(lambda cls, _db: cls()))
        monkeypatch.setattr(scanner.write_lock, "release_scan", lambda: None)

        creator_dir = tmp_path / "Creator A"
        creator = make_creator(db, "Creator A")
        db.flush()
        model_dirs = []
        for name in model_names:
            d = creator_dir / name
            _stl(d)
            model_dirs.append(d)
            model = Model(name=name, folder_path=str(d), creator_id=creator.id)
            db.add(model)
            db.flush()
            db.add(STLFile(
                model_id=model.id,
                path=str(d / f"{name}-original-marker.stl"),
                filename="original-marker.stl",
            ))
        db.commit()
        monkeypatch.setattr(
            scanner, "_creator_dirs_for", lambda _c, _db: [(creator_dir, [], False)]
        )
        return creator, creator_dir, model_dirs

    @staticmethod
    def _markers(db, creator_id):
        """Model names that still carry their pre-rescan STL row."""
        rows = (
            db.query(Model.name)
            .join(STLFile, STLFile.model_id == Model.id)
            .filter(Model.creator_id == creator_id, STLFile.filename == "original-marker.stl")
            .all()
        )
        return {r.name for r in rows}

    def test_creator_rescan_failure_leaves_unwalked_models_their_stl_rows(
        self, db, tmp_path, monkeypatch
    ):
        """STUDIO-397. The STL wipe is per model now, sharing _index_model's own
        commit, so a walk that raises leaves every model it never reached holding
        its ORIGINAL rows instead of zero.

        This test replaces the STUDIO-233 characterization test that asserted the
        opposite. That test was written to fail exactly here — it recorded the bug
        so this fix would be visible rather than silent.

        Phase 2 is the half that matters: previously the stranded models had no
        STL rows, so the next full scan deleted them as phantoms and took the
        creator row with them. Now they are not phantoms, so nothing is lost.
        """
        from datetime import timedelta
        import os

        from app.models import ScanRoot

        creator, creator_dir, model_dirs = self._rescan_fixture(
            db, tmp_path, monkeypatch, ["Model A", "Model B"]
        )
        creator_id = creator.id

        # === PHASE 1: the rescan crashes before reaching any model ===========
        real_walk = scanner._walk_for_models

        def _boom(**kwargs):
            raise OSError("simulated transient failure (SQLite lock / mount hiccup)")

        monkeypatch.setattr(scanner, "_walk_for_models", _boom)

        job = JobHandle(key="rescan-crash", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._creator_scan(job, creator_id)

        assert job.payload()["state"] == "error"
        db.expire_all()
        assert self._markers(db, creator_id) == {"Model A", "Model B"}, (
            "PHASE 1 - a crashed rescan must leave every un-walked model its "
            "original STL rows; nothing is wiped up front any more"
        )

        # === PHASE 2: the next full scan keeps them ==========================
        monkeypatch.setattr(scanner, "_walk_for_models", real_walk)
        _run_pool_inline(monkeypatch)
        monkeypatch.setattr(scanner, "_prune_stale_models", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "_prune_stale_paths", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "_prune_stale_stl_files", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "_prune_ignored", lambda *a, **k: 0)
        monkeypatch.setattr(scanner, "_prune_slicer_files", lambda *a, **k: None)
        monkeypatch.setattr(scanner.grouping, "regroup_creator", lambda _db, _cid: None)
        monkeypatch.setattr(scanner.grouping, "prune_empty_groups", lambda _db: 0)

        old = utcnow() - timedelta(days=30)
        for d in (creator_dir, *model_dirs, tmp_path):
            os.utime(d, (old.timestamp(), old.timestamp()))
        db.add(ScanRoot(path=str(tmp_path), enabled=True,
                        last_scanned=utcnow() - timedelta(days=1)))
        db.commit()

        job2 = JobHandle(key="next-full-scan", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._full_scan(job2, db=db)

        db.expire_all()
        assert db.query(Model).filter(Model.creator_id == creator_id).count() == 2, (
            "PHASE 2 - the models still have STL rows, so they are not phantoms "
            "and the next full scan leaves them alone"
        )
        assert db.get(Creator, creator_id) is not None, (
            "PHASE 2 - and the creator row survives with them"
        )

    def test_partial_rescan_rebuilds_reached_models_and_preserves_the_rest(
        self, db, tmp_path, monkeypatch
    ):
        """The partial state is the whole point of moving the wipe per model:
        models the walk reached are REBUILT, models it never reached keep their
        ORIGINAL rows, and neither group is left at zero.
        """
        creator, _dir, _dirs = self._rescan_fixture(
            db, tmp_path, monkeypatch, ["Model A", "Model B", "Model C"]
        )
        creator_id = creator.id

        real_index = scanner._index_model
        indexed: list[str] = []

        def _index_then_fail(folder, creator_, db_, *args, **kwargs):
            if len(indexed) >= 1:
                raise OSError("simulated failure after the first model")
            indexed.append(folder.name)
            return real_index(folder, creator_, db_, *args, **kwargs)

        monkeypatch.setattr(scanner, "_index_model", _index_then_fail)

        job = JobHandle(key="partial-rescan", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._creator_scan(job, creator_id)

        assert job.payload()["state"] == "error"
        assert len(indexed) == 1, "exactly one model was re-indexed before the failure"
        db.expire_all()

        rebuilt = indexed[0]
        markers = self._markers(db, creator_id)
        assert rebuilt not in markers, (
            f"{rebuilt} was re-indexed, so its original marker row is gone"
        )
        assert markers == {"Model A", "Model B", "Model C"} - {rebuilt}, (
            "every model the walk never reached keeps its original rows"
        )
        for model in db.query(Model).filter(Model.creator_id == creator_id):
            count = db.query(STLFile).filter(STLFile.model_id == model.id).count()
            assert count > 0, f"{model.name} must never be left with zero STL rows"

    def test_rescan_clears_stl_rows_for_models_whose_folder_is_gone(
        self, db, tmp_path, monkeypatch
    ):
        """The gap the per-model wipe opens, and the sweep that closes it.

        A per-model rebuild only reaches models the walk visits, so a model whose
        folder was renamed or deleted would keep stale rows and stop looking like
        a phantom — something the old bulk wipe handled as a side effect. The
        creator-scoped sweep restores that, and the phantom prune then removes the
        model as it always did.

        Fail-first note: this is a REGRESSION GUARD, not a fix-prover, and it is
        the one test here that passes against the pre-fix code too -- the old bulk
        wipe cleared these rows as a side effect. Its mutation is therefore not
        'remove the fix' but 'remove the sweep from the fix', which was verified
        RED. Read a green run as 'the fix did not open this gap', not as evidence
        of the fix itself.
        """
        creator, creator_dir, model_dirs = self._rescan_fixture(
            db, tmp_path, monkeypatch, ["Model A", "Gone Model"]
        )
        creator_id = creator.id

        # Delete one model's folder from disk, leaving its rows behind.
        import shutil
        shutil.rmtree(model_dirs[1])

        job = JobHandle(key="rescan-missing-folder", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._creator_scan(job, creator_id)

        assert job.payload()["state"] == "done"
        db.expire_all()
        names = {m.name for m in db.query(Model).filter(Model.creator_id == creator_id)}
        assert "Gone Model" not in names, (
            "a model whose folder is gone has its stale STL rows cleared and is "
            "then removed by the phantom prune, exactly as before the fix"
        )
        assert "Model A" in names, "the surviving model is untouched"

    def test_rescan_clears_nothing_when_the_volume_looks_detached(
        self, db, tmp_path, monkeypatch
    ):
        """The sweep must not mistake a dropped mount for deleted folders.

        A detached volume makes every path beneath it report missing, and an
        unmounted mountpoint presents as an EMPTY directory rather than a missing
        one — so `exists()` alone is not enough. If no walked directory is online
        (present and non-empty), the sweep clears nothing and the creator keeps
        its whole STL index.

        The bulk pre-walk wipe this replaced had no such guard: it would have
        emptied the creator's STL rows in exactly this situation. This is
        strictly safer than the code it replaces, not merely equivalent.
        """
        import shutil

        creator, creator_dir, model_dirs = self._rescan_fixture(
            db, tmp_path, monkeypatch, ["Model A", "Model B"]
        )
        creator_id = creator.id

        # Volume dropped: the creator folder is still there but empty, and every
        # model folder beneath it has vanished.
        for d in model_dirs:
            shutil.rmtree(d)
        assert creator_dir.exists() and not any(creator_dir.iterdir())

        job = JobHandle(key="rescan-detached", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._creator_scan(job, creator_id)

        db.expire_all()
        assert self._markers(db, creator_id) == {"Model A", "Model B"}, (
            "an offline-looking volume must leave every STL row in place"
        )
        assert db.query(Model).filter(Model.creator_id == creator_id).count() == 2, (
            "and the models therefore survive the phantom prune"
        )

    def test_prune_phantoms_honours_protected_creator_ids(self, db, tmp_path):
        """_prune_phantoms was the only destructive prune with no protection.
        Defensive symmetry with the other three rather than the STUDIO-397 fix
        itself — with the per-model rebuild a stranded creator is not a phantom
        in the first place.
        """
        protected = make_creator(db, "Protected")
        other = make_creator(db, "Other")
        db.flush()
        db.add(Model(name="No Files", folder_path=str(tmp_path / "a"), creator_id=protected.id))
        # Two models with STL rows so the 50% cap cannot mask the result.
        for i in (1, 2):
            m = Model(name=f"Has Files {i}", folder_path=str(tmp_path / f"b{i}"), creator_id=other.id)
            db.add(m)
            db.flush()
            db.add(STLFile(model_id=m.id, path=str(tmp_path / f"b{i}" / "p.stl"), filename="p.stl"))
        db.commit()

        removed = scanner._prune_phantoms(db, protected_creator_ids={protected.id})

        assert removed == 0, "a protected creator's phantom models are left alone"
        assert db.query(Model).filter(Model.creator_id == protected.id).count() == 1

    # -- STUDIO-398: rescan reconciles rather than wipes ---------------------

    def _model_with_user_metadata(self, db, tmp_path, monkeypatch):
        """A creator with one model whose two STL rows carry user-owned values.

        part_name, part_type and sup_of_id are set ONLY by user actions in
        routers/models.py — the scanner never re-derives them, so anything that
        deletes and re-adds a row loses them silently.
        """
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)
        monkeypatch.setattr(scanner.ScanRules, "load", classmethod(lambda cls, _db: cls()))
        monkeypatch.setattr(scanner.write_lock, "release_scan", lambda: None)
        monkeypatch.setattr(scanner.grouping, "regroup_creator", lambda _db, _cid: None)
        monkeypatch.setattr(scanner.grouping, "prune_empty_groups", lambda _db: 0)

        creator_dir = tmp_path / "Creator"
        model_dir = creator_dir / "Model A"
        _stl(model_dir, "base.stl")
        _stl(model_dir, "base_sup.stl")

        creator = make_creator(db, "Creator")
        db.flush()
        model = Model(name="Model A", folder_path=str(model_dir), creator_id=creator.id)
        db.add(model)
        db.flush()
        base = STLFile(model_id=model.id, path=str(model_dir / "base.stl"),
                       filename="base.stl", part_name="Hand-Renamed Base", part_type="body")
        sup = STLFile(model_id=model.id, path=str(model_dir / "base_sup.stl"),
                      filename="base_sup.stl", part_name="Hand-Renamed Sup")
        db.add(base)
        db.add(sup)
        db.flush()
        sup.sup_of_id = base.id
        db.commit()

        monkeypatch.setattr(
            scanner, "_creator_dirs_for", lambda _c, _db: [(creator_dir, [], False)]
        )
        return creator.id, model_dir, base.id, sup.id

    def test_successful_rescan_preserves_user_assigned_stl_metadata(
        self, db, tmp_path, monkeypatch
    ):
        """STUDIO-398. A rescan must not touch rows whose file is still there.

        This is a SUCCESS-path test. Before the reconcile, a completely normal
        rescan reset part_name to its auto-derived value ("Base") and cleared
        part_type and sup_of_id, because deleting the rows first made every
        re-insert a "first discovery" and bypassed _index_stl_files'
        skip-if-present branch.

        Row identity is asserted too, not just the values: sup_of_id is a foreign
        key to stl_files.id, so a row that comes back with a new id breaks the
        relationship even if every column looks right. SQLite reuses freed ids,
        which is exactly how a delete-and-re-add can appear to preserve identity
        while having destroyed it.
        """
        creator_id, _model_dir, base_id, sup_id = self._model_with_user_metadata(
            db, tmp_path, monkeypatch
        )

        job = JobHandle(key="rescan-metadata", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._creator_scan(job, creator_id)

        assert job.payload()["state"] == "done"
        db.expire_all()
        base = db.get(STLFile, base_id)
        sup = db.get(STLFile, sup_id)

        assert base is not None and sup is not None, "the rows must survive as themselves"
        assert base.part_name == "Hand-Renamed Base", (
            "a manual rename must survive a rescan — _index_stl_files derives "
            "part_name once at first discovery and never again"
        )
        assert base.part_type == "body", "user-assigned part_type must survive a rescan"
        assert sup.sup_of_id == base_id, (
            "the explicit sup relationship must survive, and must still point at "
            "the same row"
        )

    def test_rescan_still_drops_rows_whose_file_is_gone(self, db, tmp_path, monkeypatch):
        """The staleness half the wipe used to provide. _index_stl_files is
        additive-only and never removes a row whose file vanished, so the
        reconcile has to — otherwise deleted files linger in the index forever.
        """
        creator_id, model_dir, base_id, sup_id = self._model_with_user_metadata(
            db, tmp_path, monkeypatch
        )
        (model_dir / "base_sup.stl").unlink()

        job = JobHandle(key="rescan-stale", _lock=threading.Lock(), state=JobState.RUNNING)
        scanner._creator_scan(job, creator_id)

        assert job.payload()["state"] == "done"
        db.expire_all()
        assert db.get(STLFile, sup_id) is None, (
            "a row whose file is gone from disk is dropped by the reconcile"
        )
        surviving = db.get(STLFile, base_id)
        assert surviving is not None and surviving.part_type == "body", (
            "and its neighbour is untouched, metadata included"
        )

    def test_rescan_issues_no_stl_writes_when_the_model_is_unchanged(
        self, db, tmp_path, monkeypatch
    ):
        """The efficiency half: an unchanged model costs ZERO stl_files writes,
        where the wipe cost 2N (N deletes plus N re-inserts) on every rescan.

        This counts the SQL actually issued rather than comparing rows before and
        after. The obvious version of this test — diffing {id: path} — is useless
        here, and was written that way first: SQLite reuses freed row ids, so a
        full delete-and-re-add hands back the same ids against the same paths and
        the comparison passes. It was verified GREEN against the pre-fix wipe,
        which is exactly the wrong answer. Counting statements is the only form
        of this test that can tell the two apart.
        """
        from sqlalchemy import event

        creator_id, _model_dir, _base_id, _sup_id = self._model_with_user_metadata(
            db, tmp_path, monkeypatch
        )

        writes: list[str] = []

        # Match writes that TARGET stl_files, not any statement that merely
        # mentions it: the pre-scan needs_review clear is an UPDATE on `models`
        # whose subquery reads stl_files, and a looser substring check counts it
        # as a write. It is the only false positive here, and it is the reason
        # this matches on the statement's opening clause instead.
        targets = ("insert into stl_files", "delete from stl_files", "update stl_files")

        def _record(conn, cursor, statement, params, context, executemany):
            normalized = " ".join(statement.strip().lower().split())
            if normalized.startswith(targets):
                writes.append(statement.strip().split("\n")[0])

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", _record)
        try:
            job = JobHandle(key="rescan-noop", _lock=threading.Lock(), state=JobState.RUNNING)
            scanner._creator_scan(job, creator_id)
        finally:
            event.remove(engine, "before_cursor_execute", _record)

        assert job.payload()["state"] == "done"
        assert writes == [], (
            "an unchanged model must issue no stl_files writes at all; got:\n  "
            + "\n  ".join(writes)
        )

    def test_a_deeper_model_still_claims_a_path_its_ancestor_owns(self, db, tmp_path):
        """The risk the reconcile introduces, covered directly.

        The wipe made row ownership trivially correct: delete everything, re-add
        under whoever walks it. With a reconcile the file still exists, so its row
        is not dropped, and correctness now rests on _index_stl_files' transfer
        branch — which was previously a safety net and is now load-bearing.

        A deeper (more specific) model must take the row in place, keeping the
        user metadata on it.

        Fail-first note: this is a REGRESSION GUARD, not a fix-prover. It passes
        against the pre-STUDIO-398 wipe too, because it exercises
        _index_stl_files' transfer branch directly and that branch predates this
        change. It is here because the reconcile PROMOTES that branch from a
        safety net to the mechanism correctness depends on, so it now needs
        coverage of its own. Read a green run as "the reconcile did not break
        ownership transfer", not as evidence of the reconcile itself.
        """
        creator = make_creator(db, "Creator")
        db.flush()
        parent_dir = tmp_path / "Creator" / "Product"
        child_dir = parent_dir / "Supported"
        _stl(child_dir, "part.stl")

        parent = Model(name="Product", folder_path=str(parent_dir), creator_id=creator.id)
        child = Model(name="Supported", folder_path=str(child_dir), creator_id=creator.id)
        db.add(parent)
        db.add(child)
        db.flush()
        row = STLFile(model_id=parent.id, path=str(child_dir / "part.stl"),
                      filename="part.stl", part_name="Hand-Renamed", part_type="body")
        db.add(row)
        db.commit()
        row_id, child_id = row.id, child.id

        scanner._index_stl_files(child, child_dir, db)
        db.commit()

        db.expire_all()
        moved = db.get(STLFile, row_id)
        assert moved is not None and moved.model_id == child_id, (
            "the deeper model claims the path in place rather than a duplicate "
            "row being inserted"
        )
        assert moved.part_name == "Hand-Renamed" and moved.part_type == "body", (
            "and the transfer keeps the user-owned metadata on the row"
        )

    def test_an_ancestor_model_never_steals_a_path_back_from_its_child(
        self, db, tmp_path
    ):
        """The other direction of the same branch: a parent walking over a path
        its child legitimately owns must leave it alone. Only a strictly deeper
        model may claim a row.

        Same regression-guard caveat as the test above: green against the
        pre-STUDIO-398 wipe as well, and deliberately so.
        """
        creator = make_creator(db, "Creator")
        db.flush()
        parent_dir = tmp_path / "Creator" / "Product"
        child_dir = parent_dir / "Supported"
        _stl(child_dir, "part.stl")

        parent = Model(name="Product", folder_path=str(parent_dir), creator_id=creator.id)
        child = Model(name="Supported", folder_path=str(child_dir), creator_id=creator.id)
        db.add(parent)
        db.add(child)
        db.flush()
        row = STLFile(model_id=child.id, path=str(child_dir / "part.stl"), filename="part.stl")
        db.add(row)
        db.commit()
        row_id, child_id = row.id, child.id

        # The parent's rglob reaches into the child's folder.
        scanner._index_stl_files(parent, parent_dir, db)
        db.commit()

        db.expire_all()
        assert db.get(STLFile, row_id).model_id == child_id, (
            "a parent must never take a path back from the deeper model that owns it"
        )

    # -- split_pack -----------------------------------------------------------

    def test_split_pack_rewalk_failure_leaves_a_partial_split_durable(
        self, db, tmp_path, monkeypatch
    ):
        """split_pack commits its PackOverride and the destructive delete of the
        collapsed model BEFORE re-walking, and _index_model commits each child as
        it goes. A re-walk that raises therefore leaves a partially split,
        durable result: the original model is gone for good, the override stands,
        and however many children were indexed before the failure remain. The
        error is reported in the return value only — nothing is rolled back.

        Same harness caveat as test_each_prune_phase_commits_independently: on
        the shared-connection fixture this only goes red under a compound
        mutation (both _cascade_delete_models and _index_model commit -> flush,
        plus a rollback in split_pack s handler). Verified red that way.
        """
        from app.models import PackOverride
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)
        monkeypatch.setattr(scanner.write_lock, "release_scan", lambda: None)
        monkeypatch.setattr(scanner.write_lock, "try_acquire_for_scan", lambda: True)

        creator_dir = tmp_path / "Creator"
        pack = creator_dir / "Sinister Six"
        for child in ("Electro", "Sandman", "Spiderman"):
            _stl(pack / child / "supported")

        setup = Session()
        creator = Creator(name="Creator")
        setup.add(creator)
        setup.flush()
        collapsed = Model(name="Sinister Six", folder_path=str(pack), creator_id=creator.id)
        setup.add(collapsed)
        setup.commit()
        collapsed_id = collapsed.id
        setup.close()

        real_index = scanner._index_model
        indexed: list[str] = []

        def _index_then_fail(folder, creator_, db_, *args, **kwargs):
            if len(indexed) >= 1:
                raise OSError("simulated failure partway through the re-walk")
            indexed.append(folder.name)
            return real_index(folder, creator_, db_, *args, **kwargs)

        monkeypatch.setattr(scanner, "_index_model", _index_then_fail)

        result = scanner.split_pack(collapsed_id)

        assert result["ok"] is False, "the caller is told the split failed"
        check = Session()
        try:
            # Identity is checked by FOLDER PATH, not by id: split_pack expunges
            # the deleted model precisely because SQLite reuses freed row ids, so
            # get(Model, collapsed_id) can legitimately return one of the newly
            # indexed children instead of None.
            assert check.query(Model).filter(
                Model.folder_path == str(pack)
            ).count() == 0, (
                "the collapsed model was deleted and committed before the re-walk — "
                "the failure does not bring it back"
            )
            assert check.query(PackOverride).filter(
                PackOverride.path == str(pack)
            ).count() == 1, (
                "the PackOverride is committed up front and survives the failure, so "
                "a later rescan still treats this folder as a pack boundary"
            )
            assert len(indexed) == 1, "exactly one child was indexed before the failure"
            assert check.query(Model).filter(Model.folder_path.like(f"{pack}%")).count() == 1, (
                "that child is durable — _index_model commits per model, so the run "
                "ends with a partial split rather than an all-or-nothing rollback"
            )
        finally:
            check.close()

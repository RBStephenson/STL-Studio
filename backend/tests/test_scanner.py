"""
Integration tests for the filesystem scanner's leaf detection and variant
grouping — the subsystem that has historically harboured the subtlest bugs.

Each test lays out a fake library under tmp_path, runs the real walk, and
asserts what got indexed (and how it grouped).
"""
from pathlib import Path

from app.models import Creator, Model, STLFile
from app.services import scanner
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


def _walk(db, creator: Creator, creator_dir: Path) -> None:
    scanner._walk_for_models(
        folder=creator_dir, creator=creator, db=db,
        creator_boundary=creator_dir, character=None,
        stl_cache={}, last_scanned=None,
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

    def test_model_directly_under_creator_has_no_character(self, db, tmp_path):
        """A standalone product directly under the creator needs no grouping."""
        creator_dir = tmp_path / "Creator"
        _stl(creator_dir / "Solo Dragon")
        creator = make_creator(db, "Creator")

        _walk(db, creator, creator_dir)

        models = _models(db, creator)
        assert len(models) == 1
        assert models[0].character is None


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

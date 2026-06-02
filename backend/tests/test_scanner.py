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

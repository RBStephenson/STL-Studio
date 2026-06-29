"""Variant-grouping proposal engine (#615). Exercises the blended signals
(file_hash / filename / name) and the manual-group lock."""
from app.models import Model, STLFile, VariantGroup
from app.services import grouping
from tests.conftest import make_creator, make_model, make_stl_file


def _stl(db, model, filename, file_hash=None):
    f = make_stl_file(db, model, filename=filename, path=f"/tmp/{model.id}/{filename}")
    if file_hash:
        f.file_hash = file_hash
    return f


def _groups(db, creator):
    return db.query(VariantGroup).filter_by(creator_id=creator.id).all()


def _run(db, creator):
    grouping.regroup_creator(db, creator.id)
    db.flush()
    db.expire_all()


class TestNameSignal:
    def test_shared_name_key_groups(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin Supported")
        b = make_model(db, creator, name="Goblin Unsupported")
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id}
        assert groups[0].reason == "name: Goblin"
        assert groups[0].confidence == 0.6

    def test_distinct_products_stay_separate(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="Goblin King")
        make_model(db, creator, name="Dragon Lord")
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []


class TestFilenameSignal:
    def test_filename_overlap_groups_differently_named(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        db.flush()
        for fn in ("body.stl", "head.stl", "base.stl"):
            _stl(db, a, fn)
            _stl(db, b, fn)
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert groups[0].reason == "shared STL file names"
        assert {m.id for m in groups[0].models} == {a.id, b.id}

    def test_low_overlap_does_not_group(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        db.flush()
        _stl(db, a, "body.stl"); _stl(db, a, "head.stl"); _stl(db, a, "arm.stl")
        _stl(db, b, "body.stl"); _stl(db, b, "wheel.stl"); _stl(db, b, "turret.stl")
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []


class TestHashSignal:
    def test_shared_hash_groups_and_wins_reason(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        db.flush()
        _stl(db, a, "x.stl", file_hash="deadbeef")
        _stl(db, b, "y.stl", file_hash="deadbeef")
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert groups[0].reason == "shared mesh files"
        assert groups[0].confidence == 0.9

    def test_ubiquitous_hash_does_not_chain(self, db):
        # A hash shared by > cap models is treated as a common part and ignored.
        creator = make_creator(db)
        ms = [make_model(db, creator, name=f"M{i}") for i in range(9)]
        db.flush()
        for m in ms:
            _stl(db, m, f"part{m.id}.stl", file_hash="commonbase")
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []


class TestManualLock:
    def test_manual_group_preserved_and_members_not_reassigned(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Hero A")
        b = make_model(db, creator, name="Hero B")
        db.flush()
        manual = VariantGroup(creator_id=creator.id, label="My Group", source="manual")
        db.add(manual)
        db.flush()
        a.variant_group_id = manual.id
        b.variant_group_id = manual.id
        db.flush()

        _run(db, creator)

        db.refresh(manual)
        assert manual.source == "manual"
        assert {m.id for m in manual.models} == {a.id, b.id}

    def test_auto_group_rebuilt_each_run(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="Goblin Supported")
        make_model(db, creator, name="Goblin Unsupported")
        db.flush()

        _run(db, creator)
        _run(db, creator)  # rerun must not duplicate

        assert len(_groups(db, creator)) == 1


class TestOverrideRespected:
    def test_group_override_excludes_model_from_proposals(self, db):
        from app.models import GroupOverride
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin Supported")
        b = make_model(db, creator, name="Goblin Unsupported")
        db.flush()
        # User explicitly ungrouped `a` (sticky GroupOverride, e.g. remove-from-group).
        db.add(GroupOverride(path=a.folder_path, character=None))
        db.flush()

        _run(db, creator)

        db.refresh(a)
        assert a.variant_group_id is None  # not re-proposed into a group
        # b alone is a singleton → no group either
        assert _groups(db, creator) == []


class TestSubtreeStrategy:
    def test_off_strategy_prevents_grouping(self, db):
        from app.models import GroupingStrategy
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin Supported")
        b = make_model(db, creator, name="Goblin Unsupported")
        db.flush()
        # off on the common parent folder of a + b
        parent = a.folder_path.rsplit("/", 1)[0]
        db.add(GroupingStrategy(path=parent, strategy="off"))
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []
        db.refresh(a); db.refresh(b)
        assert a.variant_group_id is None and b.variant_group_id is None

    def test_nearest_ancestor_auto_overrides_outer_off(self, db):
        from app.models import GroupingStrategy
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin Supported")
        b = make_model(db, creator, name="Goblin Unsupported")
        # Put both under a deeper subtree we can target with a closer "auto".
        a.folder_path = "/lib/Creator/sub/Goblin Supported"
        b.folder_path = "/lib/Creator/sub/Goblin Unsupported"
        db.flush()
        db.add(GroupingStrategy(path="/lib/Creator", strategy="off"))
        db.add(GroupingStrategy(path="/lib/Creator/sub", strategy="auto"))
        db.flush()

        _run(db, creator)

        # The closer "auto" wins → they group despite the outer "off".
        assert len(_groups(db, creator)) == 1


class TestFilenameHardening:
    def test_generic_shared_filename_does_not_group(self, db):
        # Two unrelated sculpts share only generic part names → must not group (#639).
        creator = make_creator(db)
        a = make_model(db, creator, name="Dragon")
        b = make_model(db, creator, name="Wizard")
        db.flush()
        for fn in ("body.stl", "base.stl"):
            _stl(db, a, fn); _stl(db, b, fn)
        _stl(db, a, "dragon_wings.stl"); _stl(db, b, "wizard_staff.stl")
        # Make body/base generic by spreading them across many models.
        for i in range(9):
            m = make_model(db, creator, name=f"Filler{i}")
            db.flush()
            _stl(db, m, "body.stl"); _stl(db, m, "base.stl")
        db.flush()

        _run(db, creator)

        db.refresh(a); db.refresh(b)
        assert a.variant_group_id is None or a.variant_group_id != b.variant_group_id

    def test_single_shared_distinctive_file_not_enough(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        db.flush()
        _stl(db, a, "shared.stl"); _stl(db, a, "a1.stl"); _stl(db, a, "a2.stl")
        _stl(db, b, "shared.stl"); _stl(db, b, "b1.stl"); _stl(db, b, "b2.stl")
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []  # 1 shared distinct file < min


class TestStructuralOnlyNotGrouped:
    def test_structural_named_members_not_grouped(self, db):
        # Folders literally named supported/unsupported that share files must not
        # become a junk-labeled "supported" group (#639).
        creator = make_creator(db)
        a = make_model(db, creator, name="supported")
        b = make_model(db, creator, name="unsupported")
        db.flush()
        for fn in ("body.stl", "head.stl", "arm.stl"):
            _stl(db, a, fn); _stl(db, b, fn)
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []
        db.refresh(a); db.refresh(b)
        assert a.variant_group_id is None and b.variant_group_id is None


class TestPruneEmptyGroups:
    def test_prunes_empty_auto_group(self, db):
        creator = make_creator(db)
        g = VariantGroup(creator_id=creator.id, label="Orphan", source="auto")
        db.add(g); db.flush()
        n = grouping.prune_empty_groups(db)
        assert n == 1
        assert db.query(VariantGroup).count() == 0

    def test_keeps_nonempty_and_manual_empty(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A"); b = make_model(db, creator, name="B")
        full = VariantGroup(creator_id=creator.id, label="Full", source="auto")
        manual_empty = VariantGroup(creator_id=creator.id, label="Manual", source="manual")
        db.add_all([full, manual_empty]); db.flush()
        a.variant_group_id = full.id; b.variant_group_id = full.id
        db.flush()

        grouping.prune_empty_groups(db)

        labels = {g.label for g in db.query(VariantGroup)}
        assert labels == {"Full", "Manual"}


class TestRep:
    def test_rep_prefers_is_group_rep(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="Goblin Supported")
        rep = make_model(db, creator, name="Goblin Unsupported")
        rep.is_group_rep = True
        db.flush()

        _run(db, creator)

        assert _groups(db, creator)[0].rep_model_id == rep.id

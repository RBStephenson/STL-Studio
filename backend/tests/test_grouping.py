"""Variant-grouping proposal engine (#615). Exercises the blended signals
(file_hash / filename / name) and the manual-group lock."""
from app.models import GroupOverride, Model, STLFile, VariantGroup
from app.services import grouping
from tests.conftest import make_creator, make_model, make_stl_file


def _override(db, model, character):
    o = GroupOverride(path=model.folder_path, character=character)
    db.add(o)
    db.flush()
    return o


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


class TestOverrideEngineExclusionGolden678:
    """#678 Phase 2 — flip of the Phase 0 golden: the engine now feeds a user
    character override in as a forced grouping signal (strongest, like a manual
    pin) instead of excluding the model outright. Reviewed, deliberate flip —
    see git history for the pre-Phase-2 exclusion behavior this replaces."""

    def test_user_character_override_is_now_auto_grouped(self, db):
        from app.models import GroupOverride
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin Supported")
        b = make_model(db, creator, name="Goblin Unsupported")
        db.flush()
        db.add(GroupOverride(path=a.folder_path, character="Goblin"))
        db.add(GroupOverride(path=b.folder_path, character="Goblin"))
        db.flush()

        _run(db, creator)

        db.refresh(a); db.refresh(b)
        assert a.variant_group_id is not None
        assert a.variant_group_id == b.variant_group_id
        groups = _groups(db, creator)
        assert len(groups) == 1
        assert groups[0].source == "auto"
        assert groups[0].label == "Goblin"
        assert groups[0].reason == "user character: Goblin"
        assert groups[0].confidence == 0.95


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


class TestBackfillManualGroupsFromOverrides:
    """#678 Phase 1: migrate user character overrides into durable manual groups."""

    def test_override_trio_becomes_manual_group(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin A")
        b = make_model(db, creator, name="Goblin B")
        c = make_model(db, creator, name="Goblin C")
        _override(db, a, "Goblin King")
        _override(db, b, "Goblin King")
        _override(db, c, "Goblin King")
        db.flush()

        created = grouping.backfill_manual_groups_from_overrides(db)

        assert created == 1
        groups = db.query(VariantGroup).filter_by(creator_id=creator.id).all()
        assert len(groups) == 1
        group = groups[0]
        assert group.source == "manual"
        assert group.label == "Goblin King"
        assert {a.id, b.id, c.id} == {m.id for m in group.models}

    def test_rep_prefers_is_group_rep(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin A")
        rep = make_model(db, creator, name="Goblin B")
        rep.is_group_rep = True
        _override(db, a, "Goblin King")
        _override(db, rep, "Goblin King")
        db.flush()

        grouping.backfill_manual_groups_from_overrides(db)

        group = db.query(VariantGroup).filter_by(creator_id=creator.id).one()
        assert group.rep_model_id == rep.id

    def test_two_characters_become_two_groups(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin A")
        b = make_model(db, creator, name="Goblin B")
        c = make_model(db, creator, name="Dragon A")
        d = make_model(db, creator, name="Dragon B")
        _override(db, a, "Goblin King")
        _override(db, b, "Goblin King")
        _override(db, c, "Dragon Lord")
        _override(db, d, "Dragon Lord")
        db.flush()

        created = grouping.backfill_manual_groups_from_overrides(db)

        assert created == 2
        labels = {g.label for g in db.query(VariantGroup).filter_by(creator_id=creator.id)}
        assert labels == {"Goblin King", "Dragon Lord"}

    def test_singleton_override_not_grouped(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin A")
        _override(db, a, "Goblin King")
        db.flush()

        created = grouping.backfill_manual_groups_from_overrides(db)

        assert created == 0
        assert db.query(VariantGroup).count() == 0
        db.refresh(a)
        assert a.variant_group_id is None

    def test_explicit_ungroup_override_untouched(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin A")
        b = make_model(db, creator, name="Goblin B")
        _override(db, a, None)
        _override(db, b, None)
        db.flush()

        created = grouping.backfill_manual_groups_from_overrides(db)

        assert created == 0
        assert db.query(VariantGroup).count() == 0

    def test_already_grouped_model_skipped(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin A")
        b = make_model(db, creator, name="Goblin B")
        existing = VariantGroup(creator_id=creator.id, label="Existing", source="auto")
        db.add(existing)
        db.flush()
        a.variant_group_id = existing.id
        _override(db, a, "Goblin King")
        _override(db, b, "Goblin King")
        db.flush()

        created = grouping.backfill_manual_groups_from_overrides(db)

        assert created == 0
        db.refresh(a)
        assert a.variant_group_id == existing.id
        db.refresh(b)
        assert b.variant_group_id is None

    def test_scanner_derived_character_without_override_not_migrated(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="Goblin A", character="Goblin")
        make_model(db, creator, name="Goblin B", character="Goblin")
        db.flush()

        created = grouping.backfill_manual_groups_from_overrides(db)

        assert created == 0
        assert db.query(VariantGroup).count() == 0

    def test_idempotent_rerun_creates_nothing(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin A")
        b = make_model(db, creator, name="Goblin B")
        _override(db, a, "Goblin King")
        _override(db, b, "Goblin King")
        db.flush()

        first = grouping.backfill_manual_groups_from_overrides(db)
        second = grouping.backfill_manual_groups_from_overrides(db)

        assert first == 1
        assert second == 0
        assert db.query(VariantGroup).filter_by(creator_id=creator.id).count() == 1


class TestEngineOwnsOverrides:
    """#678 Phase 2: user character overrides become a forced grouping signal
    (stronger than hash/filename/name), so their durable group survives rescans
    without the read-path `ch:` fallback."""

    def test_override_forces_group_across_distinct_names(self, db):
        # No shared name key, no shared files — only the override ties them.
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        db.flush()
        db.add(GroupOverride(path=a.folder_path, character="Hero"))
        db.add(GroupOverride(path=b.folder_path, character="Hero"))
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert groups[0].label == "Hero"
        assert groups[0].reason == "user character: Hero"
        assert {m.id for m in groups[0].models} == {a.id, b.id}

    def test_override_wins_over_hash_signal_in_reason(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        db.flush()
        _stl(db, a, "x.stl", file_hash="deadbeef")
        _stl(db, b, "y.stl", file_hash="deadbeef")
        db.add(GroupOverride(path=a.folder_path, character="Hero"))
        db.add(GroupOverride(path=b.folder_path, character="Hero"))
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert groups[0].reason == "user character: Hero"
        assert groups[0].confidence == 0.95

    def test_singleton_override_stays_ungrouped(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        db.flush()
        db.add(GroupOverride(path=a.folder_path, character="Hero"))
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []
        db.refresh(a)
        assert a.variant_group_id is None

    def test_explicit_ungroup_still_excluded_when_others_have_char_override(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        db.flush()
        db.add(GroupOverride(path=a.folder_path, character=None))
        db.add(GroupOverride(path=b.folder_path, character="Hero"))
        db.flush()

        _run(db, creator)

        db.refresh(a)
        assert a.variant_group_id is None
        assert _groups(db, creator) == []  # b alone is a singleton

    def test_rerun_does_not_duplicate_override_group(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        db.flush()
        db.add(GroupOverride(path=a.folder_path, character="Hero"))
        db.add(GroupOverride(path=b.folder_path, character="Hero"))
        db.flush()

        _run(db, creator)
        _run(db, creator)

        assert len(_groups(db, creator)) == 1

    def test_manual_group_from_phase1_backfill_untouched_by_engine(self, db):
        # A model already durably grouped (e.g. by the Phase 1 backfill) as
        # source="manual" must not be re-proposed or merged by the engine, even
        # though its GroupOverride row is still present.
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        db.flush()
        manual = VariantGroup(creator_id=creator.id, label="Hero", source="manual")
        db.add(manual)
        db.flush()
        a.variant_group_id = manual.id
        b.variant_group_id = manual.id
        db.add(GroupOverride(path=a.folder_path, character="Hero"))
        db.add(GroupOverride(path=b.folder_path, character="Hero"))
        db.flush()

        _run(db, creator)

        db.refresh(manual)
        assert manual.source == "manual"
        assert {m.id for m in manual.models} == {a.id, b.id}
        assert _groups(db, creator) == [manual]

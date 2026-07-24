"""Variant-grouping proposal engine (#615). Exercises the blended signals
(file_hash / filename / name) and the manual-group lock."""
from app.models import AppSetting, VariantGroup
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


def _enable_hierarchy(db):
    db.merge(AppSetting(key="hierarchy_variant_grouping_enabled", value=True))
    db.flush()


class TestHierarchySignal:
    def test_same_character_envelope_groups_different_names(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Supported Files")
        b = make_model(db, creator, name="Alternate Cut")
        a.character = b.character = "Ada Wong"
        _enable_hierarchy(db)

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id}
        assert groups[0].label == "Ada Wong"
        assert groups[0].reason == "same product hierarchy"

    def test_conflicting_envelopes_block_shared_hash_merge(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Supported")
        b = make_model(db, creator, name="Supported Copy")
        a.character = "Ada Wong"
        b.character = "Leon Kennedy"
        db.flush()
        _stl(db, a, "body.stl", file_hash="shared-base")
        _stl(db, b, "body.stl", file_hash="shared-base")
        _enable_hierarchy(db)

        _run(db, creator)

        assert _groups(db, creator) == []

    def test_disabled_flag_keeps_existing_hash_behavior(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        a.character = "Ada Wong"
        b.character = "Leon Kennedy"
        db.flush()
        _stl(db, a, "a.stl", file_hash="same-mesh")
        _stl(db, b, "b.stl", file_hash="same-mesh")

        _run(db, creator)

        assert len(_groups(db, creator)) == 1

    def test_ambiguous_middle_cannot_bridge_conflicting_envelopes(self, db):
        creator = make_creator(db)
        ada = make_model(db, creator, name="Ada")
        bridge = make_model(db, creator, name="Bridge")
        leon = make_model(db, creator, name="Leon")
        ada.character = "Ada Wong"
        bridge.character = None
        leon.character = "Leon Kennedy"
        db.flush()
        _stl(db, ada, "ada.stl", file_hash="left")
        _stl(db, bridge, "bridge-left.stl", file_hash="left")
        _stl(db, bridge, "bridge-right.stl", file_hash="right")
        _stl(db, leon, "leon.stl", file_hash="right")
        _enable_hierarchy(db)

        _run(db, creator)

        db.refresh(ada)
        db.refresh(leon)
        assert not (
            ada.variant_group_id is not None
            and ada.variant_group_id == leon.variant_group_id
        )

    def test_manual_group_remains_authoritative_when_enabled(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Ada Supported")
        b = make_model(db, creator, name="Ada Unsupported")
        a.character = b.character = "Ada Wong"
        manual = VariantGroup(creator_id=creator.id, label="My Ada", source="manual")
        db.add(manual)
        db.flush()
        a.variant_group_id = manual.id
        b.variant_group_id = manual.id
        _enable_hierarchy(db)

        _run(db, creator)

        db.refresh(manual)
        assert manual.label == "My Ada"
        assert {m.id for m in manual.models} == {a.id, b.id}


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


class TestSignalAttribution:
    """A signal earns the group's reason/confidence only if it actually merged
    two components (STUDIO-242). Re-observing an already-connected pair, or
    being turned away at a hierarchy boundary, credits nothing."""

    def test_shared_hash_does_not_steal_credit_from_hierarchy(self, db):
        # Hierarchy runs first and forms the cluster; the hash pass then sees the
        # same pair already connected, so it must not restate reason/confidence.
        creator = make_creator(db)
        a = make_model(db, creator, name="Supported Files")
        b = make_model(db, creator, name="Alternate Cut")
        a.character = b.character = "Ada Wong"
        db.flush()
        _stl(db, a, "body.stl", file_hash="shared-mesh")
        _stl(db, b, "body.stl", file_hash="shared-mesh")
        _enable_hierarchy(db)

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id}
        assert groups[0].reason == "same product hierarchy"
        assert groups[0].confidence == 0.85

    def test_hierarchy_rejected_hash_edge_credits_nothing(self, db):
        # a+b are a legitimate hierarchy cluster. c shares a mesh with a but sits
        # behind a conflicting envelope: it stays out, and its rejected edge must
        # not relabel the a+b group as hash-derived.
        creator = make_creator(db)
        a = make_model(db, creator, name="Supported Files")
        b = make_model(db, creator, name="Alternate Cut")
        c = make_model(db, creator, name="Presupported")
        a.character = b.character = "Ada Wong"
        c.character = "Leon Kennedy"
        db.flush()
        _stl(db, a, "body.stl", file_hash="shared-mesh")
        _stl(db, c, "body.stl", file_hash="shared-mesh")
        _enable_hierarchy(db)

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id}
        assert groups[0].reason == "same product hierarchy"
        assert groups[0].confidence == 0.85
        db.refresh(c)
        assert c.variant_group_id is None

    def test_weaker_signals_do_not_restate_a_hash_formed_cluster(self, db):
        # Hash merges the pair; the filename and name passes both re-observe it
        # already connected. Hash keeps the attribution.
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin Archer")
        b = make_model(db, creator, name="Goblin Scout")
        db.flush()
        for fn in ("body.stl", "head.stl", "base.stl"):
            _stl(db, a, fn, file_hash=f"h-{fn}")
            _stl(db, b, fn, file_hash=f"h-{fn}")
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id}
        assert groups[0].reason == "shared mesh files"
        assert groups[0].confidence == 0.9


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


class TestNoGroupRespected:
    """#678 Phase 5 — Model.no_group replaces GroupOverride(character=None) as
    the sticky "keep me out of any group" pin."""

    def test_no_group_excludes_model_from_proposals(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin Supported")
        make_model(db, creator, name="Goblin Unsupported")
        db.flush()
        a.no_group = True  # e.g. the user split `a` out of a group.
        db.flush()

        _run(db, creator)

        db.refresh(a)
        assert a.variant_group_id is None  # not re-proposed into a group
        # b alone is a singleton → no group either
        assert _groups(db, creator) == []

    def test_no_group_excludes_even_with_a_strong_shared_signal(self, db):
        # A pinned model must stay out even when it shares a hash with a
        # sibling — no_group outranks every content signal.
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        c = make_model(db, creator, name="Gamma")
        db.flush()
        for m in (a, b, c):
            _stl(db, m, "x.stl", file_hash="deadbeef")
        a.no_group = True
        db.flush()

        _run(db, creator)

        db.refresh(a); db.refresh(b); db.refresh(c)
        assert a.variant_group_id is None
        assert b.variant_group_id is not None
        assert b.variant_group_id == c.variant_group_id


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

    def test_only_excluded_members_pruned_without_dangling_reference(self, db):
        """STUDIO-301: a group whose only members are excluded counts as empty
        (excluded models are invisible) and must be deleted — but the excluded
        model's variant_group_id must be cleared too, or un-excluding it later
        leaves it pointing at a deleted (or id-recycled) group."""
        creator = make_creator(db)
        only_member = make_model(db, creator, name="Hidden")
        only_member.excluded = True
        g = VariantGroup(creator_id=creator.id, label="OnlyExcluded", source="auto")
        db.add(g); db.flush()
        only_member.variant_group_id = g.id
        db.flush()
        group_id = g.id

        n = grouping.prune_empty_groups(db)

        assert n == 1
        assert db.query(VariantGroup).filter(VariantGroup.id == group_id).first() is None
        db.refresh(only_member)
        assert only_member.variant_group_id is None, "dangling reference must be cleared"

    def test_mixed_excluded_and_active_members_survives(self, db):
        """A group with at least one non-excluded member is genuinely non-empty
        and must not be touched — the excluded sibling's reference stays intact."""
        creator = make_creator(db)
        active = make_model(db, creator, name="Visible")
        hidden = make_model(db, creator, name="Hidden")
        hidden.excluded = True
        g = VariantGroup(creator_id=creator.id, label="Mixed", source="auto")
        db.add(g); db.flush()
        active.variant_group_id = g.id
        hidden.variant_group_id = g.id
        db.flush()
        group_id = g.id

        n = grouping.prune_empty_groups(db)

        assert n == 0
        assert db.query(VariantGroup).filter(VariantGroup.id == group_id).first() is not None
        db.refresh(hidden)
        assert hidden.variant_group_id == group_id


class TestRep:
    def test_rep_prefers_is_group_rep(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="Goblin Supported")
        rep = make_model(db, creator, name="Goblin Unsupported")
        rep.is_group_rep = True
        db.flush()

        _run(db, creator)

        assert _groups(db, creator)[0].rep_model_id == rep.id


class TestStructuralFolderNames:
    def test_lys_folders_do_not_group_across_characters(self, db):
        # STUDIO-281: a model whose folder name is a slicer format ("LYS") has no
        # product identity. Pre-fix, character_key("LYS") == "lys", so every
        # creator's LYS folder collapsed into one giant cross-character group via
        # the name signal. They must stay ungrouped (no other shared signal here).
        creator = make_creator(db)
        # Two distinct products, each with a folder literally named "LYS" (distinct
        # paths). Create under unique names for distinct folder_paths, then set the
        # scanned name to "LYS" as the scanner would for a slicer-format leaf.
        a = make_model(db, creator, name="spiderman-lys")
        b = make_model(db, creator, name="batman-lys")
        a.name = b.name = "LYS"
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []

    def test_character_still_groups_across_slicer_format_folders(self, db):
        # The flip side: two models for the same character that differ only by
        # slicer format ("Spiderman LYS" vs "Spiderman STL") DO group — the format
        # token is stripped from the identity, leaving "Spiderman".
        creator = make_creator(db)
        a = make_model(db, creator, name="Spiderman LYS")
        b = make_model(db, creator, name="Spiderman STL")
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id}

    def test_sized_base_folders_do_not_group_across_products(self, db):
        # STUDIO-286: One Page Rules ships a "Bases <range> (<Shape>+<Shape>)"
        # folder under every unit. Pre-fix these were not structural (the glued
        # "(round+square)" token defeated the all-tokens check), so every unit's
        # base folder collapsed into one cross-product group of 200+ models.
        creator = make_creator(db)
        a = make_model(db, creator, name="burrower-bases")
        b = make_model(db, creator, name="human-monk-bases")
        a.name = b.name = "Bases 25mm-32mm (Round+Square)"
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []

    def test_semi_cutted_folders_do_not_group_across_characters(self, db):
        # STUDIO-288: PolyMind ships a Full_cutted/Semi_cutted pair per character.
        # "Full_cutted" was structural but "Semi_cutted" was not, so every
        # character's semi folder became a product named "Semi" and 20 of them
        # collapsed into one group.
        creator = make_creator(db)
        a = make_model(db, creator, name="cloud-semi")
        b = make_model(db, creator, name="kratos-semi")
        a.name = b.name = "Semi_cutted"
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []

    def test_character_still_groups_across_cut_prep_folders(self, db):
        # Flip side: the two cut-prep variants of the SAME character still group,
        # since both tokens are stripped from the identity leaving "Cloud".
        creator = make_creator(db)
        a = make_model(db, creator, name="Cloud Full_cutted")
        b = make_model(db, creator, name="Cloud Semi_cutted")
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id}

    def test_differently_sized_base_folders_also_ungrouped(self, db):
        # Same defect, mixed labels — the three real-world variants observed in
        # the library must not group with each other either.
        creator = make_creator(db)
        a = make_model(db, creator, name="unit-a-bases")
        b = make_model(db, creator, name="unit-b-bases")
        a.name = "Bases 100mm-150mm (Oval+Rectangle)"
        b.name = "Bases 60mm-100mm (Round+Rectangle)"
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []


"""Variant-grouping proposal engine (#615). Exercises the blended signals
(file_hash / filename / name) and the manual-group lock."""
import itertools

import pytest

from app.models import AppSetting, VariantGroup
from app.services import grouping, grouping_policy, name_parser
from app.services.grouping import EvidenceLedger, SignalKind
from app.services.product_context import ProductContext
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


class TestSignalPolicy:
    """Precedence, confidence and reason live in one table (STUDIO-243)."""

    def test_every_signal_kind_has_a_policy(self):
        assert set(grouping.SIGNAL_POLICY) == set(SignalKind)

    def test_precedence_orders_signals_strongest_first(self):
        order = sorted(SignalKind, key=lambda k: grouping.policy_for(k).precedence)
        assert order == [
            SignalKind.HASH,
            SignalKind.HIERARCHY,
            SignalKind.FILENAME,
            SignalKind.NAME,
            SignalKind.CHARACTER,
        ]

    def test_precedence_values_are_distinct(self):
        precedences = [grouping.policy_for(k).precedence for k in SignalKind]
        assert len(set(precedences)) == len(precedences)

    @pytest.mark.parametrize(
        ("kind", "confidence"),
        [
            (SignalKind.HASH, 0.9),
            (SignalKind.HIERARCHY, 0.85),
            (SignalKind.FILENAME, 0.7),
            (SignalKind.NAME, 0.6),
            (SignalKind.CHARACTER, 0.6),
        ],
    )
    def test_confidence_values_are_stable(self, kind, confidence):
        assert grouping.policy_for(kind).confidence == confidence

    @pytest.mark.parametrize(
        ("kind", "reason"),
        [
            (SignalKind.HASH, "shared mesh files"),
            (SignalKind.HIERARCHY, "same product hierarchy"),
            (SignalKind.FILENAME, "shared STL file names"),
            (SignalKind.NAME, "name: Goblin"),
            (SignalKind.CHARACTER, "shared character label: Goblin"),
        ],
    )
    def test_reason_templates_render_the_documented_text(self, kind, reason):
        rendered = grouping.policy_for(kind).reason_template.format(label="Goblin")
        assert rendered == reason

    def test_unregistered_kind_fails_loudly(self):
        with pytest.raises(ValueError, match="no SignalPolicy registered"):
            grouping.policy_for("hash")  # a bare string is not a SignalKind

    def test_shipped_policy_table_passes_its_own_completeness_check(self):
        grouping.assert_policies_complete(grouping.SIGNAL_POLICY)

    def test_a_signal_without_a_policy_fails_at_import(self):
        # Mirrors the import-time guard: dropping any kind must raise, naming it.
        incomplete = {
            k: v for k, v in grouping.SIGNAL_POLICY.items() if k is not SignalKind.NAME
        }
        with pytest.raises(RuntimeError, match="missing entries for: NAME"):
            grouping.assert_policies_complete(incomplete)


class TestEvidenceLedger:
    """Evidence names the pair it describes, and credit is first-wins."""

    def test_records_the_model_pair_for_each_edge(self):
        ledger = EvidenceLedger()
        ledger.record(SignalKind.HASH, 1, 2)

        assert [(e.kind, e.a, e.b) for e in ledger.edges] == [(SignalKind.HASH, 1, 2)]

    def test_first_signal_to_reach_a_model_keeps_the_credit(self):
        ledger = EvidenceLedger()
        ledger.record(SignalKind.HIERARCHY, 1, 2)
        ledger.record(SignalKind.HASH, 2, 3)

        assert ledger.credit_for(1) is SignalKind.HIERARCHY
        assert ledger.credit_for(2) is SignalKind.HIERARCHY
        assert ledger.credit_for(3) is SignalKind.HASH

    def test_strongest_for_picks_the_highest_precedence_credit(self):
        ledger = EvidenceLedger()
        ledger.record(SignalKind.NAME, 1, 2)
        ledger.record(SignalKind.HASH, 2, 3)

        assert ledger.strongest_for([1, 2, 3]) is SignalKind.HASH

    def test_joining_two_already_credited_components_adds_no_attribution(self):
        # The edge that bridges them is real, but every endpoint already has a
        # credit, so the bridging kind must not become the group's reason.
        ledger = EvidenceLedger()
        ledger.record(SignalKind.HIERARCHY, 1, 2)
        ledger.record(SignalKind.FILENAME, 3, 4)
        ledger.record(SignalKind.HASH, 1, 3)

        assert ledger.strongest_for([1, 2, 3, 4]) is SignalKind.HIERARCHY

    def test_uncredited_cluster_falls_back_to_name(self):
        assert EvidenceLedger().strongest_for([1, 2]) is SignalKind.NAME

    def test_credit_for_unknown_model_is_none(self):
        assert EvidenceLedger().credit_for(99) is None


def _ctx(product_key, display_label=None):
    return ProductContext(product_key=product_key, display_label=display_label)


class TestProductBoundaries:
    """Product keys are hard anti-merge constraints (STUDIO-244)."""

    def test_maps_every_model_to_its_key(self):
        contexts = {1: _ctx("ada wong"), 2: _ctx(None)}

        assert grouping.product_boundaries(contexts) == {1: "ada wong", 2: None}

    def test_conflicting_keys_cannot_merge(self):
        contexts = {1: _ctx("ada wong"), 2: _ctx("leon kennedy")}
        uf = grouping_policy._UnionFind([1, 2], grouping.product_boundaries(contexts))

        assert uf.union(1, 2) is grouping_policy._MergeResult.REJECTED_HIERARCHY
        assert uf.find(1) != uf.find(2)

    def test_unkeyed_model_cannot_bridge_conflicting_keys(self):
        # 2 carries no key, so it may join either side — but never both, or it
        # would smuggle Ada and Leon into one cluster transitively.
        contexts = {1: _ctx("ada wong"), 2: _ctx(None), 3: _ctx("leon kennedy")}
        uf = grouping_policy._UnionFind([1, 2, 3], grouping.product_boundaries(contexts))

        assert uf.union(1, 2) is grouping_policy._MergeResult.MERGED
        assert uf.union(2, 3) is grouping_policy._MergeResult.REJECTED_HIERARCHY
        assert uf.find(1) != uf.find(3)


class TestHierarchyEvidence:
    """Pure HIERARCHY edge generation (STUDIO-244)."""

    def test_matching_keys_produce_evidence(self):
        contexts = {1: _ctx("ada wong"), 2: _ctx("ada wong")}

        evidence = grouping.hierarchy_evidence(contexts)

        assert [(e.kind, e.a, e.b) for e in evidence] == [(SignalKind.HIERARCHY, 1, 2)]

    def test_differing_keys_produce_no_evidence(self):
        contexts = {1: _ctx("ada wong"), 2: _ctx("leon kennedy")}

        assert grouping.hierarchy_evidence(contexts) == []

    def test_unkeyed_models_produce_no_evidence(self):
        contexts = {1: _ctx(None), 2: _ctx(None)}

        assert grouping.hierarchy_evidence(contexts) == []

    def test_bucket_fans_out_from_its_first_member(self):
        contexts = {1: _ctx("ada wong"), 2: _ctx("ada wong"), 3: _ctx("ada wong")}

        evidence = grouping.hierarchy_evidence(contexts)

        assert [(e.a, e.b) for e in evidence] == [(1, 2), (1, 3)]

    def test_only_supplied_candidates_appear(self):
        # Models filtered out upstream (manual groups, no_group, "off" subtrees)
        # are absent from `contexts` and so can never be proposed.
        contexts = {1: _ctx("ada wong"), 2: _ctx("ada wong")}

        mentioned = {m for e in grouping.hierarchy_evidence(contexts) for m in (e.a, e.b)}

        assert mentioned == {1, 2}


class TestHashEvidence:
    """Pure HASH edge generation (STUDIO-244)."""

    def test_shared_hash_produces_evidence(self):
        evidence = grouping.hash_evidence([1, 2], {1: {"deadbeef"}, 2: {"deadbeef"}})

        assert [(e.kind, e.a, e.b) for e in evidence] == [(SignalKind.HASH, 1, 2)]

    def test_distinct_hashes_produce_no_evidence(self):
        assert grouping.hash_evidence([1, 2], {1: {"aaa"}, 2: {"bbb"}}) == []

    def test_model_without_hashes_produces_no_evidence(self):
        assert grouping.hash_evidence([1, 2], {1: {"aaa"}}) == []

    def test_hash_at_the_bucket_cap_still_produces_evidence(self):
        ids = list(range(1, grouping_policy._HASH_BUCKET_CAP + 1))
        hashes = {mid: {"commonbase"} for mid in ids}

        evidence = grouping.hash_evidence(ids, hashes)

        # Every pairwise edge within the bucket is proposed (STUDIO-300), not
        # just edges from the first member.
        n = len(ids)
        assert len(evidence) == n * (n - 1) // 2

    def test_hash_bucket_proposes_every_pair_not_just_from_first_member(self):
        # STUDIO-300: a star-from-first pattern only ever offers (bucket[0],
        # other) edges, so a boundary rejection on the first pairing can strand
        # later members from each other. Pairwise coverage means every pair in
        # a bucket is proposed regardless of which one is first.
        evidence = grouping.hash_evidence([1, 2, 3], {1: {"h"}, 2: {"h"}, 3: {"h"}})

        pairs = {(e.a, e.b) for e in evidence}
        assert pairs == {(1, 2), (1, 3), (2, 3)}

    def test_hash_over_the_bucket_cap_produces_no_evidence(self):
        # A ubiquitous part (shared base, support raft) must not chain unrelated
        # products together.
        ids = list(range(1, grouping_policy._HASH_BUCKET_CAP + 2))
        hashes = {mid: {"commonbase"} for mid in ids}

        assert grouping.hash_evidence(ids, hashes) == []

    def test_one_products_variants_stay_under_the_cap(self):
        # STUDIO-411: the cap counts distinct products, not models. Twelve
        # variant folders of ONE product sharing a mesh are one product, so the
        # mesh is not ubiquitous and the bucket survives.
        ids = list(range(1, 13))
        hashes = {mid: {"shared-mesh"} for mid in ids}
        keys = {mid: "ada wong" for mid in ids}

        assert len(ids) > grouping_policy._HASH_BUCKET_CAP
        assert grouping.hash_evidence(ids, hashes, keys) != []

    def test_a_hash_spread_across_many_products_still_produces_no_evidence(self):
        # The case the cap actually exists for, restated per product: a shared
        # base across twelve *different* products is still ubiquitous.
        ids = list(range(1, 13))
        hashes = {mid: {"commonbase"} for mid in ids}
        keys = {mid: f"product-{mid}" for mid in ids}

        assert grouping.hash_evidence(ids, hashes, keys) == []

    def test_keyless_models_each_count_as_their_own_product(self):
        # The fallback that keeps hierarchy-off behaviour identical. Without it
        # every keyless model would share one "no product" bucket, collapsing to
        # a single product and making every ubiquitous mesh look distinctive.
        ids = list(range(1, 13))
        hashes = {mid: {"commonbase"} for mid in ids}

        assert grouping.hash_evidence(ids, hashes, {mid: None for mid in ids}) == []

    def test_a_large_single_product_bucket_does_not_expand_quadratically(self):
        # Pairwise expansion was only safe because the cap kept buckets tiny.
        # Now that one product may fill a bucket without limit, a bucket larger
        # than the cap fans out from its first member instead — O(k) edges, and
        # a same-key bucket cannot strand a member at a boundary anyway.
        ids = list(range(1, 101))
        hashes = {mid: {"shared-mesh"} for mid in ids}
        keys = {mid: "ada wong" for mid in ids}

        assert len(grouping.hash_evidence(ids, hashes, keys)) == len(ids) - 1

    def test_models_absent_from_ids_are_ignored(self):
        # 3 shares the hash but was filtered out upstream, so it must not be
        # proposed even though `hashes` still carries a row for it.
        hashes = {1: {"deadbeef"}, 2: {"deadbeef"}, 3: {"deadbeef"}}

        evidence = grouping.hash_evidence([1, 2], hashes)

        mentioned = {m for e in evidence for m in (e.a, e.b)}
        assert mentioned == {1, 2}


class TestFilenameEvidence:
    """Pure FILENAME edge generation and its three guards (STUDIO-245)."""

    def test_identical_file_sets_produce_evidence(self):
        files = {"body.stl", "head.stl", "base.stl"}

        evidence = grouping.filename_evidence([1, 2], {1: set(files), 2: set(files)})

        assert [(e.kind, e.a, e.b) for e in evidence] == [(SignalKind.FILENAME, 1, 2)]

    def test_jaccard_exactly_at_the_threshold_produces_evidence(self):
        # 3 shared of 5 union = 0.60, exactly _FILENAME_JACCARD.
        filenames = {1: {"a.stl", "b.stl", "c.stl", "d.stl"}, 2: {"a.stl", "b.stl", "c.stl", "e.stl"}}

        assert grouping_policy._FILENAME_JACCARD == 0.6
        assert len(grouping.filename_evidence([1, 2], filenames)) == 1

    def test_jaccard_just_below_the_threshold_produces_none(self):
        # 2 shared of 4 union = 0.50.
        filenames = {1: {"a.stl", "b.stl", "c.stl"}, 2: {"a.stl", "b.stl", "d.stl"}}

        assert grouping.filename_evidence([1, 2], filenames) == []

    def test_minimum_shared_count_is_enforced_at_the_boundary(self):
        filenames = {1: {"a.stl", "b.stl"}, 2: {"a.stl", "b.stl"}}

        assert grouping_policy._FILENAME_MIN_SHARED == 2
        assert len(grouping.filename_evidence([1, 2], filenames)) == 1

    def test_one_shared_filename_is_never_enough(self):
        # Jaccard is a perfect 1.0, but a single shared name is not a product.
        filenames = {1: {"body.stl"}, 2: {"body.stl"}}

        assert grouping.filename_evidence([1, 2], filenames) == []

    def test_filename_at_the_bucket_cap_stays_distinctive(self):
        cap = grouping_policy._FILENAME_BUCKET_CAP
        ids = list(range(1, cap + 1))
        filenames = {mid: {"shared-a.stl", "shared-b.stl"} for mid in ids}

        # Every pair still overlaps: freq == cap is not yet generic.
        assert grouping.filename_evidence(ids, filenames) != []

    def test_generic_filenames_cannot_group_unrelated_products(self):
        # One name shared by cap+1 models is generic and dropped, leaving each
        # model with nothing distinctive to match on.
        ids = list(range(1, grouping_policy._FILENAME_BUCKET_CAP + 2))
        filenames = {mid: {"body.stl", f"unique-{mid}.stl"} for mid in ids}

        assert grouping.filename_evidence(ids, filenames) == []

    def test_one_products_variants_stay_distinctive_past_the_cap(self):
        # STUDIO-411: frequency counts distinct products, not models. Twelve
        # variant folders of ONE product carry the same part names because they
        # ARE the same parts — counted per model that reads as generic and
        # empties both sides of every pair before the Jaccard test runs.
        ids = list(range(1, 13))
        files = {"body.stl", "head.stl", "cape.stl"}
        filenames = {mid: set(files) for mid in ids}
        keys = {mid: "ada wong" for mid in ids}

        assert len(ids) > grouping_policy._FILENAME_BUCKET_CAP
        assert grouping.filename_evidence(ids, filenames, keys) != []

    def test_a_name_spread_across_many_products_is_still_generic(self):
        # #639 restated per product: body.stl across twelve *different* products
        # carries no identity and must still be dropped.
        ids = list(range(1, 13))
        filenames = {mid: {"body.stl", "base.stl"} for mid in ids}
        keys = {mid: f"product-{mid}" for mid in ids}

        assert grouping.filename_evidence(ids, filenames, keys) == []

    def test_keyless_models_each_count_as_their_own_product(self):
        # The fallback that keeps hierarchy-off behaviour identical: with no
        # product key a model counts as its own product, reproducing the old
        # per-model frequency exactly. Deleting it would make every generic name
        # in a flat creator distinctive, which is #639 all over again.
        ids = list(range(1, 13))
        filenames = {mid: {"body.stl", "base.stl"} for mid in ids}

        assert grouping.filename_evidence(ids, filenames, {mid: None for mid in ids}) == []

    def test_large_creator_skips_filename_evidence_entirely(self):
        cap = grouping_policy._FILENAME_PASS_MODEL_CAP
        ids = list(range(1, cap + 2))
        files = {"body.stl", "head.stl"}
        filenames = {mid: set(files) for mid in ids}

        assert grouping.filename_evidence(ids, filenames) == []

    def test_creator_at_the_pass_cap_still_produces_filename_evidence(self):
        ids = list(range(1, grouping_policy._FILENAME_PASS_MODEL_CAP + 1))
        # Pair up models so no filename exceeds the generic bucket cap.
        filenames = {
            mid: {f"pair{mid // 2}-a.stl", f"pair{mid // 2}-b.stl"} for mid in ids
        }

        assert grouping.filename_evidence(ids, filenames) != []

    def test_models_absent_from_ids_are_ignored(self):
        filenames = {1: {"a.stl", "b.stl"}, 2: {"a.stl", "b.stl"}, 3: {"a.stl", "b.stl"}}

        evidence = grouping.filename_evidence([1, 2], filenames)

        assert {m for e in evidence for m in (e.a, e.b)} == {1, 2}


class TestNameKeys:
    """Pure character-key resolution with supplied creator identity (STUDIO-245)."""

    def test_strips_the_creator_name_from_the_key(self):
        keys = grouping.name_keys(
            [1, 2],
            {1: "Goblin Supported", 2: "Goblin Unsupported"},
            "Some Creator",
        )

        assert keys == {1: "Goblin", 2: "Goblin"}

    def test_matches_name_parser_for_the_same_inputs(self):
        names = {1: "Ada Wong Bust", 2: "Leon Kennedy"}

        keys = grouping.name_keys([1, 2], names, "Creator")

        assert keys == {
            mid: name_parser.character_key(name, "Creator") for mid, name in names.items()
        }

    def test_models_without_a_key_are_omitted(self):
        keys = grouping.name_keys([1], {1: ""}, "Creator")

        assert keys == {}

    def test_only_supplied_ids_are_resolved(self):
        keys = grouping.name_keys([1], {1: "Goblin King", 2: "Goblin Queen"}, None)

        assert set(keys) == {1}


class TestNameEvidence:
    """Pure NAME edge generation (STUDIO-245)."""

    def test_shared_key_produces_evidence(self):
        evidence = grouping.name_evidence([1, 2], {1: "goblin", 2: "goblin"})

        assert [(e.kind, e.a, e.b) for e in evidence] == [(SignalKind.NAME, 1, 2)]

    def test_distinct_keys_produce_no_evidence(self):
        assert grouping.name_evidence([1, 2], {1: "goblin", 2: "dragon"}) == []

    def test_keyless_models_produce_no_evidence(self):
        assert grouping.name_evidence([1, 2], {}) == []

    def test_bucket_fans_out_from_its_first_member(self):
        keys = {1: "goblin", 2: "goblin", 3: "goblin"}

        evidence = grouping.name_evidence([1, 2, 3], keys)

        assert [(e.a, e.b) for e in evidence] == [(1, 2), (1, 3)]

    def test_large_creators_still_get_name_evidence(self):
        # The pass cap suppresses only filename evidence; the name baseline must
        # keep working for creators of any size.
        ids = list(range(1, grouping_policy._FILENAME_PASS_MODEL_CAP + 2))
        keys = {mid: "goblin" for mid in ids}

        assert len(grouping.name_evidence(ids, keys)) == len(ids) - 1


class TestCharacterKeys:
    """Pure character-key resolution from the `character` field (STUDIO-367)."""

    def test_strips_the_creator_name_from_the_key(self):
        keys = grouping.character_keys(
            [1, 2],
            {1: "Goblin Supported", 2: "Goblin Unsupported"},
            "Some Creator",
        )

        assert keys == {1: "Goblin", 2: "Goblin"}

    def test_matches_name_parser_for_the_same_inputs(self):
        characters = {1: "Ada Wong Bust", 2: "Leon Kennedy"}

        keys = grouping.character_keys([1, 2], characters, "Creator")

        assert keys == {
            mid: name_parser.character_key(c, "Creator") for mid, c in characters.items()
        }

    def test_models_without_a_character_are_omitted(self):
        keys = grouping.character_keys([1], {}, "Creator")

        assert keys == {}

    def test_structural_only_character_yields_no_key(self):
        keys = grouping.character_keys([1], {1: "Supported"}, None)

        assert keys == {}

    def test_only_supplied_ids_are_resolved(self):
        keys = grouping.character_keys([1], {1: "Goblin King", 2: "Goblin Queen"}, None)

        assert set(keys) == {1}


class TestCharacterEvidence:
    """Pure CHARACTER edge generation (STUDIO-367)."""

    def test_shared_key_produces_evidence(self):
        evidence = grouping.character_evidence([1, 2], {1: "trays full", 2: "trays full"})

        assert [(e.kind, e.a, e.b) for e in evidence] == [(SignalKind.CHARACTER, 1, 2)]

    def test_distinct_keys_produce_no_evidence(self):
        assert grouping.character_evidence([1, 2], {1: "trays full", 2: "goblin"}) == []

    def test_keyless_models_produce_no_evidence(self):
        assert grouping.character_evidence([1, 2], {}) == []

    def test_bucket_fans_out_from_its_first_member(self):
        keys = {1: "trays full", 2: "trays full", 3: "trays full"}

        evidence = grouping.character_evidence([1, 2, 3], keys)

        assert [(e.a, e.b) for e in evidence] == [(1, 2), (1, 3)]


def _facts(names, keys=None, contexts=None, explicit_reps=()):
    """CandidateFacts with sensible defaults; keys default to the names."""
    return grouping.CandidateFacts(
        names=names,
        keys=keys if keys is not None else dict(names),
        contexts=contexts or {},
        explicit_reps=frozenset(explicit_reps),
    )


def _merged(ids, edges, boundaries=None):
    """Run edges through a union-find + ledger, returning both."""
    uf = grouping_policy._UnionFind(list(ids), boundaries)
    ledger = EvidenceLedger()
    grouping_policy._apply_evidence(uf, ledger, edges)
    return uf, ledger


class TestBuildClusters:
    """Component extraction and the transitive boundary guarantee (STUDIO-246)."""

    def test_unmerged_models_are_singleton_clusters(self):
        uf, _ = _merged([1, 2], [])

        assert grouping.build_clusters([1, 2], uf) == [[1], [2]]

    def test_merged_models_share_a_cluster(self):
        uf, _ = _merged([1, 2], [grouping.Evidence(SignalKind.HASH, 1, 2)])

        assert grouping.build_clusters([1, 2], uf) == [[1, 2]]

    def test_members_follow_ids_order(self):
        uf, _ = _merged([3, 1, 2], [grouping.Evidence(SignalKind.HASH, 1, 3)])

        assert grouping.build_clusters([3, 1, 2], uf) == [[3, 1], [2]]

    def test_conflicting_hierarchy_survives_transitive_edges(self):
        # 2 is unkeyed, so hash edges 1-2 then 2-3 would chain Ada to Leon
        # without the boundary constraint.
        contexts = {1: _ctx("ada wong"), 2: _ctx(None), 3: _ctx("leon kennedy")}
        edges = [
            grouping.Evidence(SignalKind.HASH, 1, 2),
            grouping.Evidence(SignalKind.HASH, 2, 3),
        ]
        uf, _ = _merged([1, 2, 3], edges, grouping.product_boundaries(contexts))

        clusters = grouping.build_clusters([1, 2, 3], uf)

        assert [1, 2] in clusters
        assert [3] in clusters


class TestSelectLabel:
    """Label preference order, unchanged from the original helper (STUDIO-246)."""

    def test_hierarchy_display_label_wins(self):
        facts = _facts(
            {1: "Supported Files", 2: "Alternate Cut"},
            keys={1: "supported", 2: "alternate"},
            contexts={1: _ctx("ada wong", "Ada Wong"), 2: _ctx("ada wong", "Ada Wong")},
        )

        assert grouping.select_label([1, 2], facts) == "Ada Wong"

    def test_most_common_name_key_wins_without_hierarchy(self):
        facts = _facts(
            {1: "Goblin A", 2: "Goblin B", 3: "Orc C"},
            keys={1: "Goblin", 2: "Goblin", 3: "Orc"},
        )

        assert grouping.select_label([1, 2, 3], facts) == "Goblin"

    def test_falls_back_to_the_first_members_name(self):
        facts = _facts({1: "Mystery Sculpt", 2: "Other"}, keys={})

        assert grouping.select_label([1, 2], facts) == "Mystery Sculpt"


class TestSelectRepresentative:
    """User-pinned representatives outrank the positional default."""

    def test_explicit_representative_is_preferred(self):
        facts = _facts({1: "A", 2: "B", 3: "C"}, explicit_reps={3})

        assert grouping.select_representative([1, 2, 3], facts) == 3

    def test_first_member_is_the_default(self):
        facts = _facts({1: "A", 2: "B"})

        assert grouping.select_representative([1, 2], facts) == 1

    def test_first_explicit_member_wins_when_several_are_pinned(self):
        facts = _facts({1: "A", 2: "B", 3: "C"}, explicit_reps={2, 3})

        assert grouping.select_representative([1, 2, 3], facts) == 2


class TestProposeGroups:
    """Typed proposals, computed without a database (STUDIO-246)."""

    def test_singleton_clusters_produce_no_proposal(self):
        uf, ledger = _merged([1], [])

        assert grouping.propose_groups([1], uf, ledger, _facts({1: "Goblin"})) == []

    def test_structural_only_cluster_produces_no_proposal(self):
        # Both members are junk folders, so the cluster has no product identity
        # even though a hash merged it (#639).
        names = {1: "Supported", 2: "STL"}
        uf, ledger = _merged([1, 2], [grouping.Evidence(SignalKind.HASH, 1, 2)])

        assert grouping.propose_groups([1, 2], uf, ledger, _facts(names)) == []

    def test_one_real_product_is_enough_to_propose(self):
        names = {1: "Supported", 2: "Goblin King"}
        uf, ledger = _merged([1, 2], [grouping.Evidence(SignalKind.HASH, 1, 2)])

        proposals = grouping.propose_groups([1, 2], uf, ledger, _facts(names))

        assert len(proposals) == 1
        assert proposals[0].members == (1, 2)

    def test_keyless_members_cannot_supply_product_identity(self):
        names = {1: "Goblin King", 2: "Goblin Scout"}
        uf, ledger = _merged([1, 2], [grouping.Evidence(SignalKind.HASH, 1, 2)])

        proposals = grouping.propose_groups([1, 2], uf, ledger, _facts(names, keys={}))

        assert proposals == []

    def test_character_identity_is_enough_when_names_carry_none(self):
        # Bare size folders ("20"/"25") have no name-based product identity at
        # all, but the shared `character` envelope ("Trays Full") does
        # (STUDIO-367) — mirrors what the legacy startup backfill grouped.
        names = {1: "20", 2: "25"}
        characters = {1: "Trays Full", 2: "Trays Full"}
        facts = grouping.CandidateFacts(
            names=names,
            keys={},
            contexts={},
            explicit_reps=frozenset(),
            characters=characters,
            character_keys={1: "Trays Full", 2: "Trays Full"},
        )
        uf, ledger = _merged([1, 2], [grouping.Evidence(SignalKind.CHARACTER, 1, 2)])

        proposals = grouping.propose_groups([1, 2], uf, ledger, facts)

        assert len(proposals) == 1
        assert proposals[0].reason == "shared character label: Trays Full"
        assert proposals[0].confidence == 0.6

    def test_structural_character_cannot_supply_product_identity(self):
        # A cluster whose only "identity" is a structural character label
        # ("Supported") is exactly the junk-label case #639 already guards
        # against for names — the same guard must hold for characters.
        names = {1: "20", 2: "25"}
        characters = {1: "Supported", 2: "Supported"}
        facts = grouping.CandidateFacts(
            names=names,
            keys={},
            contexts={},
            explicit_reps=frozenset(),
            characters=characters,
            character_keys={},  # character_keys() already omits structural labels
        )
        uf, ledger = _merged([1, 2], [grouping.Evidence(SignalKind.HASH, 1, 2)])

        assert grouping.propose_groups([1, 2], uf, ledger, facts) == []

    def test_proposal_carries_the_merging_signals_reason_and_confidence(self):
        names = {1: "Goblin A", 2: "Goblin B"}
        uf, ledger = _merged([1, 2], [grouping.Evidence(SignalKind.HASH, 1, 2)])

        proposal = grouping.propose_groups([1, 2], uf, ledger, _facts(names))[0]

        assert proposal.signal is SignalKind.HASH
        assert proposal.reason == "shared mesh files"
        assert proposal.confidence == 0.9

    def test_name_formed_proposal_renders_its_label_into_the_reason(self):
        facts = _facts({1: "Goblin A", 2: "Goblin B"}, keys={1: "Goblin", 2: "Goblin"})
        uf, ledger = _merged([1, 2], [grouping.Evidence(SignalKind.NAME, 1, 2)])

        proposal = grouping.propose_groups([1, 2], uf, ledger, facts)[0]

        assert proposal.label == "Goblin"
        assert proposal.reason == "name: Goblin"
        assert proposal.confidence == 0.6

    def test_explicit_representative_reaches_the_proposal(self):
        facts = _facts({1: "Goblin A", 2: "Goblin B"}, explicit_reps={2})
        uf, ledger = _merged([1, 2], [grouping.Evidence(SignalKind.HASH, 1, 2)])

        assert grouping.propose_groups([1, 2], uf, ledger, facts)[0].rep_model_id == 2

    def test_proposals_follow_cluster_order(self):
        names = {1: "Goblin A", 2: "Goblin B", 3: "Orc A", 4: "Orc B"}
        edges = [
            grouping.Evidence(SignalKind.HASH, 3, 4),
            grouping.Evidence(SignalKind.HASH, 1, 2),
        ]
        uf, ledger = _merged([1, 2, 3, 4], edges)

        proposals = grouping.propose_groups([1, 2, 3, 4], uf, ledger, _facts(names))

        # Cluster order follows `ids`, not the order edges were applied.
        assert [p.members for p in proposals] == [(1, 2), (3, 4)]

    def test_proposing_mutates_nothing_and_creates_no_rows(self):
        names = {1: "Goblin A", 2: "Goblin B"}
        facts = _facts(names)
        uf, ledger = _merged([1, 2], [grouping.Evidence(SignalKind.HASH, 1, 2)])

        grouping.propose_groups([1, 2], uf, ledger, facts)

        # Facts are frozen and the ledger still holds only what merged.
        assert facts.names == names
        assert [(e.a, e.b) for e in ledger.edges] == [(1, 2)]


class TestOrderCandidates:
    """Candidate ordering is stable and independent of row ids (STUDIO-248)."""

    def test_orders_by_folder_path(self):
        paths = {1: "/lib/c/zeta", 2: "/lib/c/alpha", 3: "/lib/c/mid"}
        names = {1: "Zeta", 2: "Alpha", 3: "Mid"}

        assert grouping.order_candidates([1, 2, 3], paths, names) == [2, 3, 1]

    def test_result_is_invariant_under_input_order(self):
        paths = {1: "/lib/c/zeta", 2: "/lib/c/alpha", 3: "/lib/c/mid"}
        names = {1: "Zeta", 2: "Alpha", 3: "Mid"}

        outcomes = {
            tuple(grouping.order_candidates(list(perm), paths, names))
            for perm in itertools.permutations([1, 2, 3])
        }

        assert len(outcomes) == 1

    def test_ordering_does_not_depend_on_id_assignment(self):
        # The same library inserted in a different order gets different
        # autoincrement ids; the resulting sequence of folder paths must match.
        first = grouping.order_candidates(
            [1, 2], {1: "/lib/c/alpha", 2: "/lib/c/beta"}, {1: "Alpha", 2: "Beta"}
        )
        second = grouping.order_candidates(
            [7, 5], {7: "/lib/c/alpha", 5: "/lib/c/beta"}, {7: "Alpha", 5: "Beta"}
        )

        assert [("alpha" if m in (1, 7) else "beta") for m in first] == ["alpha", "beta"]
        assert [("alpha" if m in (1, 7) else "beta") for m in second] == ["alpha", "beta"]

    def test_separator_style_does_not_change_the_order(self):
        paths = {1: "C:\\lib\\c\\beta", 2: "C:/lib/c/alpha"}
        names = {1: "Beta", 2: "Alpha"}

        assert grouping.order_candidates([1, 2], paths, names) == [2, 1]

    def test_identical_paths_fall_back_to_name_then_id(self):
        paths = {1: "/lib/c/dup", 2: "/lib/c/dup", 3: "/lib/c/dup"}
        names = {1: "B", 2: "A", 3: "A"}

        assert grouping.order_candidates([3, 1, 2], paths, names) == [2, 3, 1]


class TestDeterministicProposals:
    """Identical logical input yields identical proposals (STUDIO-248)."""

    def _propose(self, ids, paths, names, hashes=None, keys=None, explicit_reps=()):
        ordered = grouping.order_candidates(list(ids), paths, names)
        uf = grouping_policy._UnionFind(ordered)
        ledger = EvidenceLedger()
        grouping_policy._apply_evidence(uf, ledger, grouping.hash_evidence(ordered, hashes or {}))
        facts = _facts(names, keys=keys, explicit_reps=explicit_reps)
        return grouping.propose_groups(ordered, uf, ledger, facts)

    def test_every_permutation_produces_equal_proposals(self):
        names = {1: "Goblin Archer", 2: "Goblin Scout", 3: "Goblin Guard"}
        paths = {mid: f"/lib/c/{name}" for mid, name in names.items()}
        # 1 bridges both hashes, so edge order decides who roots the component.
        hashes = {1: {"h-a", "h-b"}, 2: {"h-a"}, 3: {"h-b"}}

        outcomes = {
            tuple(
                (p.members, p.label, p.rep_model_id, p.signal, p.reason, p.confidence)
                for p in self._propose(perm, paths, names, hashes)
            )
            for perm in itertools.permutations([1, 2, 3])
        }

        assert len(outcomes) == 1

    def test_permuted_hash_iteration_cannot_change_proposals(self):
        # Rebuilding the same hash sets in a different insertion order models a
        # different PYTHONHASHSEED between processes.
        names = {1: "Goblin Archer", 2: "Goblin Scout", 3: "Goblin Guard"}
        paths = {mid: f"/lib/c/{name}" for mid, name in names.items()}

        outcomes = set()
        for order in itertools.permutations(["h-a", "h-b"]):
            hashes = {1: set(order), 2: {"h-a"}, 3: {"h-b"}}
            outcomes.add(
                tuple((p.members, p.label) for p in self._propose([1, 2, 3], paths, names, hashes))
            )

        assert len(outcomes) == 1

    def test_default_representative_is_stable_across_permutations(self):
        names = {1: "Goblin Archer", 2: "Goblin Scout"}
        paths = {1: "/lib/c/zzz-archer", 2: "/lib/c/aaa-scout"}
        hashes = {1: {"h"}, 2: {"h"}}

        reps = {
            self._propose(perm, paths, names, hashes)[0].rep_model_id
            for perm in itertools.permutations([1, 2])
        }

        # 2 sorts first by folder path, so it is the positional default either way.
        assert reps == {2}

    def test_explicit_representative_still_wins_over_the_stable_default(self):
        names = {1: "Goblin Archer", 2: "Goblin Scout"}
        paths = {1: "/lib/c/zzz-archer", 2: "/lib/c/aaa-scout"}
        hashes = {1: {"h"}, 2: {"h"}}

        reps = {
            self._propose(perm, paths, names, hashes, explicit_reps={1})[0].rep_model_id
            for perm in itertools.permutations([1, 2])
        }

        assert reps == {1}


class TestLabelTieResolution:
    """Label ties resolve predictably rather than by encounter order."""

    def test_tied_name_keys_resolve_alphabetically(self):
        facts = _facts({1: "A", 2: "B"}, keys={1: "Zebra", 2: "Apple"})

        assert grouping.select_label([1, 2], facts) == "Apple"
        assert grouping.select_label([2, 1], facts) == "Apple"

    def test_a_clear_majority_still_beats_alphabetical_order(self):
        facts = _facts(
            {1: "A", 2: "B", 3: "C"},
            keys={1: "Zebra", 2: "Zebra", 3: "Apple"},
        )

        assert grouping.select_label([1, 2, 3], facts) == "Zebra"

    def test_tied_hierarchy_labels_resolve_alphabetically(self):
        facts = _facts(
            {1: "A", 2: "B"},
            contexts={1: _ctx("k", "Zeta Product"), 2: _ctx("k", "Alpha Product")},
        )

        assert grouping.select_label([1, 2], facts) == "Alpha Product"
        assert grouping.select_label([2, 1], facts) == "Alpha Product"


def _candidate(mid, folder_path=None, excluded=False, no_group=False, variant_group_id=None):
    return grouping.CandidateModel(
        id=mid,
        folder_path=folder_path if folder_path is not None else f"/lib/c/model{mid}",
        excluded=excluded,
        no_group=no_group,
        variant_group_id=variant_group_id,
    )


class TestSelectEligible:
    """Candidate eligibility, decided without a database (STUDIO-241)."""

    def test_a_plain_model_is_eligible(self):
        decision = grouping.select_eligible([_candidate(1)], set(), [])

        assert decision.eligible == (1,)
        assert decision.off_subtree == ()
        assert decision.reasons == {}

    def test_excluded_models_are_ineligible(self):
        decision = grouping.select_eligible([_candidate(1, excluded=True)], set(), [])

        assert decision.eligible == ()
        assert decision.reasons == {1: grouping.IneligibilityReason.EXCLUDED}

    def test_manual_group_members_are_always_ineligible(self):
        decision = grouping.select_eligible([_candidate(1, variant_group_id=42)], {42}, [])

        assert decision.eligible == ()
        assert decision.reasons == {1: grouping.IneligibilityReason.MANUAL_GROUP}

    def test_membership_of_an_auto_group_does_not_block_eligibility(self):
        # variant_group_id set, but not to a manual group — the engine rebuilds
        # auto groups from scratch each run.
        decision = grouping.select_eligible([_candidate(1, variant_group_id=7)], {42}, [])

        assert decision.eligible == (1,)

    def test_no_group_models_are_ineligible(self):
        decision = grouping.select_eligible([_candidate(1, no_group=True)], set(), [])

        assert decision.eligible == ()
        assert decision.reasons == {1: grouping.IneligibilityReason.NO_GROUP}

    def test_off_subtree_models_are_ineligible_and_reported_for_clearing(self):
        models = [_candidate(1, folder_path="/lib/c/off/model")]

        decision = grouping.select_eligible(models, set(), [("/lib/c/off", "off")])

        assert decision.eligible == ()
        assert decision.off_subtree == (1,)
        assert decision.reasons == {1: grouping.IneligibilityReason.OFF_SUBTREE}

    def test_auto_subtree_models_stay_eligible(self):
        models = [_candidate(1, folder_path="/lib/c/on/model")]

        decision = grouping.select_eligible(models, set(), [("/lib/c/off", "off")])

        assert decision.eligible == (1,)

    def test_nearer_auto_subtree_rescues_a_model_from_an_outer_off(self):
        models = [_candidate(1, folder_path="/lib/c/off/keep/model")]
        strategies = [("/lib/c/off", "off"), ("/lib/c/off/keep", "auto")]

        assert grouping.select_eligible(models, set(), strategies).eligible == (1,)

    def test_no_strategies_means_the_subtree_rule_cannot_fire(self):
        models = [_candidate(1, folder_path="/lib/c/off/model")]

        decision = grouping.select_eligible(models, set(), [])

        assert decision.eligible == (1,)
        assert decision.off_subtree == ()

    def test_only_off_subtree_models_are_listed_for_clearing(self):
        models = [
            _candidate(1, no_group=True),
            _candidate(2, excluded=True),
            _candidate(3, folder_path="/lib/c/off/model", variant_group_id=9),
        ]

        decision = grouping.select_eligible(models, set(), [("/lib/c/off", "off")])

        assert decision.off_subtree == (3,)

    def test_eligible_order_follows_the_input(self):
        decision = grouping.select_eligible([_candidate(3), _candidate(1)], set(), [])

        assert decision.eligible == (3, 1)

    def test_empty_input_yields_an_empty_decision(self):
        decision = grouping.select_eligible([], set(), [])

        assert decision.eligible == ()
        assert decision.off_subtree == ()
        assert decision.reasons == {}

    def test_accepts_a_generator(self):
        decision = grouping.select_eligible((c for c in [_candidate(1)]), set(), [])

        assert decision.eligible == (1,)


class TestEligibilityPrecedence:
    """A model tripping several rules reports the first one evaluated."""

    def test_excluded_outranks_everything(self):
        model = _candidate(1, excluded=True, no_group=True, variant_group_id=42)

        decision = grouping.select_eligible([model], {42}, [("/lib/c", "off")])

        assert decision.reasons == {1: grouping.IneligibilityReason.EXCLUDED}

    def test_manual_group_outranks_no_group(self):
        model = _candidate(1, no_group=True, variant_group_id=42)

        decision = grouping.select_eligible([model], {42}, [])

        assert decision.reasons == {1: grouping.IneligibilityReason.MANUAL_GROUP}

    def test_no_group_outranks_the_subtree_rule(self):
        model = _candidate(1, folder_path="/lib/c/off/model", no_group=True)

        decision = grouping.select_eligible([model], set(), [("/lib/c/off", "off")])

        assert decision.reasons == {1: grouping.IneligibilityReason.NO_GROUP}
        # Not queued for clearing: it was never an auto-group member to begin with.
        assert decision.off_subtree == ()

    def test_no_group_outranks_every_signal_by_never_becoming_a_candidate(self):
        # Two models that a shared hash would otherwise merge; one is pinned
        # no_group, so no evidence can ever reach it.
        models = [_candidate(1), _candidate(2, no_group=True)]

        decision = grouping.select_eligible(models, set(), [])

        assert decision.eligible == (1,)
        assert 2 not in decision.eligible


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

    def test_case_variant_envelopes_are_one_product(self, db):
        """Green before STUDIO-413 as well as after, and pinned precisely
        because of that: `product_key` folds case, which is the only reason
        mixed-case siblings ever grouped and therefore the reason the bug read
        as latent for so long. Nothing pinned this shape while it was doing the
        rescuing, so the fold it depends on could have been dropped in silence.
        `display_label` keeps a real casing per member; `_most_common` picks
        among them."""
        creator = make_creator(db)
        a = make_model(db, creator, name="Supported Files")
        b = make_model(db, creator, name="Alternate Cut")
        c = make_model(db, creator, name="Hollow")
        a.character, b.character, c.character = "Ada Wong", "ADA WONG", "ada wong"
        _enable_hierarchy(db)

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id, c.id}
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


class TestProductScopedBucketCaps:
    """Content evidence survives past 8 variants of one product (STUDIO-411).

    The bucket caps used to count models, so a product with 9 or more variants
    lost both content signals outright and its grouping rested entirely on
    `character` being right — no second opinion when it wasn't. Counting
    distinct products instead keeps the #639 guard (a name spread across many
    products is still generic) while letting one product's variants corroborate
    each other.
    """

    # All twelve names are structural, so `character_key` reduces each to
    # nothing: neither the NAME signal nor the product-identity check can form
    # or rescue a group here. Identity comes from `character` or from nowhere.
    VARIANTS = [
        "Supported", "Unsupported", "Hollow", "Solid", "Presupported", "STL",
        "32mm", "54mm", "75mm", "Bust", "Chitubox", "Lychee",
    ]
    PARTS = ["body.stl", "head.stl", "cape.stl", "base.stl"]

    def _variants(self, db, creator, characters):
        """One model per name, every one carrying the identical part set."""
        models = []
        for name, character in zip(self.VARIANTS, characters):
            model = make_model(db, creator, name=name, character=character)
            for filename in self.PARTS:
                _stl(db, model, filename)
            models.append(model)
        db.flush()
        return models

    def test_orphan_variants_rejoin_their_product_past_the_cap(self, db):
        """Ten variants the scanner labelled, two it left characterless.

        The two orphans have no `character`, so hierarchy can neither group them
        nor bar them; the identical part set is the only evidence that they
        belong. Counted per model that evidence was thrown away for being
        generic and both orphans fell out of their own product's group.
        """
        creator = make_creator(db)
        models = self._variants(db, creator, ["Ada Wong"] * 10 + [None, None])
        _enable_hierarchy(db)

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {m.id for m in models}
        assert groups[0].label == "Ada Wong"

    def test_two_products_sharing_a_file_set_stay_apart_with_hierarchy_on(self, db):
        """Two characters cut from the same part set must not weld together.

        Twelve models, one identical file set, two `character` envelopes. The
        per-product count sees two products — under the cap, so the evidence is
        offered — and the product boundary is what turns it away. Both halves of
        the protection are exercised here.
        """
        creator = make_creator(db)
        self._variants(db, creator, ["Ada Wong"] * 6 + ["Leon Kennedy"] * 6)
        _enable_hierarchy(db)

        _run(db, creator)

        groups = _groups(db, creator)
        assert {g.label for g in groups} == {"Ada Wong", "Leon Kennedy"}
        assert sorted(len(g.models) for g in groups) == [6, 6]

    def test_hierarchy_off_keeps_the_old_per_model_count(self, db):
        """With hierarchy off there are no product keys, so nothing changes.

        Every model falls back to counting as its own product, which reproduces
        the old per-model frequency exactly. Raising the cap unconditionally
        instead would merge all twelve of these into one group labelled after a
        variant folder — this is the test that says no to that.
        """
        creator = make_creator(db)
        self._variants(db, creator, ["Ada Wong"] * 6 + ["Leon Kennedy"] * 6)

        _run(db, creator)

        groups = _groups(db, creator)
        assert {g.label for g in groups} == {"Ada Wong", "Leon Kennedy"}
        assert sorted(len(g.models) for g in groups) == [6, 6]


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

    def test_names_differing_only_in_case_share_a_bucket(self, db):
        """STUDIO-413. `display_name` title-cases most of this away before it
        reaches the bucket, but it deliberately preserves short all-caps tokens
        so acronyms ("APC", "JSC") survive — which leaves "ADA WONG" and
        "Ada Wong" in two buckets for one product. The label still comes from a
        raw key, so folding the bucket must not lowercase it."""
        creator = make_creator(db)
        a = make_model(db, creator, name="ADA WONG Supported")
        b = make_model(db, creator, name="Ada Wong Unsupported")
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id}
        assert groups[0].label == "ADA WONG"      # a real casing, never "ada wong"


class TestCharacterSignal:
    """Scan-time reproduction of the legacy startup backfill's grouping,
    through the same character_key/is_structural_folder filtering every other
    signal uses (STUDIO-367)."""

    def test_shared_character_groups_bare_number_names(self, db):
        # The exact evidence shape from the STUDIO-367 ticket: sized pack
        # folders named only "20"/"25"/"30"/"40" under one character envelope.
        creator = make_creator(db)
        a = make_model(db, creator, name="20", character="Trays Full")
        b = make_model(db, creator, name="25", character="Trays Full")
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id}
        assert groups[0].reason == "shared character label: Trays Full"
        assert groups[0].confidence == 0.6

    def test_distinct_characters_stay_separate(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="20a", character="Trays Full")
        make_model(db, creator, name="20b", character="FDM Full Trays")
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []

    def test_structural_character_does_not_group(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="20", character="Supported")
        make_model(db, creator, name="25", character="Supported")
        db.flush()

        _run(db, creator)

        assert _groups(db, creator) == []

    def test_characters_differing_only_in_case_group_without_a_rescan(self, db):
        """STUDIO-413's reason to fix the bucket and not just the scanner: this
        is what a library already holds. The scanner fix only reaches models
        that are re-walked, and nothing here has a name key to fall back on —
        so before the fold these three variants of one product were not merely
        mis-labelled, they formed no group at all."""
        creator = make_creator(db)
        a = make_model(db, creator, name="20", character="Trays Full")
        b = make_model(db, creator, name="25", character="TRAYS FULL")
        c = make_model(db, creator, name="30", character="trays full")
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert {m.id for m in groups[0].models} == {a.id, b.id, c.id}
        assert groups[0].label == "TRAYS FULL"    # a real casing, never "trays full"

    def test_name_signal_takes_precedence_when_both_apply(self, db):
        # A stronger signal already explains the merge, so CHARACTER's weaker
        # reason must not overwrite it even though both would form the cluster.
        creator = make_creator(db)
        make_model(db, creator, name="Goblin Supported", character="Trays Full")
        make_model(db, creator, name="Goblin Unsupported", character="Trays Full")
        db.flush()

        _run(db, creator)

        groups = _groups(db, creator)
        assert len(groups) == 1
        assert groups[0].reason == "name: Goblin"


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

    def test_manual_membership_survives_an_off_subtree(self, db):
        # An "off" subtree clears stale *automatic* membership, but a curated
        # manual group is the user's decision and must be left alone (STUDIO-241).
        from app.models import GroupingStrategy
        creator = make_creator(db)
        curated = make_model(db, creator, name="Curated Hero")
        manual = VariantGroup(creator_id=creator.id, label="My Group", source="manual")
        db.add(manual)
        db.flush()
        curated.variant_group_id = manual.id
        parent = curated.folder_path.rsplit("/", 1)[0]
        db.add(GroupingStrategy(path=parent, strategy="off"))
        db.flush()

        _run(db, creator)

        db.refresh(curated)
        assert curated.variant_group_id == manual.id
        assert db.get(VariantGroup, manual.id) is not None


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


class TestCreatorIsResolvedOnce:
    """Creator identity is loaded once per run, not once per candidate (STUDIO-239).

    The name-key pass used to call `_creator_name(db, creator_id)` inside its
    per-model loop. A counting spy is cheap insurance against that returning.
    """

    def test_creator_name_is_resolved_at_most_once_per_regroup(self, db, monkeypatch):
        creator = make_creator(db)
        for name in ("Goblin Archer", "Goblin Scout", "Goblin Guard", "Orc Brute"):
            make_model(db, creator, name=name)
        db.flush()

        calls = []
        real = grouping._creator_name
        monkeypatch.setattr(
            grouping,
            "_creator_name",
            lambda session, cid: (calls.append(cid), real(session, cid))[1],
        )

        _run(db, creator)

        assert calls == [creator.id]

    def test_creator_name_lookup_scales_with_runs_not_models(self, db, monkeypatch):
        creator = make_creator(db)
        for i in range(12):
            make_model(db, creator, name=f"Goblin {i}")
        db.flush()

        calls = []
        real = grouping._creator_name
        monkeypatch.setattr(
            grouping,
            "_creator_name",
            lambda session, cid: (calls.append(cid), real(session, cid))[1],
        )

        _run(db, creator)
        _run(db, creator)

        assert len(calls) == 2


class TestDropAutoGroupsProtectsManualGroups:
    """The `source == "auto"` filter is what protects manual groups (STUDIO-239).

    `_drop_auto_groups` no longer takes a manual-id set, so these pin that the
    protection really comes from the query rather than a caller-supplied list.
    """

    def test_manual_group_and_members_survive_a_drop(self, db):
        creator = make_creator(db)
        kept = make_model(db, creator, name="Curated Hero")
        manual = VariantGroup(creator_id=creator.id, label="My Group", source="manual")
        db.add(manual)
        db.flush()
        kept.variant_group_id = manual.id
        db.flush()

        grouping._drop_auto_groups(db, creator.id)
        db.flush()
        db.expire_all()

        assert db.get(VariantGroup, manual.id) is not None
        db.refresh(kept)
        assert kept.variant_group_id == manual.id

    def test_auto_group_and_its_membership_are_cleared(self, db):
        creator = make_creator(db)
        model = make_model(db, creator, name="Auto Hero")
        auto = VariantGroup(creator_id=creator.id, label="Auto", source="auto")
        db.add(auto)
        db.flush()
        auto_id = auto.id
        model.variant_group_id = auto_id
        db.flush()

        grouping._drop_auto_groups(db, creator.id)
        db.flush()
        db.expire_all()

        assert db.get(VariantGroup, auto_id) is None
        db.refresh(model)
        assert model.variant_group_id is None

    def test_another_creators_auto_group_is_untouched(self, db):
        mine = make_creator(db, name="Mine")
        theirs = make_creator(db, name="Theirs")
        other = VariantGroup(creator_id=theirs.id, label="Theirs", source="auto")
        db.add(other)
        db.flush()

        grouping._drop_auto_groups(db, mine.id)
        db.flush()

        assert db.get(VariantGroup, other.id) is not None


class TestMaterialisationOwnsPersistenceOnly:
    """Transaction ownership stays with the caller (STUDIO-247)."""

    def test_regroup_does_not_commit_so_the_caller_can_roll_back(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="Goblin Supported")
        make_model(db, creator, name="Goblin Unsupported")
        db.commit()  # baseline the caller could return to

        grouping.regroup_creator(db, creator.id)
        db.flush()
        assert len(_groups(db, creator)) == 1, "groups should exist inside the transaction"

        db.rollback()

        # Nothing was committed underneath the caller.
        assert _groups(db, creator) == []

    def test_a_committed_regroup_survives(self, db):
        # The mirror of the above: rollback undoing the work is the caller's
        # choice, not the engine failing to persist.
        creator = make_creator(db)
        make_model(db, creator, name="Goblin Supported")
        make_model(db, creator, name="Goblin Unsupported")
        db.flush()

        grouping.regroup_creator(db, creator.id)
        db.commit()
        db.expire_all()

        assert len(_groups(db, creator)) == 1

    def test_auto_groups_are_replaced_not_accumulated(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="Goblin Supported")
        make_model(db, creator, name="Goblin Unsupported")
        db.flush()

        _run(db, creator)
        assert len(_groups(db, creator)) == 1
        _run(db, creator)

        # Replaced, not accumulated: still exactly one live auto group, and no
        # orphan left alongside it. Note ids are NOT expected to change — SQLite
        # reuses a rowid freed by the delete, which is precisely the hazard
        # STUDIO-301 had to guard when clearing member references first.
        assert len(_groups(db, creator)) == 1
        assert db.query(VariantGroup).filter_by(creator_id=creator.id).count() == 1

    def test_materialising_no_proposals_leaves_no_auto_groups(self, db):
        creator = make_creator(db)
        model = make_model(db, creator, name="Lonely Sculpt")
        db.flush()

        grouping.materialise_proposals(db, creator.id, [], {model.id: model}, [model.id])
        db.flush()

        assert _groups(db, creator) == []
        db.refresh(model)
        assert model.variant_group_id is None


class TestRepeatedRegroupingIsStable:
    """Regrouping the same library twice persists equivalent metadata (STUDIO-248)."""

    def _snapshot(self, db, creator):
        return sorted(
            (
                g.label,
                g.reason,
                g.confidence,
                # Compare by folder path, not id: ids change as groups are
                # dropped and recreated each run.
                next(m.folder_path for m in g.models if m.id == g.rep_model_id),
                tuple(sorted(m.folder_path for m in g.models)),
            )
            for g in _groups(db, creator)
        )

    def test_second_run_reproduces_the_first(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin Archer")
        b = make_model(db, creator, name="Goblin Scout")
        c = make_model(db, creator, name="Orc Brute")
        d = make_model(db, creator, name="Orc Warlord")
        db.flush()
        for model, file_hash in ((a, "goblin"), (b, "goblin"), (c, "orc"), (d, "orc")):
            _stl(db, model, "body.stl", file_hash=file_hash)
            _stl(db, model, f"{model.name}.stl", file_hash=file_hash)
        db.flush()

        _run(db, creator)
        first = self._snapshot(db, creator)
        _run(db, creator)
        second = self._snapshot(db, creator)

        assert len(first) == 2
        assert first == second

    def test_repeat_run_is_stable_with_hierarchy_enabled(self, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Supported Files")
        b = make_model(db, creator, name="Alternate Cut")
        a.character = b.character = "Ada Wong"
        _enable_hierarchy(db)
        db.flush()

        _run(db, creator)
        first = self._snapshot(db, creator)
        _run(db, creator)

        assert first == self._snapshot(db, creator)
        assert len(first) == 1


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


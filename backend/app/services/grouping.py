"""Variant-group orchestration and persistence (#615, epic #613).

Thin database layer over `grouping_policy`, which owns every decision about what
automatic grouping should do. This module supplies that policy with inputs, then
writes its output:

    load inputs  →  propose (pure)  →  materialise

`regroup_creator` recreates a creator's `auto` groups from scratch on every run.
`source="manual"` groups and their members are never touched, and `Model.no_group`
— an explicit, sticky "keep me out of any group" decision (#678 Phase 5) — is
excluded from proposals. Both protections are enforced in the policy layer's
eligibility stage; the only write this module does on their behalf is clearing
stale automatic membership from models that have since fallen under an `off`
subtree.

Transaction ownership stays with the caller: this module flushes, never commits,
so a caller can still roll back everything a regroup did (STUDIO-247).

The pure policy names are re-exported below so existing callers and tests keep
their import paths. `grouping.select_eligible` and
`grouping_policy.select_eligible` are the same object.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AppSetting, Model, STLFile, VariantGroup, GroupingStrategy
from app.services.grouping_policy import (
    # Underscored but shared deliberately: the orchestrator is the one sanctioned
    # consumer of the union-find and the evidence applier.
    _apply_evidence,
    _UnionFind,
    SIGNAL_POLICY,
    CandidateFacts,
    CandidateModel,
    EligibilityDecision,
    Evidence,
    EvidenceLedger,
    GroupProposal,
    IneligibilityReason,
    SignalKind,
    SignalPolicy,
    assert_policies_complete,
    build_clusters,
    character_evidence,
    character_keys,
    filename_evidence,
    hash_evidence,
    hierarchy_evidence,
    name_evidence,
    name_keys,
    order_candidates,
    policy_for,
    product_boundaries,
    propose_groups,
    select_eligible,
    select_label,
    select_representative,
)
from app.services.grouping_strategy import SubtreeStrategy, normalize_path, resolve_subtree_strategy
from app.services.product_context import ProductContext, resolve_product_context

__all__ = [
    "regroup_creator",
    "prune_empty_groups",
    "materialise_proposals",
    # Re-exported policy surface (see grouping_policy for the implementations).
    "CandidateFacts",
    "CandidateModel",
    "EligibilityDecision",
    "Evidence",
    "EvidenceLedger",
    "GroupProposal",
    "IneligibilityReason",
    "SIGNAL_POLICY",
    "SignalKind",
    "SignalPolicy",
    "SubtreeStrategy",
    "assert_policies_complete",
    "build_clusters",
    "character_evidence",
    "character_keys",
    "filename_evidence",
    "hash_evidence",
    "hierarchy_evidence",
    "name_evidence",
    "name_keys",
    "normalize_path",
    "order_candidates",
    "policy_for",
    "product_boundaries",
    "propose_groups",
    "resolve_subtree_strategy",
    "select_eligible",
    "select_label",
    "select_representative",
]

_HIERARCHY_SETTING = "hierarchy_variant_grouping_enabled"


def _hierarchy_enabled(db: Session) -> bool:
    row = db.get(AppSetting, _HIERARCHY_SETTING)
    return row is not None and row.value is True


def regroup_creator(db: Session, creator_id: int) -> None:
    """Recompute auto variant groups for one creator. Manual groups untouched."""
    models = (
        db.query(Model)
        .filter(Model.creator_id == creator_id, Model.excluded == False)  # noqa: E712
        .all()
    )

    manual_group_ids = {
        g.id for g in db.query(VariantGroup).filter(
            VariantGroup.creator_id == creator_id, VariantGroup.source == "manual"
        )
    }
    strategies = db.query(GroupingStrategy.path, GroupingStrategy.strategy).all()

    # --- eligibility (pure) ---
    by_id = {m.id: m for m in models}
    decision = select_eligible(
        (
            CandidateModel(
                id=m.id,
                folder_path=m.folder_path,
                excluded=m.excluded,
                no_group=m.no_group,
                variant_group_id=m.variant_group_id,
            )
            for m in models
        ),
        manual_group_ids,
        strategies,
    )
    candidates = [by_id[mid] for mid in decision.eligible]

    # Models under an "off" subtree may still carry automatic membership from a
    # previous run; clearing that is orchestration's job, not the policy's.
    # The manual-group check is belt-and-braces: `select_eligible` reports a
    # curated model as MANUAL_GROUP and keeps it out of `off_subtree` entirely,
    # so this can only matter if that precedence ever changes.
    off_models = [by_id[mid] for mid in decision.off_subtree]
    for m in off_models:
        if m.variant_group_id not in manual_group_ids:
            m.variant_group_id = None

    if not candidates and not off_models:
        _drop_auto_groups(db, creator_id)
        return

    stl_rows = (
        db.query(STLFile.model_id, STLFile.filename, STLFile.file_hash)
        .join(Model, STLFile.model_id == Model.id)
        .filter(Model.creator_id == creator_id)
        .all()
    )
    filenames: dict[int, set[str]] = defaultdict(set)
    hashes: dict[int, set[str]] = defaultdict(set)
    for model_id, filename, file_hash in stl_rows:
        if filename:
            filenames[model_id].add(filename.lower())
        if file_hash:
            hashes[model_id].add(file_hash)

    # `ids` is the single ordering authority for the whole pipeline (STUDIO-248):
    # every stage below iterates it, so one stable order makes evidence, clusters,
    # proposals and persistence all reproducible.
    ids = order_candidates(
        [m.id for m in candidates],
        folder_paths={m.id: m.folder_path for m in candidates},
        names={m.id: m.name for m in candidates},
    )
    hierarchy_enabled = _hierarchy_enabled(db)
    creator_name = _creator_name(db, creator_id)
    contexts: dict[int, ProductContext] = {
        mid: resolve_product_context(
            folder_path=by_id[mid].folder_path,
            character=by_id[mid].character,
            creator_name=creator_name,
        )
        for mid in ids
    } if hierarchy_enabled else {}
    boundaries = product_boundaries(contexts) if hierarchy_enabled else None
    uf = _UnionFind(ids, boundaries)
    ledger = EvidenceLedger()

    # --- hierarchy signal: same scanner-derived character envelope ---
    # It is both positive evidence and a hard boundary: the boundaries seeded
    # above stop later weak/content signals transitively bridging two
    # conflicting product envelopes.
    if hierarchy_enabled:
        _apply_evidence(uf, ledger, hierarchy_evidence(contexts))

    # --- signal 1: file_hash overlap (strongest content signal) ---
    # `boundaries` is passed for its second, quieter job (STUDIO-411): it tells
    # these signals how many distinct *products* carry a mesh or a part name, so
    # a file shared across one product's variants stays distinctive while one
    # shared across many products is still discarded as generic. With hierarchy
    # off it is None and both signals count per model exactly as they used to.
    _apply_evidence(uf, ledger, hash_evidence(ids, hashes, boundaries))

    # --- signal 2: STL filename overlap ---
    _apply_evidence(uf, ledger, filename_evidence(ids, filenames, boundaries))

    # --- signal 3: name key (baseline) ---
    # `names` and `keys` outlive this pass: cluster labelling and the
    # structural-only rejection below both read them.
    names = {mid: by_id[mid].name for mid in ids}
    keys = name_keys(ids, names, creator_name)
    _apply_evidence(uf, ledger, name_evidence(ids, keys))

    # --- signal 4: character label (weakest, STUDIO-367) ---
    # Reconciles this pipeline with the legacy startup backfill
    # (`main.py::_backfill_missing_variant_groups`), which buckets on the same
    # `character` field: once a scan can reproduce what the backfill proposes,
    # neither path keeps wiping what the other created.
    characters = {mid: by_id[mid].character for mid in ids if by_id[mid].character}
    char_keys = character_keys(ids, characters, creator_name)
    _apply_evidence(uf, ledger, character_evidence(ids, char_keys))

    # --- propose groups (pure) ---
    facts = CandidateFacts(
        names=names,
        keys=keys,
        contexts=contexts,
        explicit_reps=frozenset(mid for mid in ids if by_id[mid].is_group_rep),
        characters=characters,
        character_keys=char_keys,
    )
    proposals = propose_groups(ids, uf, ledger, facts)

    # --- materialise ---
    materialise_proposals(db, creator_id, proposals, by_id, ids)


def materialise_proposals(
    db: Session,
    creator_id: int,
    proposals: Sequence[GroupProposal],
    by_id: Mapping[int, Model],
    candidate_ids: Sequence[int],
) -> None:
    """Replace a creator's `auto` groups with `proposals` (STUDIO-247).

    The creator's previous automatic groups are dropped first, so an id is never
    reused for a different cluster and repeated runs cannot accumulate duplicates.
    Manual groups are untouched — `_drop_auto_groups` filters on
    `source == "auto"`.

    Flushes but never commits: the caller owns the transaction and can still roll
    the whole regroup back.
    """
    _drop_auto_groups(db, creator_id)

    grouped: set[int] = set()
    for proposal in proposals:
        group = VariantGroup(
            creator_id=creator_id,
            label=proposal.label,
            rep_model_id=proposal.rep_model_id,
            source="auto",
            reason=proposal.reason,
            confidence=proposal.confidence,
        )
        db.add(group)
        db.flush()
        for mid in proposal.members:
            by_id[mid].variant_group_id = group.id
            grouped.add(mid)

    # Anything the engine declined to group belongs to no auto group. This is
    # normally already true — _drop_auto_groups cleared the creator's auto
    # members, and manual members were never candidates — but stating it keeps
    # the invariant local rather than inherited.
    for mid in candidate_ids:
        if mid not in grouped:
            by_id[mid].variant_group_id = None

    db.flush()


def prune_empty_groups(db: Session) -> int:
    """Delete auto variant groups that have no (non-excluded) members. Cleans up
    orphans left by older races (#639) and is a cheap post-scan safety net. Manual
    groups are left alone — a user may have emptied one intentionally. Returns the
    number deleted.

    "Empty" only counts non-excluded members (excluded models are meant to be
    invisible), but a group whose ONLY members are excluded still has models
    pointing at it via variant_group_id. Those references are cleared before the
    group is deleted — otherwise un-excluding such a model later leaves it
    pointing at a deleted (or, worse, an id SQLite has since reused for an
    unrelated group) VariantGroup row (STUDIO-301). Un-excluding re-triggers
    regroup_creator, which will re-propose it into a fresh group anyway.
    """
    member_counts = (
        db.query(Model.variant_group_id, func.count(Model.id).label("cnt"))
        .filter(Model.excluded == False)  # noqa: E712
        .group_by(Model.variant_group_id)
        .subquery()
    )
    empties = (
        db.query(VariantGroup)
        .filter(VariantGroup.source == "auto")
        .outerjoin(member_counts, VariantGroup.id == member_counts.c.variant_group_id)
        .filter(member_counts.c.cnt == None)  # noqa: E711
        .all()
    )
    if empties:
        empty_ids = [g.id for g in empties]
        for m in db.query(Model).filter(Model.variant_group_id.in_(empty_ids)):
            m.variant_group_id = None
        for g in empties:
            db.delete(g)
        db.flush()
    return len(empties)


def _drop_auto_groups(db: Session, creator_id: int) -> None:
    """Clear variant_group_id off auto-grouped models and delete the auto groups.

    Manual groups are protected by the `source == "auto"` filter below, not by any
    caller-supplied id set: a manual group is never selected, so its members are
    never cleared.
    """
    auto_groups = (
        db.query(VariantGroup)
        .filter(VariantGroup.creator_id == creator_id, VariantGroup.source == "auto")
        .all()
    )
    auto_ids = {g.id for g in auto_groups}
    if auto_ids:
        for m in db.query(Model).filter(Model.variant_group_id.in_(auto_ids)):
            m.variant_group_id = None
        db.flush()
        for g in auto_groups:
            db.delete(g)
        db.flush()


def _creator_name(db: Session, creator_id: int) -> str | None:
    from app.models import Creator
    c = db.get(Creator, creator_id)
    return c.name if c else None

"""Variant-grouping proposal engine (#615, epic #613).

Given a creator's indexed models, propose durable variant groups by blending
four signals, strongest first:

  1. hierarchy context  — when enabled, the scanner-derived character envelope
     groups sibling packages and prevents weak signals crossing product boundaries.
  2. file_hash overlap  — two folders sharing identical meshes are almost
     certainly variants of one product (near-free: hashes already indexed on
     STLFile).
  3. STL filename overlap — folders whose STL file *names* substantially overlap
     are the same part set prepared differently (supported/unsupported/hollow…).
  4. name key            — name_parser.character_key, the existing heuristic
     (weakest on its own; the baseline when no content signal exists).

A signal is credited in a group's `reason`/`confidence` only when its evidence
edge actually connected two previously separate components (STUDIO-242). A
signal that merely re-observes an already-connected pair corroborates the
cluster but did not form it, so it takes no attribution; a pair rejected at a
hierarchy boundary takes none either.

Signals are typed (`SignalKind`) and every signal's precedence, confidence and
user-facing reason live in one table, `SIGNAL_POLICY` (STUDIO-243). Merging
edges are recorded as `Evidence` in an `EvidenceLedger`, which names the model
pair each edge describes and answers `strongest_for(members)` — the
highest-precedence signal credited to a cluster. Adding a signal means adding a
`SignalKind` plus its policy entry; a missing entry fails at import.

Note the hierarchy signal plays two distinct roles that stay separate: it is
positive evidence recorded in the ledger, and (independently) `product_key`
seeds the union-find's anti-merge boundaries, which no ledger entry can relax.

The engine derives auto groups from scratch. By default it does not read the
model's current `character` assignment; the hierarchy feature flag deliberately
adds that scanner-owned context as a constrained signal. It writes
`variant_group_id` and recreates the creator's `auto` groups each run;
`source="manual"` groups and their members are never touched. `Model.no_group`
(#678 Phase 5 — explicit
"keep me out of any group", sticky across rescans) is fully excluded from
proposals.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AppSetting, Model, STLFile, VariantGroup, GroupingStrategy
from app.services import name_parser
from app.services.product_context import ProductContext, resolve_product_context


def _norm(path: str) -> str:
    """Normalise a folder path for ancestor comparison (separators + trailing /)."""
    return path.replace("\\", "/").rstrip("/")


def _resolve_strategy(model_path: str, strategies: list[tuple[str, str]]) -> str:
    """Nearest-ancestor strategy for a model folder, defaulting to "auto".

    `strategies` is a list of (normalised_path, strategy); the longest path that is
    the model's folder or an ancestor of it wins."""
    mp = _norm(model_path)
    best_len, best = -1, "auto"
    for spath, strat in strategies:
        if (mp == spath or mp.startswith(spath + "/")) and len(spath) > best_len:
            best_len, best = len(spath), strat
    return best

# A file_hash shared by more than this many models is treated as a ubiquitous
# part (a common base, a shared support raft) and ignored for grouping — it would
# otherwise chain unrelated products together.
_HASH_BUCKET_CAP = 8

# Minimum Jaccard similarity of two models' STL filename sets to call them the
# same part set prepared differently.
_FILENAME_JACCARD = 0.6

# A filename shared by more than this many models is generic (body.stl, base.stl,
# supports.stl…) and carries no product identity — ignored for the filename
# signal so it can't chain unrelated sculpts together (#639).
_FILENAME_BUCKET_CAP = 8

# Require at least this many shared *distinct, non-generic* filenames before the
# filename signal merges two models (#639) — a single shared "body.stl" is not
# evidence of the same product.
_FILENAME_MIN_SHARED = 2

# Skip the O(n^2) filename-overlap pass for creators with more models than this,
# so a pathological creator can't stall a scan. Hash + name signals still apply.
_FILENAME_PASS_MODEL_CAP = 400

_HIERARCHY_SETTING = "hierarchy_variant_grouping_enabled"


class SignalKind(Enum):
    """The kinds of positive evidence that can merge two models (STUDIO-243)."""

    HASH = "hash"
    HIERARCHY = "hierarchy"
    FILENAME = "filename"
    NAME = "name"


@dataclass(frozen=True)
class SignalPolicy:
    """Everything a signal contributes to a proposal, in one place.

    `precedence` orders signals strongest-first (lower wins) when a cluster was
    formed by more than one kind. `reason_template` is formatted with the
    cluster's label, so a signal whose reason varies with the label needs no
    special case at the call site.
    """

    precedence: int
    confidence: float
    reason_template: str


SIGNAL_POLICY: dict[SignalKind, SignalPolicy] = {
    SignalKind.HASH: SignalPolicy(0, 0.9, "shared mesh files"),
    SignalKind.HIERARCHY: SignalPolicy(1, 0.85, "same product hierarchy"),
    SignalKind.FILENAME: SignalPolicy(2, 0.7, "shared STL file names"),
    SignalKind.NAME: SignalPolicy(3, 0.6, "name: {label}"),
}


def assert_policies_complete(policies: dict[SignalKind, SignalPolicy]) -> None:
    """Raise if any `SignalKind` lacks a policy.

    A new signal with no policy would otherwise surface as a KeyError deep in
    proposal materialisation, or worse as a silently missing reason. This runs at
    import so any test run catches it.
    """
    missing = sorted(k.name for k in SignalKind if k not in policies)
    if missing:
        raise RuntimeError(f"SIGNAL_POLICY is missing entries for: {', '.join(missing)}")


assert_policies_complete(SIGNAL_POLICY)


def policy_for(kind: SignalKind) -> SignalPolicy:
    """Look up a signal's policy, failing loudly on an unregistered kind."""
    try:
        return SIGNAL_POLICY[kind]
    except KeyError as exc:
        raise ValueError(f"no SignalPolicy registered for {kind!r}") from exc


class _MergeResult(Enum):
    """Outcome of offering one evidence edge to the union-find (STUDIO-242).

    Only ``MERGED`` means the edge actually connected two components, so only
    ``MERGED`` may credit the offering signal in the group's reason/confidence.
    ``ALREADY_CONNECTED`` is corroborating evidence, not the reason the cluster
    exists; ``REJECTED_HIERARCHY`` is not evidence at all.
    """

    MERGED = "merged"
    ALREADY_CONNECTED = "already_connected"
    REJECTED_HIERARCHY = "rejected_hierarchy"


@dataclass(frozen=True)
class Evidence:
    """One signal edge that actually merged two components (STUDIO-242/243).

    `a` and `b` are the model ids whose relationship this evidence describes, so
    a proposal's provenance can be traced back to specific pairs rather than a
    bare per-model string.
    """

    kind: SignalKind
    a: int
    b: int


class EvidenceLedger:
    """Collects merging evidence and answers which signal formed a cluster.

    Credit is first-wins per model: a model is attributed to the first signal
    whose edge pulled it into its component, matching the attribution rule from
    STUDIO-242. `strongest_for` deliberately reads that per-model credit rather
    than the raw edge list — an edge joining two components whose members were
    all already credited adds no new attribution, and reading edges directly
    would change which reason a group reports.
    """

    def __init__(self) -> None:
        self._edges: list[Evidence] = []
        self._credit: dict[int, SignalKind] = {}

    def record(self, kind: SignalKind, a: int, b: int) -> None:
        """Record an edge that merged two components under `kind`."""
        self._edges.append(Evidence(kind=kind, a=a, b=b))
        self._credit.setdefault(a, kind)
        self._credit.setdefault(b, kind)

    @property
    def edges(self) -> tuple[Evidence, ...]:
        return tuple(self._edges)

    def credit_for(self, model_id: int) -> SignalKind | None:
        return self._credit.get(model_id)

    def strongest_for(self, members: list[int]) -> SignalKind:
        """The highest-precedence signal credited to any member.

        Falls back to NAME for a cluster with no credited member — the weakest
        signal is the honest default, and it is what the pre-typed code reported.
        """
        credited = [k for k in (self._credit.get(m) for m in members) if k is not None]
        if not credited:
            return SignalKind.NAME
        return min(credited, key=lambda k: policy_for(k).precedence)


class _UnionFind:
    def __init__(self, ids: list[int], boundaries: dict[int, str | None] | None = None):
        self.parent = {i: i for i in ids}
        self.boundaries = {i: ({boundaries[i]} if boundaries and boundaries.get(i) else set()) for i in ids}

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> _MergeResult:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return _MergeResult.ALREADY_CONNECTED
        combined = self.boundaries[ra] | self.boundaries[rb]
        if len(combined) > 1:
            return _MergeResult.REJECTED_HIERARCHY
        self.parent[rb] = ra
        self.boundaries[ra] = combined
        return _MergeResult.MERGED


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

    # Models already curated into a manual group are off-limits: don't re-propose
    # them and don't disturb their group.
    manual_group_ids = {
        g.id for g in db.query(VariantGroup).filter(
            VariantGroup.creator_id == creator_id, VariantGroup.source == "manual"
        )
    }
    # Model.no_group is an explicit "ungroup this, sticky across rescans"
    # decision (#678 Phase 5) — always off-limits.
    candidates = [
        m for m in models
        if m.variant_group_id not in manual_group_ids and not m.no_group
    ]

    # Per-subtree strategy (#618): models under an "off" subtree are never
    # auto-grouped — each stays standalone. The nearest-ancestor strategy wins,
    # defaulting to "auto".
    strategies = [(_norm(p), s) for (p, s) in db.query(GroupingStrategy.path, GroupingStrategy.strategy)]
    if strategies:
        off_ids = {m.id for m in candidates if _resolve_strategy(m.folder_path, strategies) == "off"}
        off_models = [m for m in candidates if m.id in off_ids]
        candidates = [m for m in candidates if m.id not in off_ids]
        for m in off_models:
            if m.variant_group_id not in manual_group_ids:
                m.variant_group_id = None
    else:
        off_models = []

    if not candidates and not off_models:
        _drop_auto_groups(db, creator_id, manual_group_ids)
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

    ids = [m.id for m in candidates]
    hierarchy_enabled = _hierarchy_enabled(db)
    creator_name = _creator_name(db, creator_id)
    contexts: dict[int, ProductContext] = {
        m.id: resolve_product_context(
            folder_path=m.folder_path,
            character=m.character,
            creator_name=creator_name,
        )
        for m in candidates
    } if hierarchy_enabled else {}
    boundaries = {mid: contexts[mid].product_key for mid in ids} if hierarchy_enabled else None
    uf = _UnionFind(ids, boundaries)
    ledger = EvidenceLedger()

    # --- hierarchy signal: same scanner-derived character envelope ---
    # It is both positive evidence and a hard boundary: later weak/content
    # signals cannot transitively bridge two conflicting product envelopes.
    if hierarchy_enabled:
        hierarchy_index: dict[str, list[int]] = defaultdict(list)
        for mid, context in contexts.items():
            if context.product_key:
                hierarchy_index[context.product_key].append(mid)
        for bucket in hierarchy_index.values():
            if len(bucket) >= 2:
                first = bucket[0]
                for other in bucket[1:]:
                    if uf.union(first, other) is _MergeResult.MERGED:
                        ledger.record(SignalKind.HIERARCHY, first, other)

    # --- signal 1: file_hash overlap (strongest content signal) ---
    hash_index: dict[str, list[int]] = defaultdict(list)
    for mid in ids:
        for h in hashes.get(mid, ()):
            hash_index[h].append(mid)
    for bucket in hash_index.values():
        if 2 <= len(bucket) <= _HASH_BUCKET_CAP:
            first = bucket[0]
            for other in bucket[1:]:
                if uf.union(first, other) is _MergeResult.MERGED:
                    ledger.record(SignalKind.HASH, first, other)

    # --- signal 2: STL filename overlap ---
    # Drop generic filenames (shared by many models) so common part names like
    # body/base/supports.stl don't fake overlap between unrelated sculpts (#639).
    if len(ids) <= _FILENAME_PASS_MODEL_CAP:
        fname_freq: dict[str, int] = defaultdict(int)
        for mid in ids:
            for fn in filenames.get(mid, ()):
                fname_freq[fn] += 1
        distinctive = {
            mid: {fn for fn in filenames.get(mid, ()) if fname_freq[fn] <= _FILENAME_BUCKET_CAP}
            for mid in ids
        }
        for i in range(len(ids)):
            a = ids[i]
            fa = distinctive.get(a)
            if not fa:
                continue
            for j in range(i + 1, len(ids)):
                b = ids[j]
                fb = distinctive.get(b)
                if not fb:
                    continue
                inter = len(fa & fb)
                if inter >= _FILENAME_MIN_SHARED and inter / len(fa | fb) >= _FILENAME_JACCARD:
                    if uf.union(a, b) is _MergeResult.MERGED:
                        ledger.record(SignalKind.FILENAME, a, b)

    # --- signal 3: name key (baseline) ---
    key_index: dict[str, list[int]] = defaultdict(list)
    keys: dict[int, str] = {}
    by_id = {m.id: m for m in candidates}
    for mid in ids:
        key = name_parser.character_key(by_id[mid].name, _creator_name(db, creator_id))
        if key:
            keys[mid] = key
            key_index[key].append(mid)
    for bucket in key_index.values():
        if len(bucket) >= 2:
            first = bucket[0]
            for other in bucket[1:]:
                if uf.union(first, other) is _MergeResult.MERGED:
                    ledger.record(SignalKind.NAME, first, other)

    # --- materialise clusters ---
    clusters: dict[int, list[int]] = defaultdict(list)
    for mid in ids:
        clusters[uf.find(mid)].append(mid)

    _drop_auto_groups(db, creator_id, manual_group_ids)

    for members in clusters.values():
        # Don't group a cluster with no real product identity — i.e. every member
        # is a structural/junk folder ("supported", "unsupported", "STL"). These
        # only ever clustered by filename/hash; grouping + labeling them with a
        # junk name produces the duplicate "supported" groups (#639).
        if len(members) < 2 or not any(
            keys.get(mid) and not name_parser.is_structural_folder(by_id[mid].name)
            for mid in members
        ):
            for mid in members:
                by_id[mid].variant_group_id = None
            continue
        strongest = ledger.strongest_for(members)
        policy = policy_for(strongest)
        label = _label_for(members, keys, by_id, contexts)
        rep = next((m for m in members if by_id[m].is_group_rep), members[0])
        group = VariantGroup(
            creator_id=creator_id,
            label=label,
            rep_model_id=rep,
            source="auto",
            reason=policy.reason_template.format(label=label),
            confidence=policy.confidence,
        )
        db.add(group)
        db.flush()
        for mid in members:
            by_id[mid].variant_group_id = group.id

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


def _drop_auto_groups(db: Session, creator_id: int, manual_group_ids: set[int]) -> None:
    """Clear variant_group_id off auto-grouped models and delete the auto groups."""
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


def _label_for(
    members: list[int],
    keys: dict[int, str],
    by_id: dict[int, Model],
    contexts: dict[int, ProductContext],
) -> str:
    """Most common name key wins; else the first member's name."""
    hierarchy_labels = [contexts[m].display_label for m in members if m in contexts and contexts[m].display_label]
    if hierarchy_labels:
        return Counter(hierarchy_labels).most_common(1)[0][0]
    member_keys = [keys[m] for m in members if m in keys]
    if member_keys:
        return Counter(member_keys).most_common(1)[0][0]
    return by_id[members[0]].name

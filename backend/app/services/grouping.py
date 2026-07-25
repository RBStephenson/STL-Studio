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

Signal generation is fully split from orchestration (STUDIO-244, STUDIO-245).
`hierarchy_evidence`, `hash_evidence`, `filename_evidence` and `name_evidence`
are pure functions over supplied candidate data, `product_boundaries` builds the
anti-merge constraints, and `name_keys` resolves the character keys that
labelling also depends on; `_apply_evidence` offers the proposed edges to the
union-find in caller-chosen order. `regroup_creator` keeps only the database
orchestration: eligibility, evidence inputs, clustering and persistence.

Clustering and proposal building are pure too (STUDIO-246): `build_clusters`
turns merged components into member lists, and `propose_groups` returns typed
`GroupProposal` values carrying members, label, representative, signal, reason
and confidence. It creates no rows and mutates no model, so the whole pipeline
reads evidence → clusters → proposals → persistence, with `regroup_creator`
owning only the last step.

Signal ORDER remains load-bearing: an earlier merge can make a later edge
redundant or push it across a boundary, so the sequence
hierarchy → hash → filename → name must be preserved.

Proposals are deterministic (STUDIO-248). `order_candidates` sorts candidates by
`(folder_path, name, id)` and every later stage iterates that one list, so
evidence buckets, clusters, cluster members and proposals all follow from it —
never from a database plan. Two remaining encounter-order dependencies are also
pinned: each model's hashes are visited sorted, so a `set[str]`'s PYTHONHASHSEED
ordering cannot decide which merge wins at a boundary, and label ties break
alphabetically rather than by insertion. Logically identical libraries therefore
produce identical groups, whatever order their rows were inserted or returned in.

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
from collections.abc import Iterable, Mapping, Sequence
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
    the model's folder or an ancestor of it wins. Two ancestors of equal length
    are ordered by path so the winner can't depend on the row order the strategy
    query happened to return (STUDIO-248)."""
    mp = _norm(model_path)
    best_rank: tuple[int, str] | None = None
    best = "auto"
    for spath, strat in strategies:
        if mp == spath or mp.startswith(spath + "/"):
            rank = (len(spath), spath)
            if best_rank is None or rank > best_rank:
                best_rank, best = rank, strat
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
    """One signal's assertion that two models belong to the same product.

    `a` and `b` are the model ids whose relationship this evidence describes, so
    a proposal's provenance can be traced back to specific pairs rather than a
    bare per-model string (STUDIO-243).

    Evidence is *proposed* by the pure signal generators and only some of it ends
    up forming clusters: an edge may find its endpoints already connected, or be
    turned away at a product boundary. `EvidenceLedger` holds the subset that
    actually merged, which is what earns attribution (STUDIO-242).
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


def order_candidates(
    ids: Iterable[int],
    folder_paths: Mapping[int, str],
    names: Mapping[int, str],
) -> list[int]:
    """Put candidates in a stable, database-plan-independent order (STUDIO-248).

    Every later stage iterates the returned list, so this one ordering decides
    evidence bucket order, cluster order, cluster member order, and the
    positional defaults for label and representative.

    The key is `(folder_path, name, id)`. `folder_path` is unique per model and
    identifies it independently of its row id, which matters because inserting
    the same library in a different order assigns different autoincrement ids —
    an id-based sort would then produce different proposals for logically
    identical input. `id` is only a last-resort tiebreak.
    """
    return sorted(
        ids, key=lambda mid: (_norm(folder_paths[mid]), names[mid], mid)
    )


def _apply_evidence(
    uf: _UnionFind, ledger: EvidenceLedger, evidence: Iterable[Evidence]
) -> None:
    """Offer proposed evidence to the union-find, crediting only real merges.

    Order matters and is the caller's responsibility: whichever signal is offered
    first wins the attribution, and an earlier merge can make a later edge
    redundant or push it across a product boundary.
    """
    for edge in evidence:
        if uf.union(edge.a, edge.b) is _MergeResult.MERGED:
            ledger.record(edge.kind, edge.a, edge.b)


def product_boundaries(contexts: Mapping[int, ProductContext]) -> dict[int, str | None]:
    """Anti-merge constraints keyed by model id (STUDIO-244).

    A model's `product_key` is a hard boundary, not just positive evidence: no
    later signal may transitively connect two models carrying conflicting keys,
    and a model with no key cannot be used as a bridge between two that do.
    """
    return {mid: context.product_key for mid, context in contexts.items()}


def hierarchy_evidence(contexts: Mapping[int, ProductContext]) -> list[Evidence]:
    """Propose HIERARCHY edges between models sharing a `product_key`.

    Side-effect free: takes resolved contexts for the eligible candidates only,
    so models excluded upstream (manual groups, `no_group`, "off" subtrees) can
    never appear in the output.

    Each key's bucket fans out from its first member, matching the shape the
    union-find has always been offered. Bucket order follows `contexts`
    iteration order; making that ordering deterministic is STUDIO-248's job, not
    this function's, since changing it changes which merges win at boundaries.
    """
    index: dict[str, list[int]] = defaultdict(list)
    for mid, context in contexts.items():
        if context.product_key:
            index[context.product_key].append(mid)
    return [
        Evidence(kind=SignalKind.HIERARCHY, a=bucket[0], b=other)
        for bucket in index.values()
        if len(bucket) >= 2
        for other in bucket[1:]
    ]


def hash_evidence(ids: Sequence[int], hashes: Mapping[int, set[str]]) -> list[Evidence]:
    """Propose HASH edges between models sharing a `file_hash`.

    Side-effect free. Only models listed in `ids` are considered, so ineligible
    candidates never enter. A hash shared by more than `_HASH_BUCKET_CAP` models
    is a ubiquitous part (a common base, a shared support raft) and yields no
    evidence — it would otherwise chain unrelated products together.

    Bucket order is fully determined by `ids`: each model's hashes are visited in
    sorted order, so a `set[str]`'s iteration order — which varies with
    PYTHONHASHSEED between processes — cannot leak into the order edges are
    proposed, and therefore cannot change which merges win at a boundary
    (STUDIO-248).
    """
    index: dict[str, list[int]] = defaultdict(list)
    for mid in ids:
        for file_hash in sorted(hashes.get(mid, ())):
            index[file_hash].append(mid)
    return [
        Evidence(kind=SignalKind.HASH, a=bucket[0], b=other)
        for bucket in index.values()
        if 2 <= len(bucket) <= _HASH_BUCKET_CAP
        for other in bucket[1:]
    ]


def filename_evidence(
    ids: Sequence[int], filenames: Mapping[int, set[str]]
) -> list[Evidence]:
    """Propose FILENAME edges between models whose STL file names overlap.

    Two folders holding substantially the same part names are the same part set
    prepared differently (supported / unsupported / hollow…). Side-effect free;
    only models listed in `ids` are considered.

    Three guards are preserved verbatim from the inline pass:

    * a creator with more than `_FILENAME_PASS_MODEL_CAP` models yields no
      evidence at all, so the O(n^2) walk can't stall a scan. Only this signal
      is skipped — the name baseline still applies.
    * a filename shared by more than `_FILENAME_BUCKET_CAP` models is generic
      (body.stl, base.stl, supports.stl…) and is dropped before comparison, so
      common part names can't fake overlap between unrelated sculpts (#639).
    * a pair needs at least `_FILENAME_MIN_SHARED` distinctive names in common
      *and* a Jaccard similarity of at least `_FILENAME_JACCARD`; one shared
      name is never enough on its own.
    """
    if len(ids) > _FILENAME_PASS_MODEL_CAP:
        return []

    frequency: dict[str, int] = defaultdict(int)
    for mid in ids:
        for filename in filenames.get(mid, ()):
            frequency[filename] += 1
    distinctive = {
        mid: {fn for fn in filenames.get(mid, ()) if frequency[fn] <= _FILENAME_BUCKET_CAP}
        for mid in ids
    }

    evidence: list[Evidence] = []
    for i, a in enumerate(ids):
        fa = distinctive.get(a)
        if not fa:
            continue
        for b in ids[i + 1 :]:
            fb = distinctive.get(b)
            if not fb:
                continue
            shared = len(fa & fb)
            if shared >= _FILENAME_MIN_SHARED and shared / len(fa | fb) >= _FILENAME_JACCARD:
                evidence.append(Evidence(kind=SignalKind.FILENAME, a=a, b=b))
    return evidence


def name_keys(
    ids: Sequence[int], names: Mapping[int, str], creator_name: str | None
) -> dict[int, str]:
    """Resolve each model's `character_key`, skipping models with no key.

    Creator identity is supplied rather than queried, so this stays pure and the
    caller resolves the creator once (STUDIO-245). The returned keys are reused
    downstream for cluster labelling and the structural-only rejection, not just
    for evidence.
    """
    keys: dict[int, str] = {}
    for mid in ids:
        key = name_parser.character_key(names[mid], creator_name)
        if key:
            keys[mid] = key
    return keys


def name_evidence(ids: Sequence[int], keys: Mapping[int, str]) -> list[Evidence]:
    """Propose NAME edges between models sharing a `character_key`.

    The weakest signal and the baseline when no content signal exists.
    Side-effect free; keyless models simply never appear in a bucket.
    """
    index: dict[str, list[int]] = defaultdict(list)
    for mid in ids:
        key = keys.get(mid)
        if key:
            index[key].append(mid)
    return [
        Evidence(kind=SignalKind.NAME, a=bucket[0], b=other)
        for bucket in index.values()
        if len(bucket) >= 2
        for other in bucket[1:]
    ]


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


@dataclass(frozen=True)
class CandidateFacts:
    """Per-model facts the proposal stage needs, free of ORM objects (STUDIO-246).

    `names` and `keys` cover every eligible candidate; `contexts` is populated
    only when hierarchy grouping is enabled. `explicit_reps` holds the models a
    user has pinned as their group's representative, which outranks any
    positional default.
    """

    names: Mapping[int, str]
    keys: Mapping[int, str]
    contexts: Mapping[int, ProductContext]
    explicit_reps: frozenset[int]


@dataclass(frozen=True)
class GroupProposal:
    """A variant group the engine wants to exist, with its full provenance.

    Purely computed — proposing one creates no `VariantGroup` row and touches no
    model. Persisting it is the caller's job.
    """

    members: tuple[int, ...]
    label: str
    rep_model_id: int
    signal: SignalKind
    reason: str
    confidence: float


def build_clusters(ids: Sequence[int], uf: _UnionFind) -> list[list[int]]:
    """Group model ids by their union-find component.

    Clusters come back in the order their roots are first met walking `ids`, and
    members in `ids` order — the order proposals, and therefore persisted groups,
    are created in. With `ids` ordered by `order_candidates`, that whole chain is
    reproducible.
    """
    clusters: dict[int, list[int]] = defaultdict(list)
    for mid in ids:
        clusters[uf.find(mid)].append(mid)
    return list(clusters.values())


def _has_product_identity(members: Sequence[int], facts: CandidateFacts) -> bool:
    """True if any member is a real product rather than a structural folder.

    A cluster whose every member is a structural/junk folder ("supported",
    "unsupported", "STL") has no product identity. Those only ever cluster by
    filename or hash, and grouping them under a junk label is what produced the
    duplicate "supported" groups in #639.
    """
    return any(
        facts.keys.get(mid) and not name_parser.is_structural_folder(facts.names[mid])
        for mid in members
    )


def _most_common(values: Sequence[str]) -> str:
    """The most frequent value, breaking ties alphabetically (STUDIO-248).

    `Counter.most_common` resolves ties by insertion order, which makes a label
    depend on the order members happened to be visited in.
    """
    counts = Counter(values)
    return min(counts, key=lambda value: (-counts[value], value))


def select_label(members: Sequence[int], facts: CandidateFacts) -> str:
    """Label a cluster: hierarchy label, else most common name key, else a name.

    Preference order is unchanged from the original `_label_for`; only tie
    resolution is now defined (see `_most_common`).
    """
    hierarchy_labels = [
        facts.contexts[mid].display_label
        for mid in members
        if mid in facts.contexts and facts.contexts[mid].display_label
    ]
    if hierarchy_labels:
        return _most_common(hierarchy_labels)
    member_keys = [facts.keys[mid] for mid in members if mid in facts.keys]
    if member_keys:
        return _most_common(member_keys)
    return facts.names[members[0]]


def select_representative(members: Sequence[int], facts: CandidateFacts) -> int:
    """The cluster's representative: a user-pinned member, else the first.

    An explicit `is_group_rep` choice always wins over the positional default.
    """
    return next((mid for mid in members if mid in facts.explicit_reps), members[0])


def propose_groups(
    ids: Sequence[int],
    uf: _UnionFind,
    ledger: EvidenceLedger,
    facts: CandidateFacts,
) -> list[GroupProposal]:
    """Turn merged components into typed proposals (STUDIO-246).

    Side-effect free: no `VariantGroup` row is created and no model is mutated.
    Singletons and clusters with no product identity yield no proposal, so any
    model absent from the returned members belongs to no auto group.

    Each proposal's reason and confidence come from the strongest signal that
    actually merged its members, via the `SIGNAL_POLICY` table.
    """
    proposals: list[GroupProposal] = []
    for members in build_clusters(ids, uf):
        if len(members) < 2 or not _has_product_identity(members, facts):
            continue
        signal = ledger.strongest_for(members)
        policy = policy_for(signal)
        label = select_label(members, facts)
        proposals.append(
            GroupProposal(
                members=tuple(members),
                label=label,
                rep_model_id=select_representative(members, facts),
                signal=signal,
                reason=policy.reason_template.format(label=label),
                confidence=policy.confidence,
            )
        )
    return proposals


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

    by_id = {m.id: m for m in candidates}
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
    _apply_evidence(uf, ledger, hash_evidence(ids, hashes))

    # --- signal 2: STL filename overlap ---
    _apply_evidence(uf, ledger, filename_evidence(ids, filenames))

    # --- signal 3: name key (baseline) ---
    # `names` and `keys` outlive this pass: cluster labelling and the
    # structural-only rejection below both read them.
    names = {mid: by_id[mid].name for mid in ids}
    keys = name_keys(ids, names, creator_name)
    _apply_evidence(uf, ledger, name_evidence(ids, keys))

    # --- propose groups (pure) ---
    facts = CandidateFacts(
        names=names,
        keys=keys,
        contexts=contexts,
        explicit_reps=frozenset(mid for mid in ids if by_id[mid].is_group_rep),
    )
    proposals = propose_groups(ids, uf, ledger, facts)

    # --- persist ---
    _drop_auto_groups(db, creator_id, manual_group_ids)

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
    for mid in ids:
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

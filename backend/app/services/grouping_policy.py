"""Pure variant-grouping policy (epic STUDIO-238, split out in STUDIO-247).

Everything here computes what automatic grouping *wants* to do, given plain
Python inputs. Nothing in this module touches a database session, an ORM model,
or the filesystem — `app.services.grouping` owns all of that and calls into here.
That boundary is enforced by a test, not just convention: see
`tests/test_grouping_policy.py`.

The pipeline runs in four stages, each pure and independently testable:

  1. eligibility   — `select_eligible` decides which models grouping may touch,
     rejecting excluded models, manual-group members, `no_group` pins and `off`
     subtrees (STUDIO-241).
  2. evidence      — `hierarchy_evidence`, `hash_evidence`, `filename_evidence`
     and `name_evidence` propose `Evidence` edges from candidate data, while
     `product_boundaries` builds the hierarchy anti-merge constraints
     (STUDIO-244, STUDIO-245).
  3. clustering    — `_apply_evidence` offers edges to a constrained union-find
     and records the merges that actually happened in an `EvidenceLedger`;
     `build_clusters` turns components into member lists (STUDIO-242).
  4. proposals     — `propose_groups` returns typed `GroupProposal` values with
     members, label, representative, signal, reason and confidence (STUDIO-246).

Four invariants hold across all of it:

* **Signal precedence and metadata live in one table**, `SIGNAL_POLICY`. Adding a
  signal means adding a `SignalKind` and its policy entry; a missing entry fails
  at import (STUDIO-243).
* **Only evidence that actually merged two components earns attribution.** An
  edge whose endpoints were already connected corroborates a cluster but did not
  form it, and a pair rejected at a product boundary is not evidence at all
  (STUDIO-242).
* **Signal ORDER is load-bearing.** An earlier merge can make a later edge
  redundant or push it across a boundary, so callers must offer evidence in the
  order hierarchy → hash → filename → name.
* **Output is deterministic.** `order_candidates` sorts candidates by
  `(folder_path, name, id)` and every later stage iterates that one list; hashes
  are visited sorted so a `set[str]`'s PYTHONHASHSEED ordering cannot decide a
  boundary rejection; label ties break alphabetically (STUDIO-248).

The hierarchy signal deliberately plays two separate roles: positive evidence in
the ledger, and independently the `product_key` seeding of the union-find's
anti-merge boundaries, which no ledger entry can relax.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Container, Iterable, Mapping, Sequence
from itertools import combinations
from dataclasses import dataclass
from enum import Enum, StrEnum

from app.services import name_parser
from app.services.grouping_strategy import (
    SubtreeStrategy,
    normalize_path,
    resolve_subtree_strategy,
)
from app.services.product_context import ProductContext


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
        ids, key=lambda mid: (normalize_path(folder_paths[mid]), names[mid], mid)
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

    Each key's bucket fans out from its first member (kept as a star pattern
    deliberately, not switched to pairwise like `hash_evidence` — STUDIO-300
    considered it, but a hierarchy bucket's members all share the identical
    `product_key` by construction, so this function can never actually reject
    a same-bucket pair; pairwise here would only add an uncapped O(k²) cost
    for a creator with many same-key variants, with no correctness upside).
    Bucket order follows `contexts` iteration order; making that ordering
    deterministic is STUDIO-248's job, not this function's, since changing it
    changes which merges win at boundaries.
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

    Every pairwise edge within a bucket is proposed, not just edges from the
    first member (STUDIO-300). Structural hardening, not a fix for an observed
    loss: given this pipeline's ordering (hierarchy always resolves same-key
    pairs before this function runs), a star-from-first pattern was checked
    exhaustively and never found to drop a reachable merge — but a future
    reorder or a partial-compatibility boundary check could make it reachable,
    and buckets are capped at `_HASH_BUCKET_CAP` so the O(k²) pair count stays
    small regardless.
    """
    index: dict[str, list[int]] = defaultdict(list)
    for mid in ids:
        for file_hash in sorted(hashes.get(mid, ())):
            index[file_hash].append(mid)
    return [
        Evidence(kind=SignalKind.HASH, a=a, b=b)
        for bucket in index.values()
        if 2 <= len(bucket) <= _HASH_BUCKET_CAP
        for a, b in combinations(bucket, 2)
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

    Fans out from the bucket's first member, kept as a star pattern
    deliberately (STUDIO-300 considered switching to pairwise like
    `hash_evidence`, but a name-key bucket has no size cap — a creator with
    hundreds of variants of one popular character is a real shape — so
    pairwise's uncapped O(k²) cost isn't worth paying for a correctness gain
    that a full enumeration of this pipeline's reachable states never found).
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


@dataclass(frozen=True)
class CandidateModel:
    """The fields eligibility needs from a model, and nothing more (STUDIO-241).

    A projection rather than an ORM row, so the policy below is testable without
    a database or persisted groups.
    """

    id: int
    folder_path: str
    excluded: bool
    no_group: bool
    variant_group_id: int | None


class IneligibilityReason(StrEnum):
    """Why a model was kept out of automatic grouping.

    Reported in the order the rules are evaluated: a model that trips several
    reports the first. All four have the same effect — no proposal may contain
    the model — so precedence affects diagnostics, never behaviour.
    """

    EXCLUDED = "excluded"
    MANUAL_GROUP = "manual_group"
    NO_GROUP = "no_group"
    OFF_SUBTREE = "off_subtree"


@dataclass(frozen=True)
class EligibilityDecision:
    """Who may be grouped, plus what orchestration still has to write.

    `off_subtree` is separate from the rest of `reasons` because it is the one
    ineligibility that needs a database write: those models may still carry stale
    automatic membership from a previous run, which the persistence layer clears.
    The other three were never eligible to begin with.
    """

    eligible: tuple[int, ...]
    off_subtree: tuple[int, ...]
    reasons: Mapping[int, IneligibilityReason]


def select_eligible(
    models: Iterable[CandidateModel],
    manual_group_ids: Container[int],
    strategies: Sequence[tuple[str, str]],
) -> EligibilityDecision:
    """Decide which models automatic grouping may touch (STUDIO-241).

    Four rules, in evaluation order:

    * `excluded` — the model is meant to be invisible. Production also filters
      these out in SQL so they are never loaded; the rule is repeated here so it
      is expressed in policy and testable without a database, not because the
      query is unreliable.
    * a member of one of this creator's `manual_group_ids` — the user curated it,
      so neither re-propose it nor disturb its group.
    * `no_group` — an explicit, sticky "keep me out of any group" decision
      (#678 Phase 5). It outranks every signal because such a model never becomes
      a candidate, so no evidence can reach it.
    * a model under an `off` subtree (#618) stays standalone. With no strategies
      configured at all this rule cannot fire, matching the previous fast path.

    Side-effect free: nothing here mutates a model or touches the session.
    """
    eligible: list[int] = []
    off_subtree: list[int] = []
    reasons: dict[int, IneligibilityReason] = {}

    for model in models:
        if model.excluded:
            reasons[model.id] = IneligibilityReason.EXCLUDED
        elif model.variant_group_id in manual_group_ids:
            reasons[model.id] = IneligibilityReason.MANUAL_GROUP
        elif model.no_group:
            reasons[model.id] = IneligibilityReason.NO_GROUP
        elif strategies and (
            resolve_subtree_strategy(model.folder_path, strategies) is SubtreeStrategy.OFF
        ):
            reasons[model.id] = IneligibilityReason.OFF_SUBTREE
            off_subtree.append(model.id)
        else:
            eligible.append(model.id)

    return EligibilityDecision(
        eligible=tuple(eligible),
        off_subtree=tuple(off_subtree),
        reasons=reasons,
    )

"""Variant-grouping proposal engine (#615, epic #613).

Given a creator's indexed models, propose durable variant groups by blending
three signals, strongest first:

  1. file_hash overlap  — two folders sharing identical meshes are almost
     certainly variants of one product (strongest, near-free: hashes already
     indexed on STLFile).
  2. STL filename overlap — folders whose STL file *names* substantially overlap
     are the same part set prepared differently (supported/unsupported/hollow…).
  3. name key            — name_parser.character_key, the existing heuristic
     (weakest on its own; the baseline when no content signal exists).

The engine derives groups from scratch from these signals — it deliberately
does NOT read the model's current `character` assignment, so it can correct the
name heuristic rather than merely mirror it. It writes `variant_group_id` and
recreates the creator's `auto` groups each run; `source="manual"` groups and
their members are never touched.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from app.models import Model, STLFile, VariantGroup, GroupOverride, GroupingStrategy
from app.services import name_parser


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

# Skip the O(n^2) filename-overlap pass for creators with more models than this,
# so a pathological creator can't stall a scan. Hash + name signals still apply.
_FILENAME_PASS_MODEL_CAP = 400

_CONFIDENCE = {"hash": 0.9, "filename": 0.7, "name": 0.6}


class _UnionFind:
    def __init__(self, ids: list[int]):
        self.parent = {i: i for i in ids}

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


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
    # Models the user has manually grouped/moved/ungrouped (a GroupOverride row)
    # are off-limits too — their grouping is a deliberate decision the proposal
    # engine must not overturn on rescan.
    override_paths = {
        p for (p,) in db.query(GroupOverride.path).filter(
            GroupOverride.path.in_([m.folder_path for m in models])
        )
    }
    candidates = [
        m for m in models
        if m.variant_group_id not in manual_group_ids and m.folder_path not in override_paths
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
    uf = _UnionFind(ids)
    signal: dict[int, str] = {}  # model_id -> strongest signal that merged it

    # --- signal 1: file_hash overlap (strongest) ---
    hash_index: dict[str, list[int]] = defaultdict(list)
    for mid in ids:
        for h in hashes.get(mid, ()):
            hash_index[h].append(mid)
    for bucket in hash_index.values():
        if 2 <= len(bucket) <= _HASH_BUCKET_CAP:
            first = bucket[0]
            for other in bucket[1:]:
                uf.union(first, other)
                signal[first] = signal[other] = "hash"

    # --- signal 2: STL filename overlap ---
    if len(ids) <= _FILENAME_PASS_MODEL_CAP:
        for i in range(len(ids)):
            a = ids[i]
            fa = filenames.get(a)
            if not fa:
                continue
            for j in range(i + 1, len(ids)):
                b = ids[j]
                fb = filenames.get(b)
                if not fb:
                    continue
                inter = len(fa & fb)
                if inter and inter / len(fa | fb) >= _FILENAME_JACCARD:
                    uf.union(a, b)
                    signal.setdefault(a, "filename")
                    signal.setdefault(b, "filename")

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
                uf.union(first, other)
                signal.setdefault(first, "name")
                signal.setdefault(other, "name")

    # --- materialise clusters ---
    clusters: dict[int, list[int]] = defaultdict(list)
    for mid in ids:
        clusters[uf.find(mid)].append(mid)

    _drop_auto_groups(db, creator_id, manual_group_ids)

    for members in clusters.values():
        if len(members) < 2:
            for mid in members:
                by_id[mid].variant_group_id = None
            continue
        strongest = _strongest_signal(members, signal)
        label = _label_for(members, keys, by_id)
        rep = next((m for m in members if by_id[m].is_group_rep), members[0])
        group = VariantGroup(
            creator_id=creator_id,
            label=label,
            rep_model_id=rep,
            source="auto",
            reason=_reason_for(strongest, members, keys, label),
            confidence=_CONFIDENCE[strongest],
        )
        db.add(group)
        db.flush()
        for mid in members:
            by_id[mid].variant_group_id = group.id

    db.flush()


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


def _strongest_signal(members: list[int], signal: dict[int, str]) -> str:
    present = {signal.get(m) for m in members} - {None}
    for s in ("hash", "filename", "name"):
        if s in present:
            return s
    return "name"


def _label_for(members: list[int], keys: dict[int, str], by_id: dict[int, Model]) -> str:
    """Most common name key among members, else the first member's name."""
    member_keys = [keys[m] for m in members if m in keys]
    if member_keys:
        return Counter(member_keys).most_common(1)[0][0]
    return by_id[members[0]].name


def _reason_for(signal: str, members: list[int], keys: dict[int, str], label: str) -> str:
    if signal == "hash":
        return "shared mesh files"
    if signal == "filename":
        return "shared STL file names"
    return f"name: {label}"

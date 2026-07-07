"""
Library reorganize — Phase 1 preview manifest builder (#323).

Computes, for every model, where its files *would* move under a destination
template — without touching disk. The output is a durable manifest that Phase 2
(#324) will execute and verify against, so correctness and the safety flags here
are load-bearing, not cosmetic.

Path handling: everything is compared and stored with ``/`` separators and NFC
normalization. Case-insensitive collision keys use ``str.casefold()`` rather
than ``os.path.normcase`` — normcase is identity on POSIX (the test/CI host), so
relying on it would silently disable case-collision detection there.
"""
import os
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, joinedload

from app.models import (
    ImportSourceMapping,
    Model,
    PackOverride,
    ScanRoot,
)
from app.services.path_sanitize import path_over_length, sanitize_segment
from app.services.reorganize_template import parse_template, render_segments

UNKNOWN_CREATOR = "_Unknown Creator"
UNKNOWN_CHARACTER = "_Unknown Character"


def _canon(path: str) -> str:
    """NFC-normalize, switch to ``/`` separators, drop a trailing slash.

    Case-preserving — the canonical *display/compare* form. Pair with
    :func:`_key` for case-insensitive comparison.
    """
    s = unicodedata.normalize("NFC", path or "").replace("\\", "/")
    while "//" in s:
        s = s.replace("//", "/")
    if len(s) > 1:
        s = s.rstrip("/")
    return s


def _key(path: str) -> str:
    """Case-insensitive collision/identity key for a canonical path."""
    return _canon(path).casefold()


def _parent(path: str) -> str:
    c = _canon(path)
    return c.rsplit("/", 1)[0] if "/" in c else ""


@dataclass
class FileMove:
    stl_file_id: int
    current_path: str
    proposed_path: str
    size_bytes: int
    mtime_ns: int
    content_hash: str | None
    fingerprint_method: str
    # Source file unreadable/absent at preview time. A zeroed (size, mtime) is
    # then a sentinel, not a real fingerprint — Phase 2's drift check can't
    # distinguish "gone" from "matches" without this flag, so the move is unsafe.
    missing_file: bool


@dataclass
class Entry:
    model_id: int
    model_name: str
    files: list[FileMove]
    kind: str
    proposed_dir: str
    eligible: bool
    pack_override_paths: list[str]
    collision: bool
    collision_kind: str
    collision_with: list[int]
    unclassifiable: bool
    missing_fields: list[str]
    over_length: bool
    reserved_name: bool
    overlaps_other: bool
    spans_multiple_dirs: bool
    is_symlink: bool
    escapes_scan_root: bool
    missing_files_on_disk: bool


@dataclass
class Manifest:
    template: str
    entries: list[Entry]
    # collision keys are computed during build; kept for the stats pass
    _root_keys: list[str] = field(default_factory=list)


def _scan_root_for(model_dir_key: str, root_keys: list[tuple[str, str]]) -> str | None:
    """Return the canonical scan-root path whose tree contains ``model_dir_key``.

    ``root_keys`` is a list of (canonical_root, casefold_root) pairs.
    """
    for canon_root, key_root in root_keys:
        if model_dir_key == key_root or model_dir_key.startswith(key_root + "/"):
            return canon_root
    return None


def _stat_file(path: str) -> tuple[int, int, bool, bool]:
    """Return (size_bytes, mtime_ns, is_symlink, missing).

    On a missing/unreadable source the (size, mtime) are zeroed *and* missing is
    True, so callers don't mistake the sentinel for a real fingerprint.
    """
    try:
        is_link = os.path.islink(path)
        st = os.stat(path)
        return st.st_size, st.st_mtime_ns, is_link, False
    except OSError:
        return 0, 0, False, True


def build_manifest(
    db: Session,
    template: str | None,
    root_id: int | None = None,
    overrides: dict[int, dict] | None = None,
    inbox_source: str | None = None,
    slugify_title: bool = False,
    slugify_all: bool = False,
    model_ids: list[int] | None = None,
) -> Manifest:
    """Build the reorganize preview manifest. Raises ReorganizeTemplateError on
    a malformed template (caller maps to 4xx).

    ``overrides`` (Phase 2c) maps a model_id to user resolutions for that entry:
    ``creator`` / ``character`` / ``title`` substitutions (fix unclassifiable) and
    an optional ``suffix`` appended to the title segment (dodge a collision /
    shorten an over-length or reserved name). A regenerated manifest with
    overrides is a fresh artifact with its own fingerprint baseline.

    ``slugify_all`` renders every segment lowercase/hyphenated (import-style),
    overriding the narrower ``slugify_title`` (title-only) used by inbox import.
    ``model_ids``, when given, restricts the built entries to those models —
    the collision/overlap passes then only run over that subset."""
    overrides = overrides or {}
    segments = parse_template(template)
    canonical_template = "/".join(segments)

    roots_q = db.query(ScanRoot)
    if root_id is not None:
        roots_q = roots_q.filter(ScanRoot.id == root_id)
    root_keys = [(_canon(r.path), _key(r.path)) for r in roots_q.all() if r.path]

    # Managed destination root for inbox models: they live outside every scan
    # root, so they can't anchor their proposed path to a containing root the way
    # in-library models do. Default anchor is the primary (first enabled) scan
    # root; a source→library mapping overrides it per model (#453). None when no
    # roots exist (then inbox models stay ineligible: nowhere to move them).
    primary_dest = None
    primary = (
        db.query(ScanRoot)
        .filter(ScanRoot.enabled == True)  # noqa: E712
        .order_by(ScanRoot.id)
        .first()
    )
    if primary and primary.path:
        primary_dest = _canon(primary.path)

    # Source→library destination map (#453): canon(source_path) → canon(library
    # path). An inbox model resolves to the library of its longest-matching
    # source ancestor, falling back to the primary root.
    src_lib = [
        (_key(sp), _canon(lp))
        for (sp, lp) in (
            db.query(ImportSourceMapping.source_path, ScanRoot.path)
            .join(ScanRoot, ImportSourceMapping.library_id == ScanRoot.id)
            .all()
        )
        if sp and lp
    ]

    def _dest_for(m: Model) -> str | None:
        if not m.is_inbox:
            return None
        mk = _key(m.folder_path or "")
        best_len, best = -1, None
        for skey, lib in src_lib:
            if (mk == skey or mk.startswith(skey + "/")) and len(skey) > best_len:
                best_len, best = len(skey), lib
        return best if best is not None else primary_dest

    pack_paths = [_canon(p) for (p,) in db.query(PackOverride.path).all() if p]

    models_q = (
        db.query(Model)
        .options(joinedload(Model.creator), joinedload(Model.stl_files))
    )
    if inbox_source is not None:
        # Scoped import apply (#453): only inbox models under this source folder.
        skey = _key(inbox_source)
        models = [
            m for m in models_q.filter(Model.is_inbox == True).all()  # noqa: E712
            if _key(m.folder_path or "") == skey or _key(m.folder_path or "").startswith(skey + "/")
        ]
    elif root_id is not None:
        # Limit to models physically under the selected root.
        root_canons = [c for c, _ in root_keys]
        models = [
            m for m in models_q.all()
            if any(_key(m.folder_path or "").startswith(rk + "/") or _key(m.folder_path or "") == rk
                   for _, rk in root_keys)
        ] if root_canons else []
    else:
        models = models_q.all()

    if model_ids is not None:
        wanted = set(model_ids)
        models = [m for m in models if m.id in wanted]

    entries: list[Entry] = []
    for m in models:
        entries.append(_build_entry(m, segments, root_keys, pack_paths,
                                    overrides.get(m.id), _dest_for(m),
                                    slugify_title=slugify_title,
                                    slugify_all=slugify_all))

    _detect_collisions(entries)
    _detect_overlaps(entries)
    return Manifest(template=canonical_template, entries=entries, _root_keys=[k for _, k in root_keys])


def _build_entry(
    m: Model,
    segments: list[str],
    root_keys: list[tuple[str, str]],
    pack_paths: list[str],
    override: dict | None = None,
    dest_root: str | None = None,
    slugify_title: bool = False,
    slugify_all: bool = False,
) -> Entry:
    # User resolutions (Phase 2c) take precedence over model metadata and clear
    # the corresponding 'missing' flag.
    override = override or {}
    ov_creator = (override.get("creator") or "").strip()
    ov_character = (override.get("character") or "").strip()
    ov_title = (override.get("title") or "").strip()
    ov_suffix = (override.get("suffix") or "").strip()

    # Fields actually referenced in the template — only flag missing for these.
    used_fields = {
        f for seg in segments
        for f in ("creator", "character", "title")
        if ("{" + f + "}") in seg.lower()
    }

    # Resolve template field values, tracking which fell back to a sentinel.
    missing: list[str] = []
    creator_name = ov_creator or (m.creator.name if m.creator else "") or ""
    if not creator_name:
        creator_name = UNKNOWN_CREATOR
        if "creator" in used_fields:
            missing.append("creator")
    character = ov_character or m.character or ""
    if not character:
        character = UNKNOWN_CHARACTER
        if "character" in used_fields:
            missing.append("character")
    title = ov_title or m.title or m.name or ""
    if not (ov_title or (m.title or "").strip()):
        # title fell back to folder name — only 'missing' if that's also empty
        if not (m.name or "").strip() and "title" in used_fields:
            missing.append("title")
    # Suffix dodges a collision / shortens an over-length or reserved name.
    if ov_suffix:
        title = f"{title} {ov_suffix}"

    values = {"creator": creator_name, "character": character, "title": title}
    rendered = render_segments(segments, values)

    reserved = False
    over_len = False
    safe_parts: list[str] = []
    for raw_seg, part in zip(segments, rendered):
        # slugify_all lowercases/hyphenates every segment (import-style);
        # slugify_title narrows that to just the {title} segment.
        do_slug = slugify_all or (slugify_title and "{title}" in raw_seg.lower())
        sani = sanitize_segment(part, slugify=do_slug)
        reserved = reserved or sani.reserved_name
        over_len = over_len or sani.over_length
        safe_parts.append(sani.value)

    current_dir = _canon(m.folder_path or "")
    cur_key = _key(m.folder_path or "")
    scan_root = _scan_root_for(cur_key, root_keys)

    # Inbox models live outside every scan root, so they anchor at the managed
    # destination root rather than a containing root. In-library models anchor at
    # the scan root that contains them (current behaviour).
    anchor = dest_root if m.is_inbox else scan_root

    # Destination is anchored at the resolved root; if we can't place it under a
    # known root we still render a relative proposal but flag the escape.
    if anchor:
        proposed_dir = _canon(anchor + "/" + "/".join(safe_parts))
    else:
        proposed_dir = _canon("/".join(safe_parts))

    over_len = over_len or path_over_length(proposed_dir)

    # Per-file moves + fingerprints.
    files: list[FileMove] = []
    src_dirs: set[str] = set()
    is_symlink = False
    missing_files_on_disk = False
    for f in m.stl_files:
        size, mtime_ns, link, is_missing = _stat_file(f.path)
        is_symlink = is_symlink or link
        missing_files_on_disk = missing_files_on_disk or is_missing
        src_dirs.add(_key(_parent(f.path)))
        files.append(FileMove(
            stl_file_id=f.id,
            current_path=_canon(f.path),
            proposed_path=_canon(proposed_dir + "/" + (f.filename or os.path.basename(f.path or ""))),
            size_bytes=size,
            mtime_ns=mtime_ns,
            content_hash=None,
            fingerprint_method="stat",
            missing_file=is_missing,
        ))
    spans_multiple_dirs = len(src_dirs) > 1

    # Path-keyed overrides this move invalidates (under the model's folder).
    pack_refs = [p for p in pack_paths if _key(p) == cur_key or _key(p).startswith(cur_key + "/")]

    # Escape = no anchor root to place the model under. For in-library models that
    # means it sits outside every scan root; for inbox models it means there is no
    # managed destination root configured to move it into.
    if m.is_inbox:
        escapes = anchor is None
    else:
        escapes = scan_root is None and len(root_keys) > 0
    # Even with an anchor, a literal-only template or '..'-laden value could
    # escape; re-check the assembled destination stays under the anchor root.
    if anchor is not None:
        if not (_key(proposed_dir) == _key(anchor)
                or _key(proposed_dir).startswith(_key(anchor) + "/")):
            escapes = True

    kind = _classify_kind(current_dir, proposed_dir)

    unclassifiable = bool(missing)
    eligible = not (
        unclassifiable or over_len or reserved or is_symlink
        or spans_multiple_dirs or escapes or missing_files_on_disk
    )

    return Entry(
        model_id=m.id,
        model_name=m.name or "",
        files=files,
        kind=kind,
        proposed_dir=proposed_dir,
        eligible=eligible,
        pack_override_paths=pack_refs,
        collision=False,
        collision_kind="none",
        collision_with=[],
        unclassifiable=unclassifiable,
        missing_fields=missing,
        over_length=over_len,
        reserved_name=reserved,
        overlaps_other=False,
        spans_multiple_dirs=spans_multiple_dirs,
        is_symlink=is_symlink,
        escapes_scan_root=escapes,
        missing_files_on_disk=missing_files_on_disk,
    )


def creator_scan_dir(
    db: Session, template: str | None, creator_name: str, slugify: bool = True,
) -> str | None:
    """The on-disk directory a brand-new creator's folder should live in.

    Renders only the template segments up to and including the first one that
    references ``{creator}``, anchored at the primary enabled scan root.
    ``slugify`` mirrors the library's ``reorganize_slugify`` setting — when
    off, the creator name keeps its original casing/spacing (still made
    filesystem-safe). Returns ``None`` when the template doesn't reference
    ``{creator}``, an earlier segment needs ``{character}``/``{title}`` (not
    available for a bare creator), or there's no scan root to anchor to.
    """
    segments = parse_template(template)
    idx = next((i for i, seg in enumerate(segments) if "{creator}" in seg.lower()), None)
    if idx is None:
        return None
    lead = segments[: idx + 1]
    other_fields = {
        f for seg in lead for f in ("character", "title")
        if ("{" + f + "}") in seg.lower()
    }
    if other_fields:
        return None

    primary = (
        db.query(ScanRoot)
        .filter(ScanRoot.enabled == True)  # noqa: E712
        .order_by(ScanRoot.id)
        .first()
    )
    if not primary or not primary.path:
        return None

    rendered = render_segments(lead, {"creator": creator_name})
    parts = [sanitize_segment(p, slugify=slugify).value for p in rendered]
    return _canon(_canon(primary.path) + "/" + "/".join(parts))


def _classify_kind(current_dir: str, proposed_dir: str) -> str:
    if _key(current_dir) == _key(proposed_dir):
        return "in_place" if current_dir == proposed_dir else "case_rename"
    if _key(_parent(current_dir)) == _key(_parent(proposed_dir)):
        return "rename"
    return "move"


def _detect_collisions(entries: list[Entry]) -> None:
    """Group entries by case-insensitive destination dir; flag and classify."""
    groups: dict[str, list[Entry]] = {}
    for e in entries:
        groups.setdefault(_key(e.proposed_dir), []).append(e)

    for group in groups.values():
        if len(group) < 2:
            continue
        raws = {e.proposed_dir for e in group}
        if len(raws) == 1:
            # Same canonical destination from distinct models — a real merge.
            kind = "legitimate_duplicate"
        elif len({r.casefold() for r in raws}) == 1:
            kind = "case_only"
        else:
            kind = "exact"
        ids = [e.model_id for e in group]
        for e in group:
            e.collision = True
            e.collision_kind = kind
            e.collision_with = [i for i in ids if i != e.model_id]
            # A merge/collision is a blocker in Phase 1.
            e.kind = "merge"
            e.eligible = False


def _detect_overlaps(entries: list[Entry]) -> None:
    """Flag entries whose source/destination overlaps or nests another's.

    Moving A into a tree that is also B's source (or destination) is unsafe to
    apply in any order, so both are flagged ineligible.

    NOTE (perf, deferred): this is O(n^2) over the manifest. Preview is I/O-bound
    (it stats every file on disk), so the quadratic string scan is not the
    bottleneck today. If apply-time scale on very large libraries proves it
    matters (Phase 2, #324), bucket entries by normalized parent-dir prefix and
    sweep once instead.
    """
    dirs: list[tuple[Entry, str, str]] = [
        (e, _key(e.proposed_dir), _key(_canon(e.files[0].current_path)) if e.files else _key(e.proposed_dir))
        for e in entries
    ]
    for i, (e, dst_i, _src_i) in enumerate(dirs):
        for j, (other, dst_j, src_j) in enumerate(dirs):
            if i == j:
                continue
            # Destination of e nests under, or contains, another's source dir.
            src_dir_j = _key(_parent(other.files[0].current_path)) if other.files else dst_j
            if _nests(dst_i, src_dir_j) or _nests(src_dir_j, dst_i):
                if e.model_id != other.model_id:
                    e.overlaps_other = True
                    e.eligible = False
                    break


def _nests(a: str, b: str) -> bool:
    """True if path a == b or a is inside b (case-insensitive keys)."""
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")

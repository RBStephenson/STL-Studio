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
import re
import time
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, joinedload

from app.models import (
    ImportSourceMapping,
    Model,
    PackOverride,
    ScanRoot,
)
from app.services.path_sanitize import path_over_length, sanitize_segment, slug_filename
from app.services.reorganize_template import VALID_FIELDS, parse_template, render_segments

UNKNOWN_CREATOR = "_Unknown Creator"
UNKNOWN_CHARACTER = "_Unknown Character"
UNKNOWN_SCALE = "_Unknown Scale"
_SCALE_TAG_RE = re.compile(r"^(\d{1,4}mm|1[:/\-_]\d{1,2})$", re.I)
_SOURCE_SUFFIX_RE = re.compile(
    r"^(?:alt(?:ernate|ernative)?|variant)(?:[\s_-].*)?$"
    r"|^v\d+(?:\.\d+)?$"
    r"|^version[\s_-]*\d+(?:\.\d+)?$",
    re.I,
)


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
    stl_file_id: int | None
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
    # "stl" repaths an STLFile row (stl_file_id set); "image" repaths one of
    # the model's own image_paths/thumbnail_path/primary_image_path instead —
    # see reorganize_apply._repath_db.
    kind: str = "stl"


@dataclass
class Entry:
    model_id: int
    model_name: str
    files: list[FileMove]
    kind: str
    source_dir: str
    proposed_dir: str
    eligible: bool
    pack_override_paths: list[str]
    collision: bool
    collision_kind: str
    collision_with: list[int]
    suggested_suffix: str | None
    unclassifiable: bool
    missing_fields: list[str]
    over_length: bool
    reserved_name: bool
    overlaps_other: bool
    spans_multiple_dirs: bool
    is_symlink: bool
    escapes_scan_root: bool
    missing_files_on_disk: bool
    locked: bool


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


# Preview-only stat cache (STUDIO-187): the Reorganize page re-previews the
# WHOLE manifest on every resolved-field edit (collision detection is
# inherently global — fixing one row can newly collide with an untouched
# one, so every proposed_dir must be recomputed and compared). But a file's
# on-disk stat never depends on override values — typing a character name
# doesn't touch the file — so re-stat'ing every file in the library on every
# keystroke is pure waste. Cached here by path alone, no override/model
# tracking needed. A short TTL (not a manifest-scoped invalidation) is the
# safety net for the rare case a file actually changes on disk mid-edit;
# Phase 2's apply-time drift check (reorganize_apply.py) has its own,
# uncached stat call and is the real safety boundary — this cache only
# feeds the read-only preview.
_STAT_CACHE_TTL = 5.0  # seconds
_stat_cache: dict[str, tuple[float, int, int, bool, bool]] = {}  # path -> (cached_at, size, mtime_ns, is_symlink, missing)


def _clear_stat_cache() -> None:
    """Test/apply hook — drop every cached entry so the next _stat_file_cached
    call re-stats from disk."""
    _stat_cache.clear()


def _stat_file_cached(path: str) -> tuple[int, int, bool, bool]:
    """TTL-cached wrapper around _stat_file — see _stat_cache's comment."""
    now = time.monotonic()
    cached = _stat_cache.get(path)
    if cached is not None and now - cached[0] < _STAT_CACHE_TTL:
        return cached[1], cached[2], cached[3], cached[4]
    result = _stat_file(path)
    _stat_cache[path] = (now, *result)
    return result


def _scale_value(auto_tags: list | None) -> str:
    """Return the first scanner scale tag, normalizing ratio separators."""
    for raw in auto_tags or []:
        tag = str(raw).strip()
        if not _SCALE_TAG_RE.match(tag):
            continue
        if tag.lower().endswith("mm"):
            return tag.lower()
        return tag.replace("/", ":").replace("-", ":").replace("_", ":")
    return ""


def build_manifest(
    db: Session,
    template: str | None,
    root_id: int | None = None,
    overrides: dict[int, dict] | None = None,
    inbox_source: str | None = None,
    slugify_title: bool = False,
    slugify_all: bool = False,
    model_ids: list[int] | None = None,
    slugify_filenames: bool = False,
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
    the collision/overlap passes then only run over that subset.

    ``slugify_filenames`` (#946) additionally renders each STL's own filename
    lowercase/hyphenated (e.g. "Cold Giant.stl" -> "cold-giant.stl") — a
    separate, independent toggle from ``slugify_all``/``slugify_title``, which
    only ever touch directory segments. Gallery image filenames are left
    untouched; this only applies to STL files."""
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
                                    slugify_all=slugify_all,
                                    slugify_filenames=slugify_filenames))

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
    slugify_filenames: bool = False,
) -> Entry:
    # User resolutions (Phase 2c) take precedence over model metadata and clear
    # the corresponding 'missing' flag.
    override = override or {}
    ov_creator = (override.get("creator") or "").strip()
    ov_character = (override.get("character") or "").strip()
    ov_scale = (override.get("scale") or "").strip()
    ov_title = (override.get("title") or "").strip()
    ov_suffix = (override.get("suffix") or "").strip()

    # Fields actually referenced in the template — only flag missing for these.
    used_fields = {
        f for seg in segments
        for f in VALID_FIELDS
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
    scale = ov_scale or _scale_value(m.auto_tags)
    if not scale:
        scale = UNKNOWN_SCALE
        if "scale" in used_fields:
            missing.append("scale")
    title = ov_title or m.title or m.name or ""
    if not (ov_title or (m.title or "").strip()):
        # title fell back to folder name — only 'missing' if that's also empty
        if not (m.name or "").strip() and "title" in used_fields:
            missing.append("title")
    # Suffix dodges a collision / shortens an over-length or reserved name.
    if ov_suffix:
        title = f"{title} {ov_suffix}"

    values = {
        "creator": creator_name,
        "character": character,
        "scale": scale,
        "title": title,
    }
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
        size, mtime_ns, link, is_missing = _stat_file_cached(f.path)
        is_symlink = is_symlink or link
        missing_files_on_disk = missing_files_on_disk or is_missing
        src_dirs.add(_key(_parent(f.path)))
        dest_filename = f.filename or os.path.basename(f.path or "")
        if slugify_filenames and dest_filename:
            dest_filename = slug_filename(dest_filename)
        files.append(FileMove(
            stl_file_id=f.id,
            current_path=_canon(f.path),
            proposed_path=_canon(proposed_dir + "/" + dest_filename),
            size_bytes=size,
            mtime_ns=mtime_ns,
            content_hash=None,
            fingerprint_method="stat",
            missing_file=is_missing,
        ))
    spans_multiple_dirs = len(src_dirs) > 1

    # Local gallery images move alongside the STLs. Scoped to images that live
    # inside the model's OWN folder tree — a gallery image inherited from a
    # shared parent folder (e.g. a character-level "renders/" dir referenced
    # by several sibling variants) is deliberately left in place, since moving
    # it would break the path for every other model still pointing at it.
    # Missing/stale entries (the file no longer exists — #854/#855) are just
    # skipped rather than treated as a blocker: a stale gallery path shouldn't
    # stop the model's STLs from being reorganized. Never counted toward
    # spans_multiple_dirs — images commonly live in their own subfolder next
    # to the STLs, and that's not the ambiguous-source-directory case that
    # check exists to catch.
    cur_prefix = cur_key + "/"

    def _owned_local_image(p: object) -> bool:
        if not isinstance(p, str) or not p or "://" in p:
            return False
        k = _key(p)
        if k != cur_key and not k.startswith(cur_prefix):
            return False
        # Never carry a hidden-directory reference along as if it were a
        # real gallery image (#903-follow-up) — e.g. a stale .manyfold
        # derivative-cache path a pre-fix scan picked up. The scanner itself
        # has stopped discovering these; carrying an already-stored one
        # through a move would relocate the junk into the organized library
        # instead of letting it fall away.
        if any(part.startswith(".") for part in _canon(p).split("/")):
            return False
        return True

    seen_image_keys: set[str] = set()
    image_candidates: list[str] = []
    for p in [*(m.image_paths or []), m.thumbnail_path, m.primary_image_path]:
        if _owned_local_image(p):
            k = _key(p)
            if k not in seen_image_keys:
                seen_image_keys.add(k)
                image_candidates.append(p)

    for p in image_candidates:
        size, mtime_ns, link, is_missing = _stat_file_cached(p)
        if is_missing:
            continue
        is_symlink = is_symlink or link
        files.append(FileMove(
            stl_file_id=None,
            current_path=_canon(p),
            proposed_path=_canon(proposed_dir + "/" + os.path.basename(p)),
            size_bytes=size,
            mtime_ns=mtime_ns,
            content_hash=None,
            fingerprint_method="stat",
            missing_file=False,
            kind="image",
        ))

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
    # A directory classified "in_place" can still have STL files that need
    # renaming (slugify_filenames on) — the frontend treats "in_place" as
    # nothing-to-do and excludes it from selection entirely, so a filename-only
    # change must not be reported as "in_place" or it would never get applied.
    # "rename" already means "no directory move needed, just a leaf name
    # change" for the directory-classification case above; reusing it here
    # covers the file-level equivalent with the same meaning.
    if kind == "in_place" and any(
        f.kind == "stl" and _key(f.current_path) != _key(f.proposed_path) for f in files
    ):
        kind = "rename"

    unclassifiable = bool(missing)
    # A locked model is never eligible, regardless of what else
    # is true about it — the lock means no process may move/rename its
    # files, full stop (#978). Distinct from every other blocker: those are
    # all "fix this and it becomes eligible" states; this one is "unlock the
    # model first," so it's checked and reported separately.
    eligible = not (
        unclassifiable or over_len or reserved or is_symlink
        or spans_multiple_dirs or escapes or missing_files_on_disk or m.locked
    )

    return Entry(
        model_id=m.id,
        model_name=m.name or "",
        files=files,
        kind=kind,
        source_dir=current_dir,
        proposed_dir=proposed_dir,
        eligible=eligible,
        pack_override_paths=pack_refs,
        collision=False,
        collision_kind="none",
        collision_with=[],
        suggested_suffix=None,
        unclassifiable=unclassifiable,
        missing_fields=missing,
        over_length=over_len,
        reserved_name=reserved,
        overlaps_other=False,
        spans_multiple_dirs=spans_multiple_dirs,
        is_symlink=is_symlink,
        escapes_scan_root=escapes,
        missing_files_on_disk=missing_files_on_disk,
        locked=m.locked,
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
    ``{creator}``, an earlier segment needs ``{character}``/``{scale}``/
    ``{title}`` (not available for a bare creator), or there's no scan root to
    anchor to.
    """
    segments = parse_template(template)
    idx = next((i for i, seg in enumerate(segments) if "{creator}" in seg.lower()), None)
    if idx is None:
        return None
    lead = segments[: idx + 1]
    other_fields = {
        f for seg in lead for f in ("character", "scale", "title")
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
            # Same canonical destination proves a collision, not duplicate content.
            kind = "same_destination"
        elif len({r.casefold() for r in raws}) == 1:
            kind = "case_only"
        else:
            kind = "exact"
        ids = [e.model_id for e in group]
        suggestions = {e.model_id: _source_suffix(e.source_dir) for e in group}
        suggestion_counts = {
            suffix: sum(1 for value in suggestions.values() if value == suffix)
            for suffix in suggestions.values()
            if suffix is not None
        }
        for e in group:
            e.collision = True
            e.collision_kind = kind
            e.collision_with = [i for i in ids if i != e.model_id]
            suggestion = suggestions[e.model_id]
            e.suggested_suffix = (
                suggestion
                if suggestion is not None and suggestion_counts[suggestion] == 1
                else None
            )
            # A merge/collision is a blocker in Phase 1.
            e.kind = "merge"
            e.eligible = False


def _source_suffix(source_dir: str) -> str | None:
    """Return a safe suffix for a strong variant-like source-folder name."""
    leaf = _canon(source_dir).rsplit("/", 1)[-1].strip()
    if not leaf or not _SOURCE_SUFFIX_RE.fullmatch(leaf):
        return None
    suffix = sanitize_segment(leaf, slugify=True).value
    return suffix or None


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

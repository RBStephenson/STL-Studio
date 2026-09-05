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
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models import (
    AppSetting,
    ImportSourceMapping,
    Model,
    PackOverride,
    ScanRoot,
)
from app.services import name_parser
from app.services.path_sanitize import path_over_length, sanitize_segment, slug_filename
from app.services.reorganize_template import (
    ReorganizeTemplateError,
    parse_template,
    render_segments,
    segment_fields,
)

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
    # the model's own image_paths/thumbnail_path/primary_image_path instead;
    # "other" repaths one of the model's own other_files entries — see
    # reorganize_apply._repath_db.
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
    source_directories: list[str]
    is_symlink: bool
    escapes_scan_root: bool
    missing_files_on_disk: bool
    locked: bool
    creator_id: int | None = None
    creator_name: str = ""
    model_ids: list[int] = field(default_factory=list)
    package_mode: bool = False
    package_name: str | None = None
    ambiguous_package: bool = False
    character_source_dir: str | None = None
    character_proposed_dir: str | None = None
    character_package_ids: list[int] = field(default_factory=list)
    character_model_ids: list[int] = field(default_factory=list)
    shared_files: list[FileMove] = field(default_factory=list)


@dataclass
class Manifest:
    # The scope's FALLBACK template in canonical form — the explicit one when the
    # caller passed one, else the app-wide setting, else the built-in default.
    # With per-root templates (STUDIO-403) that is not a promise every entry used
    # it: a root with its own template renders its models against that instead.
    # Read this as "what a model resolves to when its root has nothing of its
    # own", never as "the template this manifest used".
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
# Last time a sweep of expired entries ran (STUDIO-314) — the TTL above is
# only ever checked at read time, so without this an entry for a path that's
# never looked up again (a model moved out of the library, a one-off preview
# scope) sits in the dict forever, growing it to "every path ever touched
# this process's lifetime" instead of "paths touched recently".
_stat_cache_last_sweep = 0.0


def _clear_stat_cache() -> None:
    """Test/apply hook — drop every cached entry so the next _stat_file_cached
    call re-stats from disk."""
    global _stat_cache_last_sweep
    _stat_cache.clear()
    _stat_cache_last_sweep = 0.0


def _stat_file_cached(path: str) -> tuple[int, int, bool, bool]:
    """TTL-cached wrapper around _stat_file — see _stat_cache's comment."""
    global _stat_cache_last_sweep
    now = time.monotonic()
    cached = _stat_cache.get(path)
    if cached is not None and now - cached[0] < _STAT_CACHE_TTL:
        return cached[1], cached[2], cached[3], cached[4]
    result = _stat_file(path)
    _stat_cache[path] = (now, *result)
    # Opportunistic sweep, throttled to at most once per TTL window so this
    # doesn't turn every single stat call into an O(cache size) scan.
    if now - _stat_cache_last_sweep >= _STAT_CACHE_TTL:
        for stale_path in [p for p, entry in _stat_cache.items() if now - entry[0] >= _STAT_CACHE_TTL]:
            del _stat_cache[stale_path]
        _stat_cache_last_sweep = now
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


def _manifest_scope(
    db: Session, root_id: int | None,
) -> tuple[list[tuple[str, str]], Callable[[Model], str | None]]:
    """Scan-root keys for `root_id` (all roots when None), plus the resolver
    that picks an inbox model's managed destination root.

    Extracted from `build_manifest` (STUDIO-401): the template-preview endpoint
    needs exactly this scope, and re-deriving it there is where a preview would
    silently diverge from the real manifest for inbox models with a source
    mapping. Reads rows; touches no filesystem.
    """
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

    return root_keys, _dest_for


class TemplateResolver:
    """Which destination template applies to which model (STUDIO-403).

    Per-scan-root templates turn "the template" from a per-build question into a
    per-model one. The rule, in one line: **an explicit template applies
    uniformly across the whole scope; with no explicit template each model
    resolves through its own destination root** — that root's saved template,
    then the app-wide ``reorganize_template`` setting, then the parser's
    built-in default.

    Explicit-wins-uniformly is deliberate and is what keeps the Reorganize
    page's one-off field, and import-apply's hard-coded ``{creator}/{title}``,
    meaning exactly what they say. Anything that passes no template — the
    unorganized badge, an unmodified preview — gets per-root resolution instead,
    which is the whole feature.

    The lookup keys on a model's **anchor** root, not the root it currently sits
    in. For in-library models those are the same thing; they differ for inbox
    models, which live outside every scan root and anchor at the managed
    destination library, and there the template that matters belongs to the
    library the files are moving *into*. That mirrors ``_render_destination``'s
    own anchor choice on purpose — if the two ever disagree, a model renders
    under one root's template into a different root's tree.

    Parsing happens once per distinct template here, not once per model: a
    library with three roots parses at most four templates for a whole manifest.
    """

    def __init__(self, db: Session, explicit: str | None, root_keys: list[tuple[str, str]]):
        self._explicit = (explicit or "").strip() or None
        self._root_keys = root_keys

        fallback = self._explicit
        if fallback is None:
            row = db.get(AppSetting, "reorganize_template")
            fallback = ((row.value or "").strip() or None) if row is not None else None
        # parse_template(None) yields the built-in default — the third and last
        # level of inheritance. Resolving it here means "" and None behave
        # identically at every call site rather than at some of them.
        self._fallback_segments = parse_template(fallback)

        self._by_root: dict[str, list[str]] = {}
        if self._explicit is None:
            for r in db.query(ScanRoot).all():
                own = (r.reorganize_template or "").strip()
                if not (r.path and own):
                    continue
                try:
                    self._by_root[_canon(r.path)] = parse_template(own)
                except ReorganizeTemplateError as e:
                    # Named, because the caller turns this into a 400 the user
                    # reads. "unknown token {creater}" with no root attached is
                    # unactionable when the template they're looking at is fine
                    # and a different root's is the broken one.
                    raise ReorganizeTemplateError(f"Scan root {r.path}: {e}") from e

    @property
    def fallback_segments(self) -> list[str]:
        """What a model resolves to when its root has no template of its own."""
        return self._fallback_segments

    def segments_for_anchor(self, anchor: str | None) -> list[str]:
        if anchor is None:
            return self._fallback_segments
        return self._by_root.get(anchor, self._fallback_segments)

    def segments_for(self, m: Model, dest_root: str | None) -> list[str]:
        anchor = dest_root if m.is_inbox else _scan_root_for(_key(m.folder_path or ""), self._root_keys)
        return self.segments_for_anchor(anchor)


def _models_for_scope(
    db: Session,
    root_keys: list[tuple[str, str]],
    root_id: int | None,
    inbox_source: str | None = None,
    with_files: bool = True,
) -> list[Model]:
    """The models a manifest covers, given its scope.

    Extracted from `build_manifest` (STUDIO-401) so template-preview selects
    the same models the real preview would — the root-scoped filter below is
    subtle enough (separator forms, casefold) that a second copy would drift.

    ``with_files=False`` skips eager-loading `stl_files`. Template-preview
    renders from model metadata alone and never reads them; loading them there
    would turn a deliberately cheap endpoint into an N+1 across the library.
    """
    options = [joinedload(Model.creator)]
    if with_files:
        options.append(joinedload(Model.stl_files))
    models_q = db.query(Model).options(*options)
    if inbox_source is not None:
        # Scoped import apply (#453): only inbox models under this source folder.
        skey = _key(inbox_source)
        models = [
            m for m in models_q.filter(Model.is_inbox == True).all()  # noqa: E712
            if _key(m.folder_path or "") == skey or _key(m.folder_path or "").startswith(skey + "/")
        ]
    elif root_id is not None:
        # Limit to models physically under the selected root. A coarse SQL
        # prefix filter runs first so a root-scoped preview on a library with
        # several scan roots doesn't load (and joinedload the STL rows for)
        # every model just to discard most of them in Python (STUDIO-314) —
        # it only narrows the candidate set, though: LIKE-based prefix
        # matching isn't casefold/NFC-safe across every DB backend, so the
        # exact case-insensitive check below still runs and remains the
        # actual filter of record. Both '/' and '\' separator forms of each
        # root are matched — folder_path is stored as-is from the OS (a
        # Windows/standalone install stores backslashes), while root_keys'
        # canon form is always '/'-normalized, so matching only the canon
        # form would silently exclude every real Windows row.
        root_canons = [c for c, _ in root_keys]
        if not root_canons:
            models = []
        else:
            root_prefixes = {p for c in root_canons for p in (c, c.replace("/", "\\"))}
            like_clauses = (
                [Model.folder_path.like(p + "/%") for p in root_prefixes]
                + [Model.folder_path.like(p + "\\%") for p in root_prefixes]
                + [Model.folder_path == p for p in root_prefixes]
            )
            candidates = models_q.filter(or_(*like_clauses)).all()
            models = [
                m for m in candidates
                if any(_key(m.folder_path or "").startswith(rk + "/") or _key(m.folder_path or "") == rk
                       for _, rk in root_keys)
            ]
    else:
        models = models_q.all()

    return models


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
    preserve_packages: bool = False,
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
    root_keys, _dest_for = _manifest_scope(db, root_id)
    resolver = TemplateResolver(db, template, root_keys)
    canonical_template = "/".join(resolver.fallback_segments)

    pack_paths = [_canon(p) for (p,) in db.query(PackOverride.path).all() if p]

    models = _models_for_scope(db, root_keys, root_id, inbox_source)

    if model_ids is not None:
        wanted = set(model_ids)
        models = [m for m in models if m.id in wanted]

    if preserve_packages and inbox_source is None:
        entries = _build_package_entries(
            models, root_keys, pack_paths, overrides,
            slugify_all=slugify_all,
        )
        _attach_character_envelopes(entries)
    else:
        entries = []
        for m in models:
            dest = _dest_for(m)
            entries.append(_build_entry(m, resolver.segments_for(m, dest), root_keys, pack_paths,
                                        overrides.get(m.id), dest,
                                        slugify_title=slugify_title,
                                        slugify_all=slugify_all,
                                        slugify_filenames=slugify_filenames))

    _detect_collisions(entries)
    if inbox_source is not None:
        # Import-apply has no interactive collision-resolution step (#1087):
        # unlike the Reorganize page, a blocked entry here is a dead end for
        # the user rather than just a hint. Silently fold an available
        # suggested_suffix into the title so the import can proceed.
        entries = _auto_apply_import_suffixes(
            entries, models, resolver, root_keys, pack_paths, overrides, _dest_for,
            slugify_title=slugify_title, slugify_all=slugify_all,
            slugify_filenames=slugify_filenames,
        )
    _detect_overlaps(entries)
    return Manifest(template=canonical_template, entries=entries, _root_keys=[k for _, k in root_keys])


@dataclass
class TemplateSample:
    """One rendered row of the cheap template preview (STUDIO-401)."""
    model_id: int
    model_name: str
    source_dir: str
    proposed_dir: str
    unclassifiable: bool
    missing_fields: list[str]
    over_length: bool
    reserved_name: bool


@dataclass
class TemplatePreview:
    """Mirrors ``Manifest``'s shape: the canonical template plus its rows."""
    template: str
    samples: list[TemplateSample]


def build_template_preview(
    db: Session,
    template: str | None,
    root_id: int | None = None,
    limit: int = 5,
    slugify_all: bool = False,
) -> TemplatePreview:
    """Render ``template`` against a handful of real models, cheaply. Raises
    ReorganizeTemplateError on a malformed template (caller maps to 400).

    Deliberately NOT a manifest: no ``os.stat``, no per-file move plan, no
    collision or overlap pass, nothing persisted. It answers "what does this
    template do to my library" and nothing else.

    **The flags here cover only problems the TEMPLATE caused** — a required
    token with no value, or a rendered path that came out over-length or
    reserved. The stat-dependent blockers (symlink, missing files on disk,
    spans-multiple-dirs) and ``locked`` are absent by design, so a sample with
    no flags is *not* a promise the model is eligible to move. Reporting some
    of the blockers would read as an eligibility verdict this endpoint cannot
    give without the filesystem work it exists to avoid.

    Sampling is deterministic and metadata-only: models in id order, and if any
    model in scope renders unclassifiable the first such model is always
    included — seeing the failure mode is the point of previewing at all. That
    search is O(models) in the worst case (no unclassifiable model exists), but
    it is pure CPU over rows already loaded.
    """
    root_keys, dest_for = _manifest_scope(db, root_id)
    resolver = TemplateResolver(db, template, root_keys)
    canonical_template = "/".join(resolver.fallback_segments)
    models = _models_for_scope(db, root_keys, root_id, with_files=False)
    models.sort(key=lambda m: m.id)

    ok: list[TemplateSample] = []
    unclassifiable: TemplateSample | None = None
    for m in models:
        dest_root = dest_for(m)
        dest = _render_destination(
            m, resolver.segments_for(m, dest_root), root_keys, None, dest_root,
            slugify_all=slugify_all,
        )
        sample = TemplateSample(
            model_id=m.id,
            model_name=m.name or "",
            source_dir=dest.current_dir,
            proposed_dir=dest.proposed_dir,
            unclassifiable=bool(dest.missing),
            missing_fields=dest.missing,
            over_length=dest.over_length,
            reserved_name=dest.reserved_name,
        )
        if sample.unclassifiable:
            if unclassifiable is None:
                unclassifiable = sample
        elif len(ok) < limit:
            ok.append(sample)
        if unclassifiable is not None and len(ok) >= limit:
            break

    if unclassifiable is None:
        return TemplatePreview(template=canonical_template, samples=ok[:limit])
    # Reserve the last slot for the failure case rather than dropping it.
    kept = [*ok[: max(limit - 1, 0)], unclassifiable]
    return TemplatePreview(
        template=canonical_template,
        samples=sorted(kept, key=lambda s: s.model_id),
    )


def _auto_apply_import_suffixes(
    entries: list[Entry],
    models: list[Model],
    resolver: TemplateResolver,
    root_keys: list[tuple[str, str]],
    pack_paths: list[str],
    overrides: dict[int, dict],
    dest_for,
    *,
    slugify_title: bool,
    slugify_all: bool,
    slugify_filenames: bool,
) -> list[Entry]:
    """Resolve import-apply collisions that have an unambiguous
    ``suggested_suffix`` by appending it to the title and rebuilding the
    entry, then re-checking for collisions. Entries without a suggestion
    (or whose suggestion doesn't resolve the collision) are left as-is and
    stay blocked, same as before.

    Takes the resolver rather than a fixed segment list (STUDIO-403) so a
    rebuilt entry renders under the same template its first pass used. Import
    apply passes an explicit template, so today every entry here resolves the
    same way — but a rebuild that silently switched templates would be a very
    quiet bug to find later."""
    if not any(e.collision and e.suggested_suffix for e in entries):
        return entries
    by_id = {m.id: m for m in models}
    rebuilt = []
    changed = False
    for e in entries:
        if e.collision and e.suggested_suffix:
            m = by_id[e.model_id]
            ov = dict(overrides.get(m.id) or {})
            ov.setdefault("suffix", e.suggested_suffix)
            dest = dest_for(m)
            e = _build_entry(m, resolver.segments_for(m, dest), root_keys, pack_paths, ov, dest,
                              slugify_title=slugify_title, slugify_all=slugify_all,
                              slugify_filenames=slugify_filenames)
            changed = True
        rebuilt.append(e)
    if changed:
        _detect_collisions(rebuilt)
    return rebuilt


def _boundary_key(value: str) -> str:
    """Conservative folder/character comparison used for package boundaries."""
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _package_boundary(model: Model, root_keys: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Return ``(character_dir, package_root)`` when topology is unambiguous.

    The scanner's character label must correspond to a real ancestor folder.
    The package is that character folder itself when it owns the model files,
    otherwise its first child on the path to the model. Nested model boundaries
    such as ``Alternate`` therefore resolve to the same release package.
    """
    current = _canon(model.folder_path or "")
    root = _scan_root_for(_key(current), root_keys)
    wanted = _boundary_key(model.character or "")
    if not current or not root or not wanted:
        return None

    parts = current.split("/")
    root_parts = root.split("/")
    for idx in range(len(parts) - 1, len(root_parts) - 1, -1):
        if _boundary_key(parts[idx]) != wanted:
            continue
        character_dir = "/".join(parts[:idx + 1])
        package_root = character_dir if idx == len(parts) - 1 else "/".join(parts[:idx + 2])
        return character_dir, package_root
    return None


def _build_package_entries(
    models: list[Model],
    root_keys: list[tuple[str, str]],
    pack_paths: list[str],
    overrides: dict[int, dict],
    *,
    slugify_all: bool,
) -> list[Entry]:
    """Build one atomic move entry per physical release package."""
    grouped: dict[str, list[tuple[Model, str, str]]] = {}
    ambiguous: list[Model] = []
    for model in models:
        boundary = _package_boundary(model, root_keys)
        if boundary is None:
            ambiguous.append(model)
            continue
        character_dir, package_root = boundary
        grouped.setdefault(_key(package_root), []).append((model, character_dir, package_root))

    entries: list[Entry] = []
    for members in grouped.values():
        members.sort(key=lambda item: (_canon(item[0].folder_path).count("/"), item[0].id))
        representative, character_dir, package_root = members[0]
        member_models = [item[0] for item in members]
        override = overrides.get(representative.id) or {}
        creator = (override.get("creator") or "").strip() or (
            representative.creator.name if representative.creator else ""
        )
        character = (override.get("character") or "").strip() or (representative.character or "")
        missing = [name for name, value in (("creator", creator), ("character", character)) if not value]

        scan_root = _scan_root_for(_key(package_root), root_keys)
        sanitized_prefix = [
            sanitize_segment(value or (UNKNOWN_CREATOR if name == "creator" else UNKNOWN_CHARACTER),
                             slugify=slugify_all)
            for name, value in (("creator", creator), ("character", character))
        ]
        safe_prefix = [part.value for part in sanitized_prefix]
        reserved = any(part.reserved_name for part in sanitized_prefix)
        proposed_dir = _canon((scan_root + "/" if scan_root else "") + "/".join(safe_prefix))
        package_name = None
        if _key(package_root) != _key(character_dir):
            package_name = package_root.rsplit("/", 1)[-1]
            sanitized_package = sanitize_segment(package_name, slugify=False)
            reserved = reserved or sanitized_package.reserved_name
            proposed_dir = _canon(proposed_dir + "/" + sanitized_package.value)

        tracked: dict[str, tuple[int, str]] = {}
        for model in member_models:
            for stl in model.stl_files:
                tracked[_key(stl.path)] = (stl.id, "stl")

        files: list[FileMove] = []
        seen: set[str] = set()
        is_symlink = False
        if os.path.isdir(package_root):
            for dirpath, dirnames, filenames in os.walk(package_root, followlinks=False):
                is_symlink = is_symlink or any(os.path.islink(os.path.join(dirpath, d)) for d in dirnames)
                for filename in filenames:
                    path = _canon(os.path.join(dirpath, filename))
                    seen.add(_key(path))
                    size, mtime_ns, link, missing_file = _stat_file_cached(path)
                    is_symlink = is_symlink or link
                    relative = path[len(package_root):].lstrip("/")
                    stl_id, kind = tracked.get(_key(path), (0, "companion"))
                    files.append(FileMove(
                        stl_file_id=stl_id or None,
                        current_path=path,
                        proposed_path=_canon(proposed_dir + "/" + relative),
                        size_bytes=size,
                        mtime_ns=mtime_ns,
                        content_hash=None,
                        fingerprint_method="stat",
                        missing_file=missing_file,
                        kind=kind,
                    ))

        missing_files = any(key not in seen for key in tracked)
        over_length = path_over_length(proposed_dir) or any(path_over_length(f.proposed_path) for f in files)
        escapes = scan_root is None
        locked = any(model.locked for model in member_models)
        entry = Entry(
            model_id=representative.id,
            model_name=package_name or character or representative.name,
            files=files,
            kind=_classify_kind(package_root, proposed_dir),
            source_dir=package_root,
            proposed_dir=proposed_dir,
            eligible=not (missing or over_length or reserved or is_symlink or escapes or missing_files or locked),
            pack_override_paths=[p for p in pack_paths if _key(p) == _key(package_root) or _key(p).startswith(_key(package_root) + "/")],
            collision=False,
            collision_kind="none",
            collision_with=[],
            suggested_suffix=None,
            unclassifiable=bool(missing),
            missing_fields=missing,
            over_length=over_length,
            reserved_name=reserved,
            overlaps_other=False,
            spans_multiple_dirs=False,
            source_directories=[package_root],
            is_symlink=is_symlink,
            escapes_scan_root=escapes,
            missing_files_on_disk=missing_files,
            locked=locked,
            creator_id=representative.creator_id,
            creator_name=representative.creator.name if representative.creator else "",
            model_ids=[model.id for model in member_models],
            package_mode=True,
            package_name=package_name,
            character_source_dir=character_dir,
            character_proposed_dir=_parent(proposed_dir) if package_name else proposed_dir,
        )
        entries.append(entry)

    for model in ambiguous:
        legacy = _build_entry(model, parse_template("{creator}/{character}"), root_keys,
                              pack_paths, overrides.get(model.id), None,
                              slugify_all=slugify_all)
        legacy.model_ids = [model.id]
        legacy.package_mode = True
        legacy.ambiguous_package = True
        legacy.eligible = False
        entries.append(legacy)
    return entries


def _attach_character_envelopes(entries: list[Entry]) -> None:
    """Inventory character-level files that sit outside every package root.

    The files are attached to one representative entry for manifest compactness;
    every entry receives the complete package/model id sets so apply can require
    an all-packages selection before adding the envelope to the move batch.
    """
    groups: dict[str, list[Entry]] = {}
    for entry in entries:
        if entry.package_mode and not entry.ambiguous_package and entry.character_source_dir:
            groups.setdefault(_key(entry.character_source_dir), []).append(entry)

    for group in groups.values():
        package_ids = sorted(entry.model_id for entry in group)
        model_ids = sorted({model_id for entry in group for model_id in entry.model_ids})
        package_roots = {_key(entry.source_dir) for entry in group}
        for entry in group:
            entry.character_package_ids = package_ids
            entry.character_model_ids = model_ids

        owner = min(group, key=lambda entry: entry.model_id)
        source_dir = owner.character_source_dir or ""
        proposed_dir = owner.character_proposed_dir or ""
        if not source_dir or not proposed_dir or _key(source_dir) in package_roots:
            continue

        shared: list[FileMove] = []
        for dirpath, dirnames, filenames in os.walk(source_dir, followlinks=False):
            current_dir = _canon(dirpath)
            # Never descend into a package; those files already belong to its
            # package entry and must not be duplicated in the envelope.
            dirnames[:] = [
                name for name in dirnames
                if _key(_canon(os.path.join(dirpath, name))) not in package_roots
            ]
            if any(_key(current_dir) == root or _key(current_dir).startswith(root + "/")
                   for root in package_roots):
                continue
            for filename in filenames:
                path = _canon(os.path.join(dirpath, filename))
                size, mtime_ns, is_link, missing = _stat_file_cached(path)
                if is_link or missing:
                    continue
                relative = path[len(source_dir):].lstrip("/")
                shared.append(FileMove(
                    stl_file_id=None,
                    current_path=path,
                    proposed_path=_canon(proposed_dir + "/" + relative),
                    size_bytes=size,
                    mtime_ns=mtime_ns,
                    content_hash=None,
                    fingerprint_method="stat",
                    missing_file=False,
                    kind="character_asset",
                ))
        owner.shared_files = shared


def _dedupe_owned_paths(paths: list, is_owned) -> list[str]:
    """Filter to paths ``is_owned`` accepts, deduped by identity key.

    Shared by every non-stl file source (image_paths/thumbnail_path/
    primary_image_path, other_files) that feeds into a model's move plan —
    each is gathered from a different Model field but needs the exact same
    ownership-boundary + de-dup treatment before becoming move candidates."""
    seen: set[str] = set()
    result: list[str] = []
    for p in paths:
        if not is_owned(p):
            continue
        k = _key(p)
        if k not in seen:
            seen.add(k)
            result.append(p)
    return result


def _append_non_stl_moves(
    files: list[FileMove], candidates: list[str],
    dest_name_counts: dict[str, int], proposed_dir: str, kind: str,
) -> bool:
    """Append one FileMove per still-existing candidate, sharing
    dest_name_counts with the STL loop and every other non-stl kind so the
    whole proposed_dir namespace disambiguates same-basename files together,
    not just within one file kind (STUDIO-314). Returns whether any
    candidate was a symlink, for the caller to fold into its own flag."""
    found_symlink = False
    for p in candidates:
        size, mtime_ns, link, is_missing = _stat_file_cached(p)
        if is_missing:
            continue
        found_symlink = found_symlink or link
        dest_filename = os.path.basename(p)
        dest_key = dest_filename.casefold()
        count = dest_name_counts.get(dest_key, 0) + 1
        dest_name_counts[dest_key] = count
        if count > 1:
            stem, ext = os.path.splitext(dest_filename)
            dest_filename = f"{stem}-{count}{ext}"
        files.append(FileMove(
            stl_file_id=None,
            current_path=_canon(p),
            proposed_path=_canon(proposed_dir + "/" + dest_filename),
            size_bytes=size,
            mtime_ns=mtime_ns,
            content_hash=None,
            fingerprint_method="stat",
            missing_file=False,
            kind=kind,
        ))
    return found_symlink


@dataclass
class RenderedDestination:
    """The stat-free half of an entry: where the template says a model goes,
    and the problems the TEMPLATE itself caused getting there.

    Deliberately not an eligibility verdict. The remaining blockers — symlink,
    missing-files-on-disk, spans-multiple-dirs — all require stat()ing the
    model's files, and `locked` is model state; none of them belong to the
    rendering. `_build_entry` adds those; the template-preview endpoint
    (STUDIO-401) uses this alone and says so.
    """
    proposed_dir: str
    current_dir: str
    cur_key: str
    missing: list[str]
    over_length: bool
    reserved_name: bool
    escapes_scan_root: bool


def _render_destination(
    m: Model,
    segments: list[str],
    root_keys: list[tuple[str, str]],
    override: dict | None = None,
    dest_root: str | None = None,
    slugify_title: bool = False,
    slugify_all: bool = False,
) -> RenderedDestination:
    """Render `segments` against one model's metadata to a destination path.

    Extracted verbatim from `_build_entry` (STUDIO-401) so the cheap
    template-preview endpoint renders through *this* code and cannot drift into
    a second implementation of the grammar. Touches no filesystem: every value
    here comes from the model row, the scan-root rows, and the template.
    """
    # User resolutions (Phase 2c) take precedence over model metadata and clear
    # the corresponding 'missing' flag.
    override = override or {}
    ov_creator = (override.get("creator") or "").strip()
    ov_character = (override.get("character") or "").strip()
    ov_scale = (override.get("scale") or "").strip()
    ov_title = (override.get("title") or "").strip()
    ov_suffix = (override.get("suffix") or "").strip()

    # Fields the template references, split by whether the reference is
    # REQUIRED or optional ("{scale?}"). Only a required reference can make a
    # model unclassifiable; an optional one drops its level instead (STUDIO-407).
    used_fields: set[str] = set()
    for seg in segments:
        # `name`, not `field` — the latter shadows the dataclasses.field import.
        for name, optional in segment_fields(seg):
            if not optional:
                used_fields.add(name)

    # Resolve template field values, tracking which fell back to a sentinel.
    # `fell_back` drives the optional-token drop; `missing` drives eligibility.
    # They are deliberately different sets: a field can fall back without being
    # "missing" (title, below), and an optional field never lands in `missing`.
    missing: list[str] = []
    fell_back: set[str] = set()
    creator_name = ov_creator or (m.creator.name if m.creator else "") or ""
    if not creator_name:
        creator_name = UNKNOWN_CREATOR
        fell_back.add("creator")
        if "creator" in used_fields:
            missing.append("creator")
    character = ov_character or m.character or ""
    if not character:
        character = UNKNOWN_CHARACTER
        fell_back.add("character")
        if "character" in used_fields:
            missing.append("character")
    scale = ov_scale or _scale_value(m.auto_tags)
    if not scale:
        scale = UNKNOWN_SCALE
        fell_back.add("scale")
        if "scale" in used_fields:
            missing.append("scale")
    title = ov_title or m.title or m.name or ""
    if not (ov_title or (m.title or "").strip()):
        # Title is the odd one out: it falls back to the FOLDER NAME before it
        # is ever "missing", so the two states genuinely differ here. Brent's
        # call 2026-09-05 is that "{title?}" drops when the model has no real
        # title of its own — dropping only when the folder name is blank too
        # would make the token do nothing, since a nameless model is vanishingly
        # rare.
        fell_back.add("title")
        # only 'missing' if the folder name is also empty
        if not (m.name or "").strip() and "title" in used_fields:
            missing.append("title")
    # Suffix dodges a collision / shortens an over-length or reserved name.
    if ov_suffix:
        title = f"{title} {ov_suffix}"
        # The suffix rides on the title segment, so an optional "{title?}" must
        # NOT drop that level any more — otherwise the one control the user has
        # for breaking a collision would silently do nothing.
        fell_back.discard("title")

    values = {
        "creator": creator_name,
        "character": character,
        "scale": scale,
        "title": title,
    }
    rendered = render_segments(segments, values, fell_back)

    reserved = False
    over_len = False
    safe_parts: list[str] = []
    for raw_seg, part in zip(segments, rendered):
        # An optional-only segment that dropped comes back empty. Skip it BEFORE
        # sanitizing — sanitize_segment("") falls back to "_", which would turn
        # a dropped level into a literal "_" directory (STUDIO-407).
        if not part:
            continue
        # slugify_all lowercases/hyphenates every segment (import-style);
        # slugify_title narrows that to just the {title} segment.
        do_slug = slugify_all or (
            slugify_title and any(f == "title" for f, _ in segment_fields(raw_seg))
        )
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

    return RenderedDestination(
        proposed_dir=proposed_dir,
        current_dir=current_dir,
        cur_key=cur_key,
        missing=missing,
        over_length=over_len,
        reserved_name=reserved,
        escapes_scan_root=escapes,
    )


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
    # Destination rendering lives in _render_destination so the cheap
    # template-preview endpoint shares this exact code (STUDIO-401). Unpacked
    # into the original local names to keep this a pure extraction.
    dest = _render_destination(
        m, segments, root_keys, override, dest_root,
        slugify_title=slugify_title, slugify_all=slugify_all,
    )
    proposed_dir = dest.proposed_dir
    current_dir = dest.current_dir
    cur_key = dest.cur_key
    missing = dest.missing
    over_len = dest.over_length
    reserved = dest.reserved_name
    escapes = dest.escapes_scan_root

    # Per-file moves + fingerprints.
    files: list[FileMove] = []
    src_dirs: dict[str, str] = {}
    is_symlink = False
    missing_files_on_disk = False
    # Two distinct source filenames can collapse to the identical destination
    # name — slugify_filenames strips enough (e.g. "arm_2_R_sup.stl" and
    # "arm_2_R__sup.stl" both slug to "arm-2-r-sup.stl"), or a source folder
    # can just have two files differing only by case. Left unchecked, the
    # second file's move silently overwrites the first on some filesystems
    # or hard-fails apply outright on others (#1087 — a real build-kit pack
    # hit this and lost the second file). Track destination names already
    # claimed within this model and disambiguate with a numeric suffix.
    dest_name_counts: dict[str, int] = {}
    for f in m.stl_files:
        size, mtime_ns, link, is_missing = _stat_file_cached(f.path)
        is_symlink = is_symlink or link
        missing_files_on_disk = missing_files_on_disk or is_missing
        source_dir = _canon(_parent(f.path))
        source_key = _key(source_dir)
        current_display = src_dirs.get(source_key)
        if current_display is None or source_dir < current_display:
            src_dirs[source_key] = source_dir
        dest_filename = f.filename or os.path.basename(f.path or "")
        if slugify_filenames and dest_filename:
            dest_filename = slug_filename(dest_filename)
        dest_key = dest_filename.casefold()
        count = dest_name_counts.get(dest_key, 0) + 1
        dest_name_counts[dest_key] = count
        if count > 1:
            stem, ext = os.path.splitext(dest_filename)
            dest_filename = f"{stem}-{count}{ext}"
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
    source_directories = [src_dirs[key] for key in sorted(src_dirs)]

    # Local gallery images and other_files move alongside the STLs. Scoped to
    # files that live inside the model's OWN folder tree — one inherited from
    # a shared parent folder (e.g. a character-level "renders/" dir referenced
    # by several sibling variants) is deliberately left in place, since moving
    # it would break the path for every other model still pointing at it.
    # Missing/stale entries (the file no longer exists — #854/#855) are just
    # skipped rather than treated as a blocker: a stale reference shouldn't
    # stop the model's STLs from being reorganized. Never counted toward
    # spans_multiple_dirs — these commonly live in their own subfolder next
    # to the STLs, and that's not the ambiguous-source-directory case that
    # check exists to catch.
    cur_prefix = cur_key + "/"

    def _owned_local_file(p: object) -> bool:
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

    # Same collapse risk as STL filenames above, and just as real: two files
    # with the same basename in different subfolders (or differing only by
    # case) both flatten to proposed_dir/<basename>. Apply forgives a
    # non-stl FileExistsError by skipping the move (reorganize_apply
    # .apply_manifest), so unlike an STL collision this wouldn't even fail
    # loudly — the second file would just silently stay behind. Shares
    # dest_name_counts with the STL loop above (and across image/other_files
    # here) so the whole proposed_dir namespace is disambiguated together,
    # not just within each file kind (STUDIO-314).
    image_candidates = _dedupe_owned_paths(
        [*(m.image_paths or []), m.thumbnail_path, m.primary_image_path], _owned_local_file,
    )
    is_symlink = is_symlink or _append_non_stl_moves(
        files, image_candidates, dest_name_counts, proposed_dir, kind="image",
    )

    # other_files (PDFs, READMEs, a .3mf project bundle — see
    # scanner.PROJECT_BUNDLE_EXTENSIONS) never had a move-plan entry at all
    # before this: only "stl" and "image" kinds existed, so any model with a
    # non-empty other_files silently left those files behind at the old
    # folder on every reorganize (#1156 follow-up — a real incident: adding a
    # creator name to an inbox-imported pack left its .3mf stranded in the
    # old inbox folder). Same collision-avoidance and hidden-dir/ownership
    # scoping as the image loop above.
    other_candidates = _dedupe_owned_paths(m.other_files or [], _owned_local_file)
    is_symlink = is_symlink or _append_non_stl_moves(
        files, other_candidates, dest_name_counts, proposed_dir, kind="other",
    )

    # Path-keyed overrides this move invalidates (under the model's folder).
    pack_refs = [p for p in pack_paths if _key(p) == cur_key or _key(p).startswith(cur_key + "/")]

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
        source_directories=source_directories,
        is_symlink=is_symlink,
        escapes_scan_root=escapes,
        missing_files_on_disk=missing_files_on_disk,
        locked=m.locked,
        creator_id=m.creator_id,
        creator_name=m.creator.name if m.creator else "",
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

    **The per-root rule, stated rather than left implicit (STUDIO-403):** the
    folder is anchored at the primary enabled root, so it is shaped by *that
    root's* template. Where it lands decides how it is shaped — anchoring under
    one root while rendering with another root's template would place a folder
    the receiving root then reports as unorganized the moment it is scanned.
    An explicit ``template`` argument still wins, same as everywhere else.
    """
    primary = (
        db.query(ScanRoot)
        .filter(ScanRoot.enabled == True)  # noqa: E712
        .order_by(ScanRoot.id)
        .first()
    )
    if not primary or not primary.path:
        return None

    segments = TemplateResolver(db, template, []).segments_for_anchor(_canon(primary.path))
    # Matched through segment_fields, not a "{creator}" substring test — the
    # latter sees nothing in "{creator?}", which would return None here and
    # silently stop placing new creator folders altogether (STUDIO-407).
    idx = next(
        (i for i, seg in enumerate(segments)
         if any(f == "creator" for f, _ in segment_fields(seg))),
        None,
    )
    if idx is None:
        return None
    lead = segments[: idx + 1]
    other_fields = {
        f for seg in lead for f, _ in segment_fields(seg)
        if f in ("character", "scale", "title")
    }
    if other_fields:
        return None

    # No dropped_fields: a brand-new creator always has a name, so even an
    # optional "{creator?}" renders here. The `if p` guard is the same
    # skip-before-sanitize rule as _build_entry's loop.
    rendered = render_segments(lead, {"creator": creator_name})
    parts = [sanitize_segment(p, slugify=slugify).value for p in rendered if p]
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
    """Return a safe suffix for a strong variant-like source-folder name.

    Falls back to :func:`name_parser.support_status` for print-format-variant
    folders ("... (supported)" / "... (unsupported)") that don't match the
    Alt/V2/Version pattern above but are just as reliable a distinguishing
    signal (#1087) — common when a single pack's Approach-B/single-pack scan
    lands two variants of the same product in one collision group."""
    leaf = _canon(source_dir).rsplit("/", 1)[-1].strip()
    if not leaf:
        return None
    if _SOURCE_SUFFIX_RE.fullmatch(leaf):
        suffix = sanitize_segment(leaf, slugify=True).value
        return suffix or None
    status = name_parser.support_status(leaf)
    if status:
        return sanitize_segment(status, slugify=True).value or None
    return None


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
    dirs: list[tuple[Entry, str]] = [(e, _key(e.proposed_dir)) for e in entries]
    for i, (e, dst_i) in enumerate(dirs):
        for j, (other, dst_j) in enumerate(dirs):
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

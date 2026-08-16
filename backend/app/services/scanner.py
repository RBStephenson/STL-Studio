"""
File system scanner.

Folder structure on disk (variable depth):
  <root>/
    <Creator>/
      <Character>/               ← user-created grouping folder
        Images/                  ← shared images (may be here or anywhere)
        <Product Variant>/       ← extracted from a ZIP ← Model
          Akuma/                 ← parts sub-folder (not a separate model)
          Base/
        <Another Variant -Pre Supported>/   ← separate Model

A folder is only ever a model if its subtree contains STL files.
Leaf detection priority:
  1. Folder name contains scale/type/modifier signals (product boundary), while
     independently qualifying nested product/variant folders retain ownership
     of their own subtrees
  2. Folder contains STLs and all child dirs look like parts sub-folders
  3. Folder contains STLs and has no children with STLs (deepest fallback)

Auto-tags are generated from detected scale, type, and modifier tokens.
needs_review=True is set when confidence is low.
"""
import logging
import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

from sqlalchemy import text as _sqltext, func, or_

from app.database import SessionLocal
from app.models import Creator, Model, STLFile, ScanRoot, ModelTag, CollectionModel, PackOverride
from app.services.job_runner import JobHandle, JobState, runner
from app.services import name_parser, layout, grouping
from app.services.path_boundary import PathBoundary
from app.services.scan_rules import (
    IgnoreMatcher, load_ignore_matcher, load_tag_rules, load_parts_names,
)
from app.services.tag_sync import sync_model_tags
from app.services import write_lock
from app.services import ai_organize
from app.services.ai_organize import clean_name
from app.utils import utcnow, utc_timestamp

logger = logging.getLogger(__name__)

STL_EXTENSIONS = {".stl", ".3mf", ".obj"}
# Members of STL_EXTENSIONS that count as "this folder has printable content"
# for leaf detection, but are a project/bundle format rather than a single
# printable part — filed as other_files, never as their own STLFile row (see
# _index_stl_files). Anything that checks STL_EXTENSIONS to mean "already
# indexed/moved as tracked geometry" must subtract this set first — treating
# it as an ordinary STL_EXTENSIONS member there silently drops the file: it's
# not in the STL move manifest (not an STLFile row) and would be skipped by
# the non-STL file mover too (imports.py) if that check doesn't know about
# this carve-out, so it never gets moved to the destination at all.
PROJECT_BUNDLE_EXTENSIONS = {".3mf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
PREFERRED_IMAGE_DIRS = {
    "renders", "render", "images", "image", "photos", "photo",
    "preview", "previews", "pics", "pictures", "gallery",
}
# Slicer project/slice files — never index these, even if a future printable
# extension overlaps (#206). NOTE: .3mf is deliberately NOT here — slicers save
# projects as .3mf, but many designers also distribute printable geometry that
# way; see the issue for a possible content-sniffing follow-up.
SLICER_EXTENSIONS = {
    ".lys",        # Lychee Slicer
    ".chitubox",   # Chitubox
    ".ctb",        # Chitubox / Halot
    ".photon",     # Photon Workshop
    ".pw0", ".pwx", ".pws",  # Photon Workshop variants
    ".fhd",        # Formware
}
NESTED_VARIANT_BOUNDARY = re.compile(
    r"^(?:alt(?:ernate|ernative)?|variant)(?:[\s_-].*)?$|^v\d+(?:\.\d+)?$",
    re.I,
)
# How many read-failure paths a scan reports back through its status payload. The
# count is exact; the sample is capped so a systematically unreadable library
# (e.g. every path past MAX_PATH) can't grow the status response without bound.
READ_FAILURE_SAMPLE_LIMIT = 20


@dataclass(frozen=True)
class ReadFailure:
    """One filesystem entry the scanner could not stat while classifying a folder.

    Defined up here rather than beside :func:`_list_dir` because
    ``_walk_for_models`` annotates a parameter with it, and annotations are
    evaluated at def time.
    """
    path: str
    error: str


@dataclass(frozen=True)
class DirListing:
    """A folder's immediate children, split by kind, plus any per-entry failures.

    ``dirs``/``files`` are unsorted and unfiltered (hidden entries included) —
    call sites apply their own ordering and hidden-filtering so this stays a
    faithful listing rather than a policy decision.
    """
    dirs: list[Path] = dataclass_field(default_factory=list)
    files: list[Path] = dataclass_field(default_factory=list)
    failures: list[ReadFailure] = dataclass_field(default_factory=list)

# The "one scan at a time" gate is the app-wide library write lock
# (services/write_lock.py), so a scan and a reorganize apply/undo are mutually
# exclusive — a scan must not prune/insert rows under a move in flight (#324).
# Serializes DB-mutating work across the parallel creator workers. SQLite allows
# only one writer; without this, workers holding an open write transaction during
# slow rglob I/O block each other past busy_timeout -> "database is locked", which
# aborts a creator's walk and silently drops its models.
_db_lock = threading.Lock()

# Scan status/cancel/progress live on the shared background-job runner
# (services/job_runner.py, STUDIO-59), keyed "scan" — only one scan runs at a
# time (held by the write lock), so a single key and a single active handle are
# enough. The handle is stashed module-level so the deep, recursive walk helpers
# can push progress and observe cancellation without threading it through every
# call (same justification as the pack-overrides / ignore-matcher globals below).
_SCAN_KEY = "scan"
_active: JobHandle | None = None


def _msg(message: str) -> None:
    if _active is not None:
        _active.update(message=message)


def _bump(**deltas: int) -> None:
    if _active is not None:
        _active.increment(**deltas)


def _cancelled() -> bool:
    return _active is not None and _active.cancelled
@dataclass(frozen=True)
class ScanRules:
    """Immutable per-run rules the walk consults for every folder (STUDIO-231).

    Previously two module-level mutable globals populated at scan start. That
    worked only because one scan runs at a time (held by the library write lock),
    and it hid a real dependency: nothing in the signature of ``_walk_for_models``
    said its classification depended on process-wide state, and an entry point
    that forgot to load them silently walked with whatever the previous operation
    left behind.

    Frozen, so the four parallel creator workers share read-only state by
    construction rather than by convention.

    * ``pack_overrides`` — folders the user has explicitly split into per-child
      models (see PackOverride). The walk treats these as boundaries; this is what
      makes an opt-in split durable across rescans.
    * ``ignore`` — configurable folder/file ignore patterns (#31). The walk skips
      any folder it matches.
    * ``parser_rules`` — the user's tag-inference and parts/structural folder
      rules (#31), threaded into every ``name_parser`` call the walk makes
      (STUDIO-363). Previously pushed into ``name_parser`` as module-level
      global state by this classmethod as a side effect; now just another
      field on this immutable, explicitly-passed context.
    """

    pack_overrides: frozenset[str] = frozenset()
    ignore: IgnoreMatcher = IgnoreMatcher(())
    parser_rules: name_parser.ParserRules = name_parser.ParserRules()

    @classmethod
    def load(cls, db: Session) -> "ScanRules":
        """Read this run's rules from the database. Free of side effects — the
        returned value is the only thing this constructor produces."""
        return cls(
            pack_overrides=frozenset(row[0] for row in db.query(PackOverride.path)),
            ignore=load_ignore_matcher(db),
            parser_rules=name_parser.ParserRules(
                tag_rules=tuple((r.pattern, r.tag) for r in load_tag_rules(db)),
                parts_names=load_parts_names(db),
            ),
        )


def get_status() -> dict:
    """Legacy scan-status shape kept as the public contract (ScanStatus + the
    /scan/status route + tests): ``{running, message, models_found, files_found,
    cancelled, offline_roots}``. Mapped out of the shared runner's uniform
    ``{state, progress, message, error}`` payload."""
    payload = runner.status(_SCAN_KEY)
    prog = payload["progress"]
    return {
        "running": payload["state"] == JobState.RUNNING.value,
        "message": payload["message"] or "idle",
        "models_found": prog.get("models_found", 0),
        "files_found": prog.get("files_found", 0),
        # cancelled flips the moment the walk observes the request (progress flag),
        # before the job reaches its terminal CANCELLED state during teardown.
        "cancelled": payload["state"] == JobState.CANCELLED.value or prog.get("cancelled", False),
        "offline_roots": prog.get("offline_roots", []),
        # Entries the walk could not stat (STUDIO-358). Non-zero means this run saw
        # an incomplete view of the disk, so its model count is a floor, not a
        # total — and the prunes that depend on a complete walk were skipped.
        "read_failures": prog.get("read_failures", 0),
        "read_failure_samples": prog.get("read_failure_samples", []),
    }


def _root_available(path: str) -> bool:
    """A scan root counts as 'available' only if it exists on disk AND holds at
    least one entry.

    A detached bind/network mount typically leaves an EMPTY mountpoint directory
    behind — it still passes ``.exists()``, so absence alone is not a reliable
    unmount signal; emptiness is. Pruning must never treat a model as deleted just
    because its drive went offline, so every destructive prune is gated on this:
    models under an unavailable root are protected, not removed.
    """
    try:
        p = Path(path)
        if not p.is_dir():
            return False
        with os.scandir(p) as it:
            return next(it, None) is not None
    except OSError:
        return False


def request_cancel():
    """Cooperatively cancel the running scan. The walk polls _cancelled() at safe
    checkpoints; no-op if nothing is running."""
    runner.cancel(_SCAN_KEY)


def scan_all_roots(db: Session | None = None):
    """Full library scan. Synchronous — runs the job inline on the calling thread
    so direct callers (tests) execute against a caller-owned session. Routers use
    start_full_scan() to run it off the request path. The write lock is the
    concurrency gate; a busy lock is a silent no-op (prior status untouched)."""
    if not write_lock.try_acquire_for_scan():
        return
    runner.run_inline(_SCAN_KEY, _full_scan, db=db)


def start_full_scan() -> bool:
    """Launch a full scan off the request path via the shared runner. Returns
    False if the library is busy (the write lock is held by a scan/apply/undo) so
    the router can answer 409 instead of a misleading 200. A launch failure
    releases the lock rather than wedging the library at running-forever."""
    if not write_lock.try_acquire_for_scan():
        return False
    try:
        runner.start(_SCAN_KEY, _full_scan, single_flight=False)
    except Exception:
        write_lock.release_scan()
        raise
    return True


def _full_scan(job: JobHandle, db: Session | None = None):
    # Assumes the write lock is already held (acquired by the sync wrapper or the
    # launcher); released in the finally below.
    global _active
    _active = job
    job.update(message="starting", models_found=0, files_found=0, cancelled=False, offline_roots=[],
               read_failures=0, read_failure_samples=[])
    try:
        _db = db or SessionLocal()
        own_db = db is None
        try:
            rules = ScanRules.load(_db)

            # Clear needs_review for any model that already has indexed STL files —
            # those are confirmed real products that were over-eagerly flagged.
            result = _db.execute(_sqltext(
                """
                UPDATE models SET needs_review = 0
                WHERE needs_review = 1
                  AND id IN (SELECT DISTINCT model_id FROM stl_files)
                """
            ))
            cleared = result.rowcount
            _db.commit()
            if cleared:
                logger.info(f"Pre-scan: cleared needs_review on {cleared} previously-indexed models")

            # Captured BEFORE any root is walked and used as the new last_scanned
            # baseline (not each root's post-walk timestamp): a file changed
            # mid-walk, after its own folder was already visited, has an mtime
            # older than an end-of-walk stamp and would be wrongly skipped next
            # run (STUDIO-295).
            scan_start = utcnow()
            roots = _db.query(ScanRoot).filter(ScanRoot.enabled == True).all()
            root_paths = [r.path for r in roots]
            # Creators whose walk raised this run — their models were only partially
            # (re)indexed, so they must be shielded from the stale prune (STUDIO-79).
            failed_creator_ids: set[int] = set()
            for root in roots:
                if _cancelled():
                    job.update(state=JobState.CANCELLED, message="cancelled", cancelled=True)
                    break
                root_failed = _scan_root(root, _db, rules)
                failed_creator_ids |= root_failed
                # Only advance the baseline for a root that was ONLINE (missing or
                # detached-mount-empty roots present as "no creators found", which
                # root_failed alone can't distinguish from a genuinely empty root)
                # AND walked with no creator failures this run. Otherwise keep the
                # prior last_scanned so the next scan re-checks everything it may
                # have missed while offline/failing (STUDIO-295).
                if not root_failed and _root_available(root.path):
                    root.last_scanned = scan_start
                _db.commit()

            if not _cancelled():
                # Mount-detach guard: a root that has unmounted presents as a
                # missing OR empty directory. Treat such roots as offline and
                # prune nothing beneath them — otherwise one transient mount drop
                # makes every path under it look deleted and cascades away the
                # whole library (models, STL rows, tags, collection memberships).
                # Only roots we can confirm are online feed the destructive prunes.
                available_paths = [p for p in root_paths if _root_available(p)]
                offline_paths = [p for p in root_paths if p not in available_paths]
                if offline_paths:
                    logger.warning(
                        "Scan root(s) offline (missing or empty) — pruning skipped "
                        f"for everything beneath them to avoid data loss: {offline_paths}"
                    )
                    job.update(offline_roots=list(offline_paths))

                if failed_creator_ids:
                    logger.warning(
                        "Creator walk(s) failed this run — stale prune skipped for "
                        f"their models to avoid data loss: creator_ids={sorted(failed_creator_ids)}"
                    )

                removed = _prune_stale_models(
                    _db, scan_start, available_paths,
                    protected_creator_ids=failed_creator_ids,
                )
                removed += _prune_stale_paths(
                    _db, available_paths, protected_creator_ids=failed_creator_ids,
                )
                _prune_stale_stl_files(
                    _db, available_paths, protected_creator_ids=failed_creator_ids,
                )
                # Drop models that a newly-added ignore pattern now covers (#31).
                removed += _prune_ignored(_db, available_paths, rules.ignore)
                # Slicer rows must go before the phantom prune so a model whose
                # only "STL" was a slicer project is removed in the same scan.
                _prune_slicer_files(_db)
                removed += _prune_phantoms(_db)
                prune_empty_creators(_db)

                # Replace the in-progress "scanning <creator>" message with a
                # summary the UI can show once the run finishes (#223).
                prog = job.payload()["progress"]
                summary = (
                    f"done — {prog.get('models_found', 0)} models, "
                    f"{prog.get('files_found', 0)} files"
                )
                if removed:
                    summary += f", {removed} removed"
                job.update(state=JobState.DONE, message=summary)
        finally:
            if own_db:
                _db.close()
    except Exception as e:
        logger.exception(f"Scan failed: {e}")
        job.update(state=JobState.ERROR, message=f"error: {e}", error=str(e))
    finally:
        write_lock.release_scan()
        _active = None


def _cascade_delete_models(db: Session, ids: list[int], chunk: int = 500) -> None:
    """Delete the given models and all their dependent rows (STL files, tag links,
    collection links) in batches, then commit.

    Shared by every prune path (and the pack-split replace) so the set of child
    tables that must be cleared alongside a Model lives in exactly one place — add
    a new child table and only this helper needs updating, not three call sites.
    """
    for i in range(0, len(ids), chunk):
        batch = ids[i:i + chunk]
        db.query(STLFile).filter(STLFile.model_id.in_(batch)).delete(synchronize_session=False)
        db.query(ModelTag).filter(ModelTag.model_id.in_(batch)).delete(synchronize_session=False)
        db.query(CollectionModel).filter(CollectionModel.model_id.in_(batch)).delete(synchronize_session=False)
        db.query(Model).filter(Model.id.in_(batch)).delete(synchronize_session=False)
    db.commit()


def _exceeds_prune_cap(stale_count: int, total: int, reason: str) -> bool:
    """Safety net shared by the cap-guarded prunes: return True (and log a warning)
    when deleting `stale_count` of `total` models would exceed 50% — that looks like
    a botched indexing run rather than legitimate cleanup, so the caller should skip.
    """
    if total and stale_count > total * 0.5:
        logger.warning(
            f"Prune skipped ({reason}): {stale_count}/{total} models matched — "
            "that looks like an indexing failure, not stale data."
        )
        return True
    return False


def _prune_stale_paths(
    db: Session,
    available_root_paths: list[str],
    protected_creator_ids: set[int] | None = None,
):
    """Remove models whose folder_path no longer exists on disk — cleans up rows
    left behind after a creator/character folder is renamed under a still-mounted
    root (e.g. 'polyminds studios' → 'PolyMind Studios'). The scanner never visits
    the old path again, so the rows survive the phantom prune.

    Mount-detach safety: a model is pruned only when its folder is missing AND it
    lives under a root confirmed ONLINE this run. A detached mount makes every path
    beneath it report missing; without this gate the prune would wipe the entire
    library (cascading away STL rows, tags, and collection links) the moment a drive
    dropped. Models not attributable to any online root are left untouched. The 50%
    cap (shared with the other prunes) is a second safety net against a botched run.

    Models under a creator whose walk FAILED this run (protected_creator_ids) are
    also never pruned here — same STUDIO-79 rationale as _prune_stale_models and
    _prune_stale_stl_files: a transient error partway through a creator's walk
    (root listable, but a subfolder flakes) must not look like a deleted folder
    (STUDIO-296).

    Returns the number of models pruned (for the scan completion summary, #223).
    """
    online = PathBoundary.from_paths(available_root_paths)
    if not online:
        return 0
    protected = protected_creator_ids or set()

    rows = (
        db.query(Model.id, Model.folder_path, Model.creator_id)
        .filter(Model.folder_path != None)  # noqa: E711
        .all()
    )
    under = [
        r for r in rows
        if r.creator_id not in protected and online.contains(r.folder_path)
    ]
    total = len(under)
    stale_ids = [r.id for r in under if not Path(r.folder_path).exists()]
    if not stale_ids:
        return 0
    if _exceeds_prune_cap(len(stale_ids), total, "folder path missing on disk"):
        return 0

    _cascade_delete_models(db, stale_ids)
    logger.info(f"Post-scan: pruned {len(stale_ids)} models with missing folder paths")
    return len(stale_ids)


def _prune_stale_stl_files(
    db: Session,
    available_root_paths: list[str],
    protected_creator_ids: set[int] | None = None,
):
    """Remove STLFile rows whose recorded path no longer exists on disk, for
    models whose own folder IS confirmed present this run.

    _index_stl_files (the per-folder indexer) is additive-only: it inserts a
    row for any on-disk file not already indexed by exact path, but never
    removes one whose file has since vanished under that exact path — e.g. a
    bulk rename done outside the app (case/hyphenation change, a renamed
    scale suffix, etc.). Left alone, those rows never go away on their own:
    the model's folder still exists (so _prune_stale_paths doesn't catch it)
    and the model still has other valid STL rows (so _prune_phantoms doesn't
    either) — they just sit there forever looking like a "missing file" to
    Reorganize and anything else that stats STLFile.path, even though the
    file is right there under its new name.

    Same safety rails as the other prunes: only rows belonging to a model
    under a root confirmed ONLINE this run, whose folder itself still exists,
    and not under a creator whose walk failed (protected_creator_ids) — a
    transient mount hiccup or partial walk must never look like a legitimate
    rename. Cap-guarded like the others against a botched run.

    Returns the number of STL rows pruned (for the scan completion summary).
    """
    online = PathBoundary.from_paths(available_root_paths)
    if not online:
        return 0
    protected = protected_creator_ids or set()

    models = (
        db.query(Model.id, Model.folder_path, Model.creator_id)
        .filter(Model.folder_path != None)  # noqa: E711
        .all()
    )
    model_ids = [
        m.id for m in models
        if m.creator_id not in protected
        and online.contains(m.folder_path)
        and Path(m.folder_path).exists()
    ]
    if not model_ids:
        return 0

    total = 0
    stale_ids: list[int] = []
    for i in range(0, len(model_ids), 500):
        chunk = model_ids[i:i + 500]
        rows = db.query(STLFile.id, STLFile.path).filter(STLFile.model_id.in_(chunk)).all()
        total += len(rows)
        stale_ids.extend(r.id for r in rows if not r.path or not os.path.exists(r.path))

    if not stale_ids:
        return 0
    if _exceeds_prune_cap(len(stale_ids), total, "STL file path missing on disk"):
        return 0

    for i in range(0, len(stale_ids), 500):
        db.query(STLFile).filter(STLFile.id.in_(stale_ids[i:i + 500])).delete(synchronize_session=False)
    db.commit()
    logger.info(f"Post-scan: pruned {len(stale_ids)} stale STL file row(s) (renamed/removed outside the app)")
    return len(stale_ids)


def _prune_ignored(db: Session, root_paths: list[str], ignore: IgnoreMatcher):
    """Remove already-indexed models that now fall under a configured ignore
    pattern (#31).

    The walk returns at the first ignored folder and never indexes anything
    beneath it, so a model already in the DB is "ignored" when its own folder OR
    any ancestor up to (but not including) its scan root matches the ignore
    matcher. Testing ancestors — not just the leaf — means a bare-name pattern
    like "wip" still drops every model nested under a "wip" folder.

    Cap-guarded via _exceeds_prune_cap so a too-broad new pattern can't silently
    wipe the library, and user-excluded models are left alone (already hidden;
    mirrors _prune_stale_models).

    Returns the number of models pruned (for the scan completion summary, #223).
    """
    if not ignore.patterns:
        return 0
    roots = PathBoundary.from_paths(root_paths)
    if not roots:
        return 0

    def _is_ignored(folder_path: str | None) -> bool:
        if not folder_path:
            return False
        current = Path(folder_path)
        # Walk leaf → up, stopping when we step onto a scan root (don't test the
        # root itself — ignoring a whole root is not this feature's job) or run
        # out of parents.
        #
        # is_root(), NOT contains(): this is the stop condition for the climb, so
        # it must match the root EXACTLY. contains() would also match every
        # descendant, i.e. the model's own folder on the first iteration, ending
        # the walk immediately and silently disabling ignore rules for anything
        # nested below an ignored folder.
        while True:
            if roots.is_root(current):
                return False
            if ignore.matches(current):
                return True
            parent = current.parent
            if parent == current:  # filesystem root, no scan-root match found
                return False
            current = parent

    total = db.query(Model.id).count()
    rows = (
        db.query(Model.id, Model.folder_path)
        .filter(Model.excluded == False, Model.folder_path != None)  # noqa: E711, E712
        .all()
    )
    ignored_ids = [r.id for r in rows if _is_ignored(r.folder_path)]
    if not ignored_ids:
        return 0
    if _exceeds_prune_cap(len(ignored_ids), total, "matched an ignore pattern"):
        return 0

    _cascade_delete_models(db, ignored_ids)
    logger.info(f"Post-scan: pruned {len(ignored_ids)} models under ignore patterns")
    return len(ignored_ids)


def _prune_stale_models(
    db: Session,
    scan_start: datetime,
    root_paths: list[str],
    protected_creator_ids: set[int] | None = None,
):
    """After a full scan, delete models under scanned roots that were not visited.

    Any model whose updated_at predates the scan start was not walked this run —
    either the folder was restructured, or the scanner logic evolved and it's no
    longer a leaf. Safety cap: skip if >50% of models under the scanned roots
    would be pruned (suggests an indexing failure rather than legitimate pruning).

    Root membership goes through services/path_boundary.PathBoundary rather than a
    SQL LIKE prefix: folder paths and root names routinely contain '_' and other
    LIKE metacharacters, and an unanchored prefix would also match sibling roots
    ('D:/STL' vs 'D:/STLBackup'). The boundary anchors descendants on a separator
    and folds case per host filesystem, which is why this stays in Python.

    User-EXCLUDED models are never pruned: the walk returns before bumping their
    updated_at (so it always predates scan_start), and deleting them would let a
    later scan resurrect the folder as a brand-new, non-excluded model.

    Models under a creator whose walk FAILED this run (protected_creator_ids) are
    also never pruned: their folders were only partially re-indexed, so a stale
    updated_at reflects a transient error (SQLite lock, mount hiccup), not a deleted
    folder — pruning them would silently wipe live data (STUDIO-79).

    Returns the number of models pruned (for the scan completion summary, #223).
    """
    scanned = PathBoundary.from_paths(root_paths)
    if not scanned:
        return 0
    protected = protected_creator_ids or set()

    # Fetch non-excluded candidates once (id + folder + timestamp + creator), then
    # derive both the under-root total and the stale subset in Python. Root
    # membership can't move to SQL (see docstring re: LIKE metacharacters), but a
    # single pass replaces the two overlapping full-table queries this ran before
    # (#653).
    rows = (
        db.query(Model.id, Model.folder_path, Model.updated_at, Model.creator_id)
        .filter(Model.excluded == False, Model.folder_path != None)  # noqa: E711, E712
        .all()
    )
    under = [
        r for r in rows
        if scanned.contains(r.folder_path) and r.creator_id not in protected
    ]
    total = len(under)
    stale_ids = [
        r.id for r in under
        if r.updated_at is not None and r.updated_at < scan_start
    ]
    if not stale_ids:
        return 0
    if _exceeds_prune_cap(len(stale_ids), total, "not visited this run"):
        return 0

    _cascade_delete_models(db, stale_ids)
    logger.info(f"Post-scan: pruned {len(stale_ids)} stale models (not visited this run)")
    return len(stale_ids)


def prune_empty_creators(db: Session):
    """Delete Creator rows that have no models — left behind by stale-path pruning,
    or by a caller reassigning every one of a creator's models elsewhere
    (single-pack import's placeholder creator — named after the pack folder,
    e.g. "Ignisaurus Clan ..." — orphaned the moment the user sets the real
    creator name via bulk-enrich or a single-model edit; #1108). Public
    (no leading underscore) since it's now called from outside this module,
    not just the post-scan pass below."""
    orphans = (
        db.query(Creator)
        .filter(~Creator.id.in_(db.query(Model.creator_id).filter(Model.creator_id != None).distinct()))
        .all()
    )
    if orphans:
        for c in orphans:
            db.delete(c)
        db.commit()
        logger.info(f"Removed {len(orphans)} creator(s) with no remaining models")


def _prune_phantoms(db: Session, creator_id: int | None = None):
    """Delete models that have no STL files — render/preview/empty folders that
    earlier scanner versions wrongly indexed.

    After a completed full scan, every STL-containing folder has been indexed, so a
    model with zero STL rows genuinely has no printable files. (Incremental skips
    keep prior STL rows, so unchanged real models are never empty.) Set-based for
    speed — no per-model disk walk. As a safety net against a botched indexing run,
    skip pruning if an implausibly large share of models look empty.

    Pass creator_id to restrict pruning to a single creator (used after per-creator
    rescans so we don't touch creators that haven't been walked yet).

    Returns the number of models pruned (for the scan completion summary, #223).
    """
    base_q = db.query(Model.id)
    if creator_id is not None:
        base_q = base_q.filter(Model.creator_id == creator_id)
    total = base_q.count()
    ids = [
        row[0] for row in
        base_q.filter(~Model.id.in_(db.query(STLFile.model_id).distinct()))
    ]
    if not ids:
        return 0
    if _exceeds_prune_cap(len(ids), total, "no STL files"):
        return 0

    _cascade_delete_models(db, ids)
    logger.info(f"Post-scan: pruned {len(ids)} phantom models (no STL files)")
    return len(ids)


def _prune_slicer_files(db: Session):
    """Delete stl_files rows for slicer project files indexed by earlier scanner
    versions (#206). The candidate filter in _index_stl_files keeps new ones out;
    this cleans up what's already in the table.
    """
    patterns = [f"%{ext}" for ext in SLICER_EXTENSIONS]
    rows = db.query(STLFile).filter(
        or_(*[STLFile.filename.ilike(p) for p in patterns])
    ).all()
    if rows:
        logger.info(f"Post-scan: pruned {len(rows)} slicer project file(s) from stl_files")
        for row in rows:
            db.delete(row)
        db.commit()


def _creator_dirs_by_name(name: str, db: Session) -> list[tuple[Path, list[str]]]:
    """Locate creator directories under scan roots by matching the creator's name.

    Used as a fallback when _creator_dirs_for returns nothing (zero indexed
    models yet). Enables per-creator rescan to bootstrap a brand-new creator.
    """
    results: list[tuple[Path, list[str], bool]] = []
    for root in db.query(ScanRoot).filter(ScanRoot.enabled == True).all():
        root_path = Path(root.path)
        roles = layout.roles_for(root.layout)
        for creator_dir, layout_tags in layout.iter_creator_dirs(root_path, roles):
            if creator_dir.name.lower() == name.lower() and creator_dir.exists():
                results.append((creator_dir, layout_tags, root.group_by_character))
    return results


def _creator_dirs_for(creator: Creator, db: Session) -> list[tuple[Path, list[str]]]:
    """Resolve the on-disk creator-level folder(s) for a creator from its indexed
    models, honouring each scan root's layout. Returns (creator_dir, layout_tags)
    pairs. A creator normally maps to one folder, but we handle several
    defensively (e.g. the same name under multiple {tag} branches)."""
    roots = [(Path(r.path), layout.roles_for(r.layout), r.group_by_character)
             for r in db.query(ScanRoot).filter(ScanRoot.enabled == True).all()]
    boundaries: dict[Path, list[str]] = {}
    group_flags: dict[Path, bool] = {}
    for (fp,) in db.query(Model.folder_path).filter(Model.creator_id == creator.id):
        if not fp:
            continue
        p = Path(fp)
        for root, roles, grp in roots:
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            depth = layout.creator_depth(roles)
            if len(rel.parts) > depth:
                creator_dir = root.joinpath(*rel.parts[:depth + 1])
                boundaries[creator_dir] = layout.tags_for_path(creator_dir, root, roles)
                group_flags[creator_dir] = grp
            break

    return [(d, tags, group_flags.get(d, False))
            for d, tags in sorted(boundaries.items()) if d.exists()]


def scan_creator(creator_id: int):
    """Rescan a single creator's folder(s) — a targeted alternative to a full scan.
    Synchronous (see scan_all_roots); routers use start_creator_scan()."""
    if not write_lock.try_acquire_for_scan():
        return
    runner.run_inline(_SCAN_KEY, _creator_scan, creator_id=creator_id)


def start_creator_scan(creator_id: int) -> bool:
    """Launch a single-creator rescan off the request path. Returns False if the
    library is busy (write lock held) so the router can answer 409 instead of a
    misleading 200. A launch failure releases the lock rather than wedging it."""
    if not write_lock.try_acquire_for_scan():
        return False
    try:
        runner.start(_SCAN_KEY, _creator_scan, single_flight=False, creator_id=creator_id)
    except Exception:
        write_lock.release_scan()
        raise
    return True


def _creator_scan(job: JobHandle, creator_id: int):
    # Assumes the write lock is already held; released in the finally below.
    global _active
    _active = job
    job.update(message="starting", models_found=0, files_found=0, cancelled=False,
               read_failures=0, read_failure_samples=[])
    try:
        db = SessionLocal()
        try:
            creator = db.get(Creator, creator_id)
            if not creator:
                job.update(state=JobState.DONE, message="creator not found")
                return

            rules = ScanRules.load(db)

            # Clear stale needs_review on this creator's already-indexed models.
            db.execute(_sqltext(
                """
                UPDATE models SET needs_review = 0
                WHERE needs_review = 1 AND creator_id = :cid
                  AND id IN (SELECT DISTINCT model_id FROM stl_files)
                """
            ), {"cid": creator_id})
            db.commit()

            dirs = _creator_dirs_for(creator, db)
            if not dirs:
                dirs = _creator_dirs_by_name(creator.name, db)
            if not dirs:
                job.update(state=JobState.DONE, message="no folders found for creator")
                return

            # Clear all STL rows for this creator's models before re-walking.
            # _index_stl_files is additive-only, so without this, stale rows from
            # a previous scan keep phantom models above the zero-STL threshold and
            # _prune_phantoms never removes them.
            model_ids = [row[0] for row in db.query(Model.id).filter(Model.creator_id == creator_id)]
            for i in range(0, len(model_ids), 500):
                chunk = model_ids[i:i + 500]
                db.query(STLFile).filter(STLFile.model_id.in_(chunk)).delete(synchronize_session=False)
            db.commit()

            walk_failures: list[ReadFailure] = []
            for creator_dir, layout_tags, grp_by_char in dirs:
                if _cancelled():
                    job.update(state=JobState.CANCELLED, message="cancelled", cancelled=True)
                    break
                _msg(f"scanning {creator_dir.name}")
                _walk_for_models(
                    folder=creator_dir,
                    creator=creator,
                    db=db,
                    creator_boundary=creator_dir,
                    character=None,
                    stl_cache={},
                    last_scanned=None,  # full reindex of this creator
                    rules=rules,
                    layout_tags=layout_tags,
                    group_by_character=grp_by_char,
                    read_failures=walk_failures,
                )
            _report_read_failures(walk_failures)

            if not _cancelled():
                # This path wiped the creator's STL rows above and rebuilt them from
                # disk, so a short listing can leave a real model looking phantom.
                # Skip the phantom prune rather than delete on an incomplete view.
                if walk_failures:
                    logger.warning(
                        f"Creator rescan hit {len(walk_failures)} unreadable entries — "
                        "phantom prune skipped to avoid removing live models"
                    )
                removed = 0 if walk_failures else _prune_phantoms(db, creator_id=creator_id)
                # Match the full-scan path: creator rescans refresh only
                # machine-owned groups after the filesystem walk. The grouping
                # service keeps manual groups and explicit no_group decisions
                # out of its candidate set.
                grouping.regroup_creator(db, creator_id)
                grouping.prune_empty_groups(db)
                db.commit()
                prog = job.payload()["progress"]
                summary = (
                    f"done — {prog.get('models_found', 0)} models, "
                    f"{prog.get('files_found', 0)} files"
                )
                if removed:
                    summary += f", {removed} removed"
                job.update(state=JobState.DONE, message=summary)
        finally:
            db.close()
    except Exception as e:
        logger.exception(f"Creator scan failed: {e}")
        job.update(state=JobState.ERROR, message=f"error: {e}", error=str(e))
    finally:
        write_lock.release_scan()
        _active = None


def split_pack(model_id: int) -> dict:
    """Opt-in: split a model whose folder is actually a multi-product pack into one
    model per child folder. Records a durable PackOverride so the split survives
    rescans, then deletes the collapsed model and re-walks the folder as a boundary.

    Returns {"ok": bool, "created": int, "message": str}. Runs synchronously and
    holds the scan lock so it can't race a running scan."""
    if not write_lock.try_acquire_for_scan():
        return {"ok": False, "created": 0, "message": "a scan is already running"}
    try:
        db = SessionLocal()
        try:
            model = db.get(Model, model_id)
            if not model:
                return {"ok": False, "created": 0, "message": "model not found"}
            creator = db.get(Creator, model.creator_id) if model.creator_id else None
            if not creator:
                return {"ok": False, "created": 0, "message": "model has no creator"}
            creator_id = creator.id

            pack = Path(model.folder_path)
            if not pack.is_dir():
                return {"ok": False, "created": 0, "message": "folder not found on disk"}

            child_dirs = [d for d in pack.iterdir() if d.is_dir()]
            try:
                any_child_has_stls = any(_has_stls(d, recurse=True) for d in child_dirs)
            except OSError:
                return {"ok": False, "created": 0,
                        "message": "couldn't read one or more child folders — try again"}
            if not any_child_has_stls:
                return {"ok": False, "created": 0,
                        "message": "no child folders with STLs to split into"}

            # Record the durable override (idempotent), then build this operation's
            # rules so the re-walk below sees it as a boundary.
            #
            # This now loads the FULL rule set, including ignore patterns. It
            # previously loaded only the overrides, so the re-walk consulted
            # whatever _ignore_matcher the module global happened to hold — the
            # previous scan's patterns in a long-lived process, empty in a fresh
            # one. That was leftover state, not a designed contract; a split now
            # honours the user's ignore rules the same way every other entry point
            # does, and does so deterministically (STUDIO-231).
            if not db.query(PackOverride).filter(PackOverride.path == str(pack)).first():
                db.add(PackOverride(path=str(pack)))
                db.commit()
            rules = ScanRules.load(db)

            # Drop the collapsed model (and its dependents) so the re-walk starts clean.
            _cascade_delete_models(db, [model_id])
            # Expunge just the deleted model so the re-walk's inserts (SQLite may
            # reuse the freed id) don't collide with it in the identity map. The
            # creator object stays attached for the walk below.
            db.expunge(model)

            # Re-walk the pack as a boundary: it's never a model, each child is.
            # Recover the layout tags for the pack's path so split children keep
            # the same above-creator auto-tags a normal scan would assign.
            pack_layout_tags: list[str] = []
            root_group_by_character = False
            for r in db.query(ScanRoot).filter(ScanRoot.enabled == True).all():
                try:
                    pack.relative_to(Path(r.path))
                except ValueError:
                    continue
                pack_layout_tags = layout.tags_for_path(pack, Path(r.path), layout.roles_for(r.layout))
                root_group_by_character = r.group_by_character
                break

            before = db.query(func.count(Model.id)).filter(Model.creator_id == creator_id).scalar() or 0
            walk_failures: list[ReadFailure] = []
            _walk_for_models(
                folder=pack,
                creator=creator,
                db=db,
                creator_boundary=pack,
                character=None,
                stl_cache={},
                last_scanned=None,
                rules=rules,
                layout_tags=pack_layout_tags,
                group_by_character=root_group_by_character,
                read_failures=walk_failures,
            )
            _report_read_failures(walk_failures)
            db.commit()
            after = db.query(func.count(Model.id)).filter(Model.creator_id == creator_id).scalar() or 0
            created = max(0, after - before)
            logger.info(f"Split pack '{pack.name}' into {created} models")
            return {"ok": True, "created": created,
                    "message": f"split into {created} models"}
        finally:
            db.close()
    except Exception as e:
        logger.exception(f"Split pack failed: {e}")
        return {"ok": False, "created": 0, "message": f"error: {e}"}
    finally:
        write_lock.release_scan()


def _scan_root(root: ScanRoot, db: Session, rules: ScanRules) -> set[int]:
    """Walk a scan root's creators in parallel. Returns the set of creator ids whose
    walk did NOT complete cleanly (raised mid-walk). Those creators were only
    partially indexed, so their models must be protected from the "not visited this
    run" stale prune — otherwise a transient error (SQLite lock, mount hiccup) makes
    unvisited-but-live models look deleted and cascades them away (STUDIO-79)."""
    root_path = Path(root.path)
    if not root_path.exists():
        logger.warning(f"Scan root not found: {root.path}")
        _msg(f"path not found: {root.path}")
        return set()

    # Resolve creator-level folders via the root's layout template. Each entry is
    # (creator_dir, layout_tags) where layout_tags are the {tag} folder names from
    # the levels above the creator (captured as auto-tags on every model beneath).
    roles = layout.roles_for(root.layout)
    creator_entries = layout.iter_creator_dirs(root_path, roles)

    # Capture last_scanned as a plain value before fanning out — `root` belongs to
    # the main-thread session and must not be touched from worker threads.
    root_last_scanned = root.last_scanned

    # Pre-create all Creator rows in the main session before going parallel so
    # worker threads never race to INSERT the same creator name. The same creator
    # name can appear under multiple {tag} branches; _get_or_create_creator dedups.
    creator_ids: dict[str, int] = {}
    for creator_dir, _tags in creator_entries:
        creator = _get_or_create_creator(creator_dir.name, db)
        creator_ids[str(creator_dir)] = creator.id
    db.commit()

    # Creators whose walk raised — collected across worker threads so the caller can
    # exclude them from the destructive stale prune (STUDIO-79). A plain set guarded
    # by a lock; contention is negligible (only touched on the exception path).
    failed_creator_ids: set[int] = set()
    failed_lock = threading.Lock()
    # Per-entry read failures across all workers. Aggregated under failed_lock and
    # reported once after the pool joins — _report_read_failures does a
    # read-modify-write on the progress payload and must not run in parallel.
    root_read_failures: list[ReadFailure] = []

    def _scan_one(creator_dir: Path, layout_tags: list[str]):
        if _cancelled():
            return
        creator_id = creator_ids[str(creator_dir)]
        thread_db = SessionLocal()
        walk_failures: list[ReadFailure] = []
        try:
            creator = thread_db.get(Creator, creator_id)
            _msg(f"scanning {creator_dir.name}")
            _walk_for_models(
                folder=creator_dir,
                creator=creator,
                db=thread_db,
                creator_boundary=creator_dir,
                character=None,
                stl_cache={},
                last_scanned=root_last_scanned,
                rules=rules,
                layout_tags=layout_tags,
                group_by_character=root.group_by_character,
                read_failures=walk_failures,
            )
            if walk_failures:
                # The walk finished, but on an incomplete view of the disk. Treat it
                # like a failed walk for prune purposes: a folder whose listing was
                # short may have classified differently (or not been reached at
                # all), so its models must not be pruned as stale this run.
                logger.warning(
                    f"Creator '{creator_dir.name}' had {len(walk_failures)} unreadable "
                    "entries — stale prune skipped for its models"
                )
                with failed_lock:
                    failed_creator_ids.add(creator_id)
                    root_read_failures.extend(walk_failures)
        except Exception:
            # Swallow so one bad creator doesn't abort the whole scan, but RECORD it:
            # a partially-walked creator's untouched models must not be pruned as
            # stale this run (STUDIO-79).
            logger.exception(f"Error scanning creator: {creator_dir.name}")
            with failed_lock:
                failed_creator_ids.add(creator_id)
        finally:
            thread_db.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_scan_one, d, tags) for d, tags in creator_entries]
        for future in as_completed(futures):
            future.result()  # propagate any unexpected exception to the outer handler

    # Single-threaded again — safe to fold the workers' read failures into progress.
    _report_read_failures(root_read_failures)

    # Propose durable variant groups (#615) once per *distinct* creator, AFTER the
    # parallel walk, on a single session. Running it inside the thread pool (once
    # per creator-dir) raced across sessions and left orphaned/duplicate groups
    # (#639). Sequential single-session regrouping is race-free. Manual groups are
    # preserved; empty auto groups are pruned.
    group_db = SessionLocal()
    try:
        for cid in dict.fromkeys(creator_ids.values()):
            try:
                grouping.regroup_creator(group_db, cid)
            except Exception:
                logger.exception(f"Error regrouping creator id={cid}")
                group_db.rollback()
        grouping.prune_empty_groups(group_db)
        group_db.commit()
    finally:
        group_db.close()

    return failed_creator_ids


def _walk_for_models(
    folder: Path,
    creator: Creator,
    db: Session,
    creator_boundary: Path,
    character: str | None,
    stl_cache: dict[str, bool],
    last_scanned: datetime | None,
    rules: ScanRules,
    parent_names: list[str] | None = None,
    layout_tags: list[str] | None = None,
    is_inbox: bool = False,
    group_by_character: bool = False,
    read_failures: list[ReadFailure] | None = None,
    boundary_is_product: bool = False,
):
    """Walk *folder*, indexing models and recursing per classification.

    ``rules`` carries this run's pack overrides and ignore patterns. Required
    rather than defaulted: these decide whether a folder becomes a model at all,
    so a caller that omitted them would silently walk with no pack splits and no
    ignore rules — the exact failure the module globals used to allow (STUDIO-231).

    ``read_failures``, when supplied, accumulates every entry this walk could not
    stat (see :func:`_list_dir`). Callers use a non-empty list as the signal to
    shield the creator from the stale prune — an incomplete listing may have
    changed which folders were classified as models, so anything not rediscovered
    this run must not be assumed deleted (same protection as STUDIO-79).

    ``boundary_is_product`` (STUDIO-377): ``creator_boundary`` means two different
    things depending on the caller. Most callers pass the actual creator's own
    folder, which can hold many unrelated products as direct children — gallery
    walks must stop at the product/character folder below it, not climb all the
    way to the creator (see :func:`_gallery_boundary`). A single-pack import
    (#1087) instead passes the *pack's own* folder as ``creator_boundary``,
    because the caller already knows that whole folder tree is one product —
    there, the format-variant siblings inside it (e.g. "(supported)" next to
    "(unsupported)") are meant to share the pack-root images, so the boundary
    must NOT be narrowed further. Set True only where ``creator_boundary`` is
    already scoped to one product, not a creator with several.
    """
    if not folder.is_dir():
        return

    # User-configured ignore patterns (#31): skip this folder and its entire
    # subtree. Checked before any classification so an ignored folder costs nothing.
    # The creator boundary itself is never ignored — a pattern that happened to match
    # a creator folder would silently drop every model under it; ignore is for
    # sub-folders (WIP dumps, archives, slicer project dirs), not whole creators.
    if folder != creator_boundary and rules.ignore.matches(folder):
        return

    # The creator-boundary folder is never itself a model. Its name may contain a
    # type keyword (e.g. "Tanuki Figures" -> "figure", "LA Figures", "X Miniatures")
    # which would otherwise trip product detection and short-circuit the whole
    # creator into a single model. Always recurse past it into the character folders.
    #
    # A folder the user has explicitly split (a pack override) is treated the same
    # way: never a model itself, always recursed past, so each child becomes its own
    # model. This is what makes an opt-in split durable across rescans.
    is_creator_root = folder == creator_boundary or str(folder) in rules.pack_overrides

    # One listing feeds all three classification inputs below. Previously each read
    # the directory again with its own error handling — child_dirs and
    # has_direct_stls let OSError propagate while the filename collection swallowed
    # it into an empty list, so whichever raised first decided the outcome. A single
    # read makes the failure handling consistent (and costs two fewer syscall
    # round-trips per folder on a network mount).
    listing = _list_dir(folder)
    if read_failures is not None:
        read_failures.extend(listing.failures)

    child_dirs = [d for d in sorted(listing.dirs) if not _is_hidden(d.name)]
    has_direct_stls = any(f.suffix.lower() in STL_EXTENSIONS for f in listing.files)
    any_child_stls = _any_child_has_stls_cached(child_dirs, stl_cache)
    has_any_stls = has_direct_stls or any_child_stls

    # File names for signal detection. Hidden files are deliberately NOT filtered
    # here — unchanged from the previous iterdir()-based collection.
    filenames = [f.name for f in listing.files]

    # --- Step 1: name-based product detection (folder + files + parents) ---
    # Require the subtree to actually contain STLs. A folder whose *name* (or whose
    # image filenames, e.g. "Auron_bust_75mm.png") trips a scale/type signal but
    # holds no printable files — render/preview folders — must never be a model.
    signals = name_parser.parse_folder(
        str(folder),
        filenames=filenames,
        parent_names=parent_names,
        rules=rules.parser_rules,
    )
    product_boundary_split = False

    # STUDIO-371: a pre-supported pack layout puts every STL one level down in
    # named part/format subfolders ("STL", "Supported STL", "Supported LYS")
    # and leaves the product's own folder with no direct STLs and no name
    # signal of its own. Without this, such a folder falls through Step 1/2/3
    # untouched and recursion visits each part subfolder independently, where
    # Step 3 (STLs here, nothing below) indexes it as its own phantom model.
    #
    # Promote the folder to a product boundary here ONLY when a STL-bearing
    # child is *positively* recognised as a parts folder (name_parser.is_parts
    # on the child's own name) — never on a low-confidence/no-signal fallback.
    # A plain character-name grouping folder (e.g. "Alien Hives" holding
    # "AH - Carnivorex", "AH - Ravenous", ...) has no such child, so this does
    # not fire there; those children keep recursing and resolve independently,
    # one model per character, exactly as before.
    # Direct (non-recursive) STLs only: a parts-named *wrapper* that holds no
    # files of its own and only reaches STLs through a further nested folder
    # (e.g. "Cloud Strife/STL/Bust") must NOT promote its parent — the real
    # product boundary is deeper, and recursion already finds it correctly.
    # Only a parts folder that directly contains the STLs (the actual
    # pre-supported pack shape: "AH - Carnivorex/STL/*.stl") qualifies.
    has_parts_child_with_stls = not has_direct_stls and any(
        name_parser.parse(d.name, rules.parser_rules).is_parts and _has_stls(d, recurse=False)
        for d in child_dirs
    )

    if not is_creator_root and has_any_stls and (signals.is_product or has_parts_child_with_stls):
        # A product-like ancestor may also contain a nested variant/product that
        # carries its own signals (Alternative, V2, another scale/type, etc.).
        # Treat those children as ownership boundaries instead of letting this
        # ancestor's recursive STL indexing claim their files. Parent-derived
        # scale is deliberately excluded from this decision: the child must
        # qualify from its own name or direct filenames, otherwise generic part
        # folders beneath a scaled product would all become separate models.
        boundary_children: list[Path] = []
        for child in child_dirs:
            child_key = str(child)
            if child_key not in stl_cache:
                stl_cache[child_key] = _has_stls(child, recurse=True)
            if not stl_cache[child_key]:
                continue
            try:
                child_filenames = [f.name for f in child.iterdir() if f.is_file()]
            except OSError:
                child_filenames = []
            child_signals = name_parser.parse_folder(
                str(child), filenames=child_filenames, parent_names=None,
                rules=rules.parser_rules,
            )
            if child_signals.is_product or _is_nested_variant_boundary(child.name):
                boundary_children.append(child)

        if not boundary_children:
            _index_model(folder, creator, db, creator_boundary, character,
                         stl_cache, auto_signals=signals, last_scanned=last_scanned,
                         layout_tags=layout_tags, is_inbox=is_inbox,
                         boundary_is_product=boundary_is_product,
                         parser_rules=rules.parser_rules)
            return

        boundary_keys = {str(child) for child in boundary_children}
        parent_has_owned_stls = has_direct_stls
        for child in child_dirs:
            child_key = str(child)
            if child_key in boundary_keys:
                continue
            if child_key not in stl_cache:
                stl_cache[child_key] = _has_stls(child, recurse=True)
            parent_has_owned_stls = parent_has_owned_stls or stl_cache[child_key]
        if parent_has_owned_stls:
            _index_model(
                folder, creator, db, creator_boundary, character, stl_cache,
                auto_signals=signals, last_scanned=last_scanned,
                layout_tags=layout_tags, is_inbox=is_inbox,
                excluded_stl_subtrees=boundary_children,
                boundary_is_product=boundary_is_product,
                parser_rules=rules.parser_rules,
            )

        # Only recurse into the independently qualifying boundaries. Other
        # descendants remain part of the parent model indexed above.
        child_dirs = boundary_children
        product_boundary_split = True

    # --- Step 2: has STLs + children look like parts ---
    if not product_boundary_split and not is_creator_root and has_any_stls:
        child_names = [d.name for d in child_dirs]
        if has_direct_stls and name_parser.children_look_like_parts(child_names, rules.parser_rules):
            _index_model(folder, creator, db, creator_boundary, character,
                         stl_cache, auto_signals=signals, last_scanned=last_scanned,
                         layout_tags=layout_tags, is_inbox=is_inbox,
                         boundary_is_product=boundary_is_product,
                         parser_rules=rules.parser_rules)
            return

    # --- Step 3: deepest fallback — STLs here, nothing below ---
    # Unlike Step 1/2, this one isn't gated on `not is_creator_root`: those
    # steps assume there's a real choice to make (recurse past this folder
    # into character folders, or split off a nested product), which only
    # makes sense when there's something to recurse into. When a "creator"
    # boundary folder has no subdirectories at all, there's nothing to
    # recurse into — the earlier rule "the creator boundary is never itself
    # a model" would silently drop every file in it. This is exactly the
    # shape of a creator whose own folder IS the product (no character
    # subfolder at all), and of the inbox importer's per-subfolder pseudo-
    # creators when an imported pack's sub-collections have no further
    # nesting of their own (e.g. a pack folder with STLs one level down in
    # several sibling sub-collection folders, none of which have their own
    # child folders — previously indexed 0 models, #1048).
    if not product_boundary_split and has_direct_stls and not any_child_stls:
        _index_model(folder, creator, db, creator_boundary, character,
                     stl_cache, auto_signals=signals, last_scanned=last_scanned,
                     layout_tags=layout_tags, is_inbox=is_inbox,
                     boundary_is_product=boundary_is_product,
                     parser_rules=rules.parser_rules)
        return

    # Not a leaf — recurse. Decide the variant-grouping "character" for each child by
    # analysing the sibling folder names together, so support/scale/format variants
    # (Supported/Unsupported/Solid/75mm…) collapse onto one product while genuinely
    # distinct products stay separate. See name_parser.character_key.
    next_parents = (parent_names or []) + [folder.name]

    # Normalised product keys for the "real" child folders (skip parts/structural
    # buckets, which never carry product identity).
    keys: dict[str, str] = {}
    for c in child_dirs:
        if (name_parser.parse(c.name, rules.parser_rules).is_parts
                or name_parser.is_structural_folder(c.name, rules.parser_rules)
                or _is_nested_variant_boundary(c.name)):
            continue
        keys[c.name] = name_parser.character_key(c.name, creator.name)
    nonempty = [k for k in keys.values() if k]
    distinct = set(nonempty)
    counts = Counter(nonempty)

    # This folder's own identity. Use the *raw* folder name (not the normalised key)
    # so a real character keeps its readable label, e.g. "Auron - Final Fantasy X".
    # The creator root and structural/parts folders carry no identity of their own —
    # at the creator root own_character stays None so its children decide for
    # themselves (a standalone product groups only with key-sharing siblings).
    own_character = character
    if (not is_creator_root
            and not signals.is_parts
            and not name_parser.is_structural_folder(folder.name, rules.parser_rules)
            and not _is_nested_variant_boundary(folder.name)
            and name_parser.character_key(folder.name, creator.name)):
        own_character = folder.name

    #   strict-majority shared key → children are support/format/scale variants of one
    #                                product (label it by THIS folder's name); a few
    #                                odd-named or typo'd leaves fold in with the majority
    #   multiple keys, none dominant → separate products: keep each child's own key
    #   no product keys at all       → variant descriptors of THIS folder
    if not nonempty:
        strategy, common_key = "parent", None
    else:
        top_key, top_n = counts.most_common(1)[0]
        # > half of the real children share one key (and at least two do), OR a single
        # real child carries the only identity → one product. Strict majority (not ≥)
        # keeps an even 2-vs-2 split of two distinct products from collapsing.
        if (top_n >= 2 and top_n * 2 > len(keys)) or (len(distinct) == 1 and len(keys) == 1):
            strategy, common_key = "common", top_key
        else:
            strategy, common_key = "leaf", None

    # For a "common" group, label by the shared key (which carries whatever context
    # the leaf names hold, e.g. a faction prefix "Crimson Wings APC") — UNLESS the key
    # is merely this folder's own cleaned name plus a trailing junk token such as a
    # creator tag ("Ada Wong" vs "Ada Wong CA3D"), in which case the cleaned folder
    # name is the better label. Require the folder's key to be a *strictly shorter*
    # prefix of the shared key: equal-length means there is no junk to drop, and the
    # raw folder name may still hold a support word ("…unsupported"). Computed once.
    common_label = common_key
    if strategy == "common" and own_character:
        own_key = name_parser.character_key(own_character, creator.name)
        if (own_key and len(own_key) < len(common_key)
                and common_key.lower().startswith(own_key.lower())):
            common_label = own_key

    for child in sorted(child_dirs):
        if group_by_character:
            # Folder-driven grouping (opt-in): the first folder below the creator
            # names the group; every model beneath inherits it, so the whole
            # character subtree is one variant group. `character` is None only at
            # the creator boundary, where each child becomes its own group.
            child_character = character if character is not None else child.name
        elif strategy == "common":
            child_character = common_label
        elif strategy == "leaf":
            child_character = keys.get(child.name) or own_character
        else:  # parent
            child_character = own_character
        _walk_for_models(child, creator, db, creator_boundary,
                         character=child_character, parent_names=next_parents,
                         stl_cache=stl_cache, last_scanned=last_scanned,
                         rules=rules,
                         layout_tags=layout_tags, is_inbox=is_inbox,
                         group_by_character=group_by_character,
                         read_failures=read_failures,
                         boundary_is_product=boundary_is_product)

    # Two sibling branches (e.g. "Mult Color Filament" / "One Color Filament")
    # can each independently reach the "leaf" strategy at some depth and each
    # produce a child whose OWN folder name is the same identity-bearing
    # string ("EchoMasteryTracker") — the leaf strategy has no memory of which
    # branch it's under, so both get the identical character. Untouched, that
    # collapses their destination folders onto one another at import/apply
    # time (a real destination-collision incident: "Mult Color Filament"
    # could never import because "One Color Filament" already claimed
    # "EchoMasteryTracker"'s destination). Only run this once per top-level
    # walk, scoped to what this walk just touched.
    if is_creator_root:
        _disambiguate_colliding_characters(db, creator.id, folder)


def _disambiguate_colliding_characters(db: Session, creator_id: int, boundary: Path) -> None:
    """Rename characters that collided across distinct branches of this walk.

    Only a model whose character was assigned fresh at its OWN leaf level —
    i.e. nobody grouped it with siblings, its character is simply its own
    folder's name — is a candidate. That's deliberate: the "common"/"parent"
    strategies also produce several models sharing one character with
    different immediate parents (e.g. a product's "STL" and "Presupport"
    variant folders correctly sharing the product's character) — that's
    intentional grouping, not a collision, and must be left untouched. A
    model whose character was inherited from an ancestor's grouping decision
    never equals its own bare folder name, so that's the signal: only two
    *independent* leaves — each carrying nothing but its own name, reached
    via two different, unrelated parents — are a real collision.

    Scoped to models under ``boundary`` only — a wider, whole-creator sweep
    would risk renaming unrelated models from an earlier, separate scan that
    happen to legitimately share a character (same product name used across
    two different packs)."""
    models = [
        m for m in db.query(Model).filter(Model.creator_id == creator_id).all()
        if m.folder_path and _is_within_boundary(m.folder_path, boundary)
    ]
    groups: dict[str, list[Model]] = {}
    for m in models:
        if m.character and m.character == Path(m.folder_path).name:
            groups.setdefault(m.character, []).append(m)

    changed = False
    for character, group in groups.items():
        if len(group) < 2:
            continue
        by_parent: dict[str, list[Model]] = {}
        for m in group:
            by_parent.setdefault(Path(m.folder_path).parent.name, []).append(m)
        if len(by_parent) < 2:
            continue  # one shared parent — an intentional grouped variant set
        for parent_name, members in by_parent.items():
            label = f"{parent_name} — {character}"
            for m in members:
                if m.name == m.character:
                    m.name = label
                m.character = label
                changed = True
    if changed:
        db.commit()


def _index_model(
    folder: Path,
    creator: Creator,
    db: Session,
    creator_boundary: Path | None,
    character: str | None,
    stl_cache: dict[str, bool],
    auto_signals: name_parser.NameSignals | None = None,
    last_scanned: datetime | None = None,
    layout_tags: list[str] | None = None,
    is_inbox: bool = False,
    excluded_stl_subtrees: list[Path] | None = None,
    boundary_is_product: bool = False,
    parser_rules: name_parser.ParserRules = name_parser.ParserRules(),
):
    folder_path = str(folder)

    # Serialize all DB interaction for this model. SQLite has a single writer;
    # holding this lock across the read/query + writes + commit keeps the worker
    # threads from contending at the SQLite level (which otherwise surfaces as
    # "database is locked" and drops a creator's models).
    with _db_lock:
        model = db.query(Model).filter(Model.folder_path == folder_path).first()

        # Case-insensitive identity fallback (STUDIO-78). On a case-insensitive
        # volume (Windows) a casing change to any ancestor folder — a scan root
        # re-added at different case, or a creator/character folder renamed
        # 'polyminds studios' → 'PolyMind Studios' — makes the exact match above
        # miss. Left alone that orphans the existing row (is_new=True inserts a
        # fresh one, then _prune_stale_models deletes the old), silently wiping
        # all user metadata and emptying manual variant groups. Fall back to a
        # normalized-path match, scoped to this creator, and adopt the new casing
        # in place so identity — and everything hanging off it — survives.
        # Only case-insensitive volumes can produce this miss, so skip the extra
        # query entirely on case-sensitive filesystems (Linux servers/CI), where
        # a differently-cased path is a genuinely different folder (STUDIO-226).
        #
        # The SQL match keeps this to a single narrow query per new model instead
        # of scanning every model for the creator; the _normpath guard on each
        # result is what actually decides identity, so the query only has to be
        # loose enough not to miss a real match.
        #
        # Separators are folded on BOTH sides (STUDIO-365). _normpath() is
        # normcase(normpath(...)), which on Windows folds case *and* rewrites '/'
        # to '\'. A prefilter that folded case alone therefore could not see a row
        # stored in forward-slash form — 'F:/lib/x' vs 'F:\lib\x' compare unequal
        # under lower() — so the guard below never ran and a duplicate row was
        # inserted for a folder already indexed. Such duplicates then survive every
        # prune, because on a case-insensitive volume the forward-slash path still
        # exists() and the row looks live.
        #
        # Still not folded here: '..' segments and repeated separators, which
        # normpath() would collapse but this comparison will not. A row stored in
        # such a form remains un-matchable; no writer is known to produce one.
        recased_from: str | None = None
        if model is None and _normpath("A") == _normpath("a"):
            target_norm = _normpath(folder_path)
            candidates = (
                db.query(Model)
                .filter(Model.creator_id == creator.id,
                        func.lower(func.replace(Model.folder_path, "\\", "/"))
                        == folder_path.lower().replace("\\", "/"))
                .all()
            )
            matches = [
                c for c in candidates
                if c.folder_path and _normpath(c.folder_path) == target_norm
            ]
            if len(matches) > 1:
                # Pre-existing duplicates for one physical folder (the bug above,
                # before it was fixed). Adopting one leaves the rest stale and
                # unprunable; surface it rather than silently picking one.
                logger.warning(
                    f"{len(matches)} model rows resolve to the same folder "
                    f"{folder_path!r}: ids={[m.id for m in matches]}. Adopting "
                    f"id={matches[0].id}; the others need manual cleanup."
                )
            if matches:
                model = matches[0]
                recased_from = model.folder_path

        # User-excluded model: leave it hidden. Never re-index, re-tag, or reset
        # the flag, so a rescan never resurrects something the user removed.
        if model is not None and model.excluded:
            return

        # Adopt the new casing on the reused row and its STL files (identity
        # preserved above). Done after the excluded check so hidden models stay
        # untouched; before file indexing so _index_stl_files matches by the
        # refreshed paths instead of inserting duplicates.
        if recased_from is not None and recased_from != folder_path:
            _recase_model_paths(db, model, recased_from, folder_path)

        # Skip expensive file indexing when the folder hasn't changed since the
        # last scan. Metadata/tag updates still run so manual edits and parser
        # improvements are picked up.
        folder_unchanged = (
            model is not None
            and last_scanned is not None
            # utc_timestamp, not .timestamp(): last_scanned is naive UTC, and
            # .timestamp() would read it as local time — skewing the baseline
            # by the host's UTC offset and skipping real changes (STUDIO-294).
            and folder.stat().st_mtime < utc_timestamp(last_scanned)
        )

        # Clean, human-readable display name derived from the raw folder name
        # (strips scale/support/slicer/version/junk, title-cased). The raw folder
        # name stays the source of truth on disk; folder_path is unchanged.
        clean_name = name_parser.display_name(folder.name, creator.name)

        # A structural leaf folder (STL, supported, presupported, renders…) carries
        # no product identity — naming the model "STL"/"supported" produces junk
        # cards (#641). Name it after its product instead.
        #
        # The nearest non-structural ANCESTOR wins over the walk `character`: the
        # ancestor is positionally guaranteed to own this folder, whereas the
        # character is carried down the walk and can survive across sibling
        # subtrees. Preferring the character named "RPG Bases/RPG Bases Supported"
        # after an unrelated sibling release (STUDIO-289). The character remains the
        # fallback for layouts where no ancestor qualifies.
        if (name_parser.is_structural_folder(folder.name, parser_rules)
                or _is_nested_variant_boundary(folder.name)):
            product = None
            top_level = None          # last ancestor before the creator boundary
            for anc in folder.parents:
                if anc == creator_boundary or anc == anc.parent:
                    break
                if name_parser.is_container_folder(anc.name):
                    continue
                top_level = anc.name
                if not name_parser.is_structural_folder(anc.name, parser_rules):
                    product = anc.name
                    break
            # No ancestor reads as a product by its words alone. A folder sitting
            # directly under the creator is one by POSITION regardless — "RPG Bases"
            # is a real release even though every token in it is a parts word.
            # Preferring it over `character` is what stops an unrelated sibling
            # release's name from leaking in. (STUDIO-287 case B / STUDIO-289)
            if not product:
                product = top_level or character
            if product:
                clean_name = name_parser.display_name(product, creator.name) or product

        # A name with no identity of its own ("Bases", "Parts") collides with every
        # other such folder in the library — 11 Titan Forge models all landed on
        # "Bases" in one variant group. Qualify it with the owning release/product
        # instead. Only fires when the derived name is generic, so a correctly
        # derived name ("Gridrunner") never enters this branch. (STUDIO-287)
        if name_parser.is_generic_name(clean_name, parser_rules):
            for anc in folder.parents:
                if anc == creator_boundary or anc == anc.parent:
                    break
                if name_parser.is_container_folder(anc.name):
                    continue
                qualifier = name_parser.qualifier_from_folder(anc.name)
                if qualifier:
                    clean_name = name_parser.qualify_generic_name(clean_name, qualifier)
                    break

        is_new = model is None
        if is_new:
            model = Model(
                name=clean_name,
                folder_path=folder_path,
                creator_id=creator.id,
            )
            db.add(model)
            db.flush()
        else:
            # Model.name is scanner-owned: it is set here and at the Model(...)
            # construction above, and NOWHERE else in the codebase. There is no
            # rename endpoint (ModelUpdate has no `name` field — users edit `title`)
            # and no UI path, so a name always reflects some past run of this
            # derivation. Refresh it unconditionally so parser improvements reach
            # existing rows.
            #
            # This replaces the STUDIO-282 predicate, which only refreshed a name
            # that matched the folder name, matched the new derivation, or was
            # itself structural. That guarded against a user rename which cannot
            # happen, and the cost was severe: any name an older parser *derived*
            # ("Semi" from "Semi_cutted") matched none of the three cases and was
            # pinned forever, silently immune to every future fix. STUDIO-288
            # landed correct yet changed nothing on rescan for exactly this reason.
            #
            # If a rename feature is ever added, it must record that intent
            # explicitly (e.g. a name_is_user_set column) and this branch must
            # honour it — do not reintroduce shape-based inference. (STUDIO-290)
            model.name = clean_name

        # Scanner-owned structured variant attributes (support/cut/slicer/version).
        # Kept separate from user-set custom_attributes so a rescan never clobbers
        # user edits. Recomputed every scan so parser improvements propagate.
        model.parsed_attributes = name_parser.parsed_attributes(folder.name)

        # Character grouping — a read-only scanner-derived attribute (#678 Phase 5):
        # always reflect the current walk (including None) so a model whose path
        # is all-structural clears any stale character. Grouping itself is owned
        # entirely by variant_group_id / the proposal engine, not this column.
        model.character = character

        # Auto-detected signals, merged with layout-derived tags (from {tag}
        # folder levels above the creator). Lower-cased and de-duplicated, order
        # preserved: detected signals first, then layout tags. The walk always
        # passes auto_signals, so this also covers the layout-tags-only case.
        if auto_signals:
            model.auto_tags = _merge_auto_tags(auto_signals.auto_tags, layout_tags)
            # Only flag needs_review for brand-new models that look genuinely
            # ambiguous: no name/type signals AND no direct STL files in this
            # folder (only found recursively). Existing models are cleared at
            # scan start if they have STL files, so we avoid re-flagging the
            # same false positives on every rescan.
            if is_new and auto_signals.confidence < 0.25:
                has_direct_stls = _has_stls(folder, recurse=False)
                if not has_direct_stls:
                    model.needs_review = True

        if not folder_unchanged:
            gallery_boundary = (
                (creator_boundary or folder) if boundary_is_product
                else _gallery_boundary(folder, creator_boundary)
            )
            try:
                gallery_images = _collect_gallery_images(
                    folder,
                    boundary=gallery_boundary,
                    stl_cache=stl_cache,
                )
            except OSError:
                # A transient read failure (drive hiccup, permission blip) —
                # not "this model's images are gone". Leave image_paths/
                # thumbnail_path exactly as they are; a later scan re-tries.
                logger.warning(
                    "Gallery image discovery failed for %s — leaving existing "
                    "image_paths untouched this scan", folder, exc_info=True,
                )
                gallery_images = None

            if gallery_images is not None:
                # Thumbnail: walk upward if not already set
                if not model.thumbnail_path:
                    if gallery_images:
                        model.thumbnail_path = str(gallery_images[0])

                model.image_paths = _merge_scan_gallery_paths(
                    existing=model.image_paths or [],
                    discovered=[str(img) for img in gallery_images],
                    removed=model.removed_image_paths or [],
                    boundary=gallery_boundary,
                )

            _index_stl_files(
                model, folder, db,
                excluded_subtrees=excluded_stl_subtrees,
            )

        if is_inbox:
            model.is_inbox = True

        model.updated_at = utcnow()
        sync_model_tags(model, db)
        db.commit()

    _bump(models_found=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normpath(p: str) -> str:
    """Normalize a filesystem path for MODEL IDENTITY comparison — case- and
    separator-folded on the current platform (case-insensitive on Windows).

    Currently identical to services/path_boundary.normalize(), and deliberately
    kept as a separate function rather than delegating to it. The two answer
    different questions and are expected to diverge:

    * ``path_boundary`` compares paths against roots on THIS host — a live
      filesystem question, so host casing semantics are correct there permanently.
    * This one decides whether a path is the same LIBRARY OBJECT as a stored row.
      STUDIO-78 made it match the prune normalization so lookup and prune agree;
      STUDIO-359 will make it canonical and host-INDEPENDENT so a database is
      portable between the Docker and Windows deployments.

    Collapsing them would make that change silently alter prune membership too.
    """
    return os.path.normcase(os.path.normpath(p))


def _recase_model_paths(db: Session, model: Model, old_folder_path: str, new_folder_path: str):
    """Adopt a case- or separator-only folder rename on an existing model in place
    (STUDIO-78, extended by STUDIO-365).

    Updates the model's folder_path and rewrites the prefix of every child
    STLFile.path so they line up with the folder as the walk sees it. The relative
    suffix under the model folder names the same files either way, so a prefix
    swap preserves STL-level metadata (sup_of_id, part_name) that a
    delete-and-reindex would drop.

    Both the prefix test and the suffix are separator-folded. A plain
    ``startswith`` missed a stored path that differed from the model folder only
    by separator style, and even when it matched it left the OLD style in the
    suffix — producing a mixed path like ``C:\\lib\\Model/part.stl`` that
    ``_index_stl_files`` then failed to match, inserting a duplicate row and
    stranding the original's metadata.

    Only reached from the case-insensitive-volume fallback in ``_index_model``,
    so folding separators is safe here: on a case-sensitive host a backslash is a
    legal filename character and this code does not run.
    """
    model.folder_path = new_folder_path
    old_norm = _normpath(old_folder_path)
    for stl in db.query(STLFile).filter(STLFile.model_id == model.id).all():
        if not stl.path:
            continue
        # Compare normalized, but slice the RAW path so the file's own casing is
        # preserved. normcase/normpath are length-preserving for these inputs
        # (case fold and separator swap are both one-for-one), so the offset is
        # valid on either form.
        if not _normpath(stl.path).startswith(old_norm):
            continue
        suffix = stl.path[len(old_folder_path):]
        stl.path = new_folder_path + suffix.replace("\\", os.sep).replace("/", os.sep)


def _merge_auto_tags(detected: list[str], layout_tags: list[str] | None) -> list[str]:
    """Combine detected auto-tags with layout-derived tags, lower-cased and
    de-duplicated while preserving order (detected first, then layout)."""
    merged: list[str] = []
    seen: set[str] = set()
    for raw in list(detected or []) + list(layout_tags or []):
        t = (raw or "").strip().lower()
        if t and t not in seen:
            seen.add(t)
            merged.append(t)
    return merged


def _is_hidden(name: str) -> bool:
    """True for dotfile/dot-directory names (.git, .DS_Store, …).

    Other tools stash their own metadata/derivative caches in hidden folders
    alongside real content — e.g. a resized-thumbnail cache nested several
    levels deep. None of that should ever be treated as a model, an STL, or a
    gallery image.
    """
    return name.startswith(".")


def _is_nested_variant_boundary(name: str) -> bool:
    """True for a variant descriptor that should own its physical subtree."""
    return bool(NESTED_VARIANT_BOUNDARY.fullmatch(name.strip()))


def _has_hidden_ancestor(path: Path, within: Path) -> bool:
    """True if any directory component between *within* and *path* is hidden."""
    try:
        parts = path.relative_to(within).parts
    except ValueError:
        return False
    return any(_is_hidden(p) for p in parts[:-1])


def _iter_files_recursive(folder: Path):
    """Yield every non-hidden file under folder, recursing into subdirectories.

    Deliberately NOT built on Path.rglob()/glob(): both silently swallow any
    OSError while listing a subdirectory (see CPython's _WildcardSelector —
    a bare ``except OSError: pass``), so an unreadable folder anywhere in the
    tree looks identical to "this subtree is genuinely empty". That
    difference matters here: a caller that merges this into image_paths (a
    destructive prune of anything not rediscovered) must be able to tell a
    transient read failure apart from a real deletion, so this walk lets
    OSError/PermissionError propagate instead.
    """
    with os.scandir(folder) as it:
        entries = list(it)
    for entry in entries:
        if _is_hidden(entry.name):
            continue
        if entry.is_dir():
            yield from _iter_files_recursive(Path(entry.path))
        else:
            yield Path(entry.path)


def _list_dir(folder: Path) -> DirListing:
    """List a folder's immediate children, tolerating PER-ENTRY stat failures.

    Two failure modes must be told apart, because they need opposite handling:

    * The whole directory cannot be listed (permissions, vanished mount). The
      OSError PROPAGATES — the creator walk catches it and shields that creator's
      models from the stale prune (STUDIO-79). Swallowing it here would remove
      that protection and let a transient mount drop prune a live library.
    * A single entry cannot be stat'd while the directory itself lists fine. This
      is the common Windows case: the directory path fits inside MAX_PATH but an
      individual child's full path does not, so ``is_dir()`` raises for that entry
      alone. It also covers broken symlinks and dehydrated cloud placeholders.
      Aborting the whole folder over one bad entry would be worse than useless, so
      the entry is skipped — but RECORDED, never silently dropped.

    Recording matters because an incomplete listing is not inert: it feeds
    ``name_parser.parse_folder()`` product detection, so a missing file can change
    whether this folder becomes a model at all. Same reasoning as
    :func:`_iter_files_recursive`, which avoids rglob for exactly this reason.
    """
    with os.scandir(folder) as it:
        entries = list(it)

    dirs: list[Path] = []
    files: list[Path] = []
    failures: list[ReadFailure] = []
    for entry in entries:
        try:
            is_dir = entry.is_dir()
        except OSError as e:
            failures.append(ReadFailure(path=entry.path, error=str(e)))
            continue
        (dirs if is_dir else files).append(Path(entry.path))
    return DirListing(dirs=dirs, files=files, failures=failures)


def _report_read_failures(failures: list[ReadFailure]) -> None:
    """Push per-entry read failures onto scan progress and the log.

    Call from single-threaded code only: the bounded sample is a read-modify-write
    on the progress payload, which the parallel creator workers must not race on.
    ``_scan_root`` therefore aggregates its workers' failures under the existing
    ``failed_lock`` and reports once, after the pool joins.
    """
    if not failures:
        return
    for f in failures:
        logger.warning(f"Scan could not read entry (skipped, folder still indexed): {f.path} — {f.error}")
    if _active is None:
        return
    _active.increment(read_failures=len(failures))
    existing = _active.payload()["progress"].get("read_failure_samples", []) or []
    room = READ_FAILURE_SAMPLE_LIMIT - len(existing)
    if room > 0:
        _active.update(read_failure_samples=existing + [f.path for f in failures[:room]])


def _has_stls(folder: Path, recurse: bool = False) -> bool:
    if recurse:
        return any(p.suffix.lower() in STL_EXTENSIONS for p in _iter_files_recursive(folder))
    return any(f.suffix.lower() in STL_EXTENSIONS for f in folder.iterdir() if f.is_file())


def _any_child_has_stls_cached(child_dirs: list[Path], cache: dict[str, bool]) -> bool:
    for d in child_dirs:
        key = str(d)
        if key not in cache:
            cache[key] = _has_stls(d, recurse=True)
        if cache[key]:
            return True
    return False


def _path_identity(path: str) -> str:
    if "://" in path:
        return path
    return _normpath(path)


def _is_within_boundary(path: str, boundary: Path) -> bool:
    if "://" in path:
        return False
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            return False
        candidate_resolved = candidate.resolve(strict=False)
        boundary_resolved = boundary.resolve(strict=False)
        return os.path.commonpath([str(candidate_resolved), str(boundary_resolved)]) == str(boundary_resolved)
    except (OSError, ValueError):
        return False


def _image_files_recursive(folder: Path) -> list[Path]:
    # _iter_files_recursive (not rglob/glob) so a transient read failure
    # (external-drive hiccup, permission blip) propagates instead of looking
    # identical to "this folder genuinely has no images" — see its docstring.
    return sorted(
        p for p in _iter_files_recursive(folder)
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )


def _gallery_boundary(folder: Path, creator_boundary: Path | None) -> Path:
    """The real ceiling for a gallery-image walk: the character/product folder
    directly under the creator, not the whole creator (STUDIO-377).

    A model's own leaf can sit arbitrarily deep under the creator (Step 1/2/3 of
    _walk_for_models index a model at whatever depth first qualifies), so this
    walks up `folder`'s ancestors until it finds the one whose *parent* is the
    creator boundary — the creator's immediate child. Sharing images within that
    child's own subtree (e.g. a diorama folder's renders shared by its several
    character models) is still intentional and unaffected. Sharing across
    *sibling* children — a completely different product, or a stray image
    dropped straight in the creator's own folder — is exactly what let one
    product's marketing images bleed into every other model under the same
    creator (Darth Vader Samurai/Regina's images into unrelated CA 3D Studios
    models; a loose "RPG Pack - Names.jpg" into every DM Stash model).

    Falls back to `folder` itself when there's no creator boundary to scope to,
    and returns `folder` unchanged for the documented edge case where the
    creator's own folder IS the product (no character level to climb to).
    """
    if creator_boundary is None:
        return folder
    if folder == creator_boundary:
        return folder
    current = folder
    while current.parent != creator_boundary:
        if current.parent == current:
            return creator_boundary
        current = current.parent
    return current


def _collect_gallery_images(leaf: Path, boundary: Path,
                            stl_cache: dict[str, bool] | None = None) -> list[Path]:
    """
    Walk upward from leaf to creator boundary looking for gallery images.

    Priority at each level:
      1. Preferred image subdirs, recursively
      2. Direct image files in the folder itself
      3. Any other subdir that doesn't contain STLs

    Raises OSError/PermissionError if any folder along the way couldn't be
    listed — deliberately not caught here. Callers that merge the result into
    image_paths (dropping anything not rediscovered) must catch this and skip
    that merge rather than trust a possibly-incomplete listing as if it were
    a confirmed-empty one.
    """
    def _has_stls_cached(d: Path) -> bool:
        key = str(d)
        if stl_cache is not None:
            if key not in stl_cache:
                stl_cache[key] = _has_stls(d, recurse=True)
            return stl_cache[key]
        return _has_stls(d, recurse=True)

    def images_at(folder: Path) -> list[Path]:
        children = list(folder.iterdir())
        subdirs = [c for c in children if c.is_dir() and not _is_hidden(c.name)]
        found: list[Path] = []

        for sub in sorted(subdirs):
            if sub.name.lower() in PREFERRED_IMAGE_DIRS:
                found.extend(_image_files_recursive(sub))

        found.extend(
            f for f in sorted(children)
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        )

        for sub in sorted(subdirs):
            if sub.name.lower() in PREFERRED_IMAGE_DIRS or _has_stls_cached(sub):
                continue
            # A no-STL sibling that's itself a print-format-variant folder
            # (e.g. "Product (chitubox)" next to "Product (supported)" /
            # "Product (unsupported)") almost always bundles its own copy of
            # the SAME marketing images, not new content — sweeping those in
            # duplicates every other variant's own gallery with redundant,
            # identically-numbered files (#1114). A genuine bonus-images
            # folder ("renders", "Render Images", ...) has no such signal
            # and is still swept in below.
            if name_parser.support_status(sub.name) or name_parser.slicer(sub.name):
                continue
            found.extend(_image_files_recursive(sub))

        return found

    images: list[Path] = []
    seen: set[str] = set()
    current = leaf
    while True:
        for img in images_at(current):
            key = _normpath(str(img))
            if key not in seen:
                seen.add(key)
                images.append(img)
        if current == boundary or current.parent == current:
            break
        current = current.parent
    return images


def _merge_scan_gallery_paths(
    existing: list,
    discovered: list[str],
    removed: list,
    boundary: Path,
) -> list[str]:
    discovered_keys = {_path_identity(p) for p in discovered if isinstance(p, str) and p}
    removed_keys = {
        _path_identity(p) for p in removed
        if isinstance(p, str) and p
    }
    result: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        key = _path_identity(path)
        if key in removed_keys or key in seen:
            return
        seen.add(key)
        result.append(path)

    for path in discovered:
        if isinstance(path, str) and path:
            add(path)

    for path in existing:
        if not isinstance(path, str) or not path:
            continue
        key = _path_identity(path)
        if _is_within_boundary(path, boundary) and key not in discovered_keys:
            continue
        add(path)

    return result


def refresh_model_gallery(db: Session, model: Model) -> None:
    """Re-sync one model's gallery images with what's actually on disk.

    Reuses the same discovery/merge primitives a full or per-creator scan
    applies to every model (_collect_gallery_images / _merge_scan_gallery_paths)
    — just scoped to this one model, on demand, without touching naming, tags,
    or STL indexing. Mutates the passed-in ORM object; the caller commits.

    Raises OSError/PermissionError if the folder listing failed partway
    through (a transient drive/permission hiccup) — deliberately not caught
    here, and nothing has been mutated yet when it's raised, so the caller
    can surface the failure instead of silently treating an unreliable
    listing as "no images here anymore".
    """
    folder = Path(model.folder_path)
    if not folder.exists():
        return

    creator_boundary: Path | None = None
    creator = model.creator or (
        db.query(Creator).filter(Creator.id == model.creator_id).first()
        if model.creator_id else None
    )
    if creator:
        for creator_dir, _tags, _grp in _creator_dirs_for(creator, db):
            if _is_within_boundary(str(folder), creator_dir):
                creator_boundary = creator_dir
                break

    boundary = _gallery_boundary(folder, creator_boundary)
    gallery_images = _collect_gallery_images(folder, boundary=boundary, stl_cache={})

    if not model.thumbnail_path and gallery_images:
        model.thumbnail_path = str(gallery_images[0])

    model.image_paths = _merge_scan_gallery_paths(
        existing=model.image_paths or [],
        discovered=[str(img) for img in gallery_images],
        removed=model.removed_image_paths or [],
        boundary=boundary,
    )

    if model.primary_image_path and model.primary_image_path not in model.image_paths:
        model.primary_image_path = None


def _index_stl_files(
    model: Model,
    folder: Path,
    db: Session,
    excluded_subtrees: list[Path] | None = None,
):
    # Gather candidate STL files under this folder.
    excluded = {
        _normpath(str(path)) for path in (excluded_subtrees or [])
    }

    def is_excluded(path: Path) -> bool:
        normalized = _normpath(str(path))
        return any(
            normalized == root or normalized.startswith(root + os.sep)
            for root in excluded
        )

    candidates = [
        stl for stl in sorted(folder.rglob("*"))
        if stl.is_file()
        and not is_excluded(stl)
        and stl.suffix.lower() in STL_EXTENSIONS
        and stl.suffix.lower() not in SLICER_EXTENSIONS
    ]
    if not candidates:
        return

    # PROJECT_BUNDLE_EXTENSIONS (.3mf) stay in STL_EXTENSIONS (a lone .3mf
    # folder must still be recognised as a model — see the comment there),
    # but it's a project/bundle format, not a single printable part, so it's
    # filed as other_files rather than getting its own STLFile row. Split it
    # out before the STLFile loop below; merge (not overwrite) so a rescan
    # doesn't drop a file the same folder already indexed under other_files
    # for an unrelated reason.
    other_candidates = [c for c in candidates if c.suffix.lower() in PROJECT_BUNDLE_EXTENSIONS]
    candidates = [c for c in candidates if c.suffix.lower() not in PROJECT_BUNDLE_EXTENSIONS]
    if other_candidates:
        model.other_files = _merge_scan_gallery_paths(
            existing=model.other_files or [],
            discovered=[str(c) for c in other_candidates],
            removed=[],
            boundary=folder,
        )
        # Self-healing: a .3mf indexed as an STLFile row by a scan that ran
        # before this behaviour changed would otherwise linger forever —
        # _index_stl_files never revisits a path it's already seen (see the
        # `existing` check below), so without this it'd show up as both a
        # tracked file and an other_file until the row was cleaned up by hand.
        other_paths = [str(c) for c in other_candidates]
        (
            db.query(STLFile)
            .filter(STLFile.model_id == model.id, STLFile.path.in_(other_paths))
            .delete(synchronize_session=False)
        )
    if not candidates:
        return

    # Find which of these are already indexed by exact path. A parent model's
    # rglob may have already claimed files that belong to a sub-folder model,
    # so we check the entire stl_files table, not just this model's rows.
    # We match on exact paths (chunked to stay under SQLite's bind-variable
    # limit) rather than a LIKE prefix — the stored paths use the OS separator
    # and folder names routinely contain '_', a LIKE wildcard.
    candidate_paths = [str(stl) for stl in candidates]
    model_key = _normpath(str(folder))
    existing: dict[str, tuple[STLFile, str]] = {}
    for i in range(0, len(candidate_paths), 500):
        chunk = candidate_paths[i:i + 500]
        existing.update({
            row.path: (row, owner_folder)
            for row, owner_folder in (
                db.query(STLFile, Model.folder_path)
                .join(Model, STLFile.model_id == Model.id)
                .filter(STLFile.path.in_(chunk))
            )
        })

    for stl, path_str in zip(candidates, candidate_paths):
        if path_str in existing:
            # A pre-fix ancestor model may already own this exact path. The
            # current, deeper boundary is now authoritative; transfer the row
            # in place so user-owned STL metadata survives the repair scan. A
            # parent scan must never steal a path back from its child model.
            row, owner_folder = existing[path_str]
            owner_key = _normpath(owner_folder)
            if model_key.startswith(owner_key + os.sep):
                row.model_id = model.id
            continue
        # part_name is auto-derived once, at first discovery, so a freshly
        # scanned/imported file has a real saved name immediately instead of
        # just the dimmed filename-derived placeholder the UI shows for a
        # genuinely empty one. Never touched again after this insert — a
        # later manual rename (or an AI Organize suggestion) always wins,
        # since existing rows are skipped entirely above.
        row = STLFile(
            model_id=model.id,
            path=path_str,
            filename=stl.name,
            size_bytes=stl.stat().st_size,
            part_name=clean_name(stl.name) or None,
        )
        db.add(row)
        existing[path_str] = (row, str(folder))
        _bump(files_found=1)


def _get_or_create_creator(name: str, db: Session) -> Creator:
    """Get-or-create for a creator named after an on-disk folder.

    Delegates to resolve_creator so folder-derived names use the same
    case-insensitive dedup rule as scraped and user-entered ones. Before
    STUDIO-298 this matched exact case only, so a creator already stored
    with different casing than the folder — a scraped "Abe3d" alongside a
    folder "abe3d" — made every scan insert a second Creator row.

    Deliberately case-insensitive on every platform, including
    case-sensitive filesystems where "Abe3D/" and "abe3d/" can coexist:
    two spellings of one creator are one creator, and each model still
    records its own folder_path. Note this is the opposite of the model
    -folder identity rule, which is host-sensitive by design (_normpath).

    The Linux case-variant adoption is logged: it is harmless when the two
    spellings are one artist (the common case, and unavoidable on Windows
    and macOS where the filesystem itself folds case), but it would merge
    two genuinely different artists onto one creator. That is recoverable
    by renaming a folder and rescanning, and no model is lost either way,
    but it should not happen without a trace.
    """
    creator = resolve_creator(name, db)
    if creator.name != name.strip():
        logger.warning(
            "Folder %r indexed under existing creator %r (differs only by case or "
            "surrounding whitespace). Rename the folder and rescan if these are "
            "meant to be separate creators.",
            name, creator.name,
        )
    return creator


def resolve_creator(name: str, db: Session) -> Creator:
    """Case-insensitive get-or-create for use outside the scanner.

    Matches an existing creator by name (case-insensitive) so that a
    scraped name like 'Abe3d' doesn't create a duplicate alongside a
    folder-derived 'abe3d'. If no match exists, creates with the
    supplied casing.

    Lowered equality, NOT ilike: % and _ are LIKE wildcards, and
    underscores are common in creator names ('My_Studio' would
    ilike-match 'MyXStudio') (#217).
    """
    name = name.strip()
    creator = db.query(Creator).filter(func.lower(Creator.name) == name.lower()).first()
    if not creator:
        creator = Creator(name=name)
        db.add(creator)
        db.flush()
    return creator


def prepare_inbox_scan() -> bool:
    """Synchronously acquire the library write lock for an inbox import.

    Returns True if the lock was acquired, False if the library is busy. Called in
    the request thread before launching the import so the HTTP response is
    authoritative: a 200 means the import is actually starting, not queued behind a
    lock the worker might fail to take. Progress state is set when the job launches
    (start_inbox_scan)."""
    return write_lock.try_acquire_for_scan()


def abort_inbox_scan(message: str = "error: failed to start") -> None:
    """Release the write lock and drop the scan job after prepare_inbox_scan()
    succeeded but launching the worker failed — otherwise the lock stays held and
    a phantom running job lingers in the registry."""
    runner.reset(_SCAN_KEY)
    write_lock.release_scan()


def start_inbox_scan(path: str, single_pack: bool = False, creator_name: str | None = None) -> bool:
    """Launch an inbox import off the request path. Acquires the write lock
    synchronously (authoritative 200) then runs the work on the shared runner.
    Returns False if the library is busy. Used by both /scan/inbox and
    /import/scan-folder (single_pack=True, #1087 — see _inbox_scan).

    ``creator_name`` (#1110): only consulted when single_pack=True — see
    _inbox_scan."""
    if not prepare_inbox_scan():
        return False
    try:
        runner.start(
            _SCAN_KEY, _inbox_scan, single_flight=False,
            path=path, single_pack=single_pack, creator_name=creator_name,
        )
    except Exception:
        abort_inbox_scan()
        raise
    return True


def scan_inbox_folder(
    path: str, db: Session | None = None, _lock_already_held: bool = False,
    single_pack: bool = False, creator_name: str | None = None,
) -> None:
    """Index an arbitrary folder as inbox models without adding it as a scan root.
    Synchronous — direct callers (tests) run it inline against a caller-owned
    session; routers use start_inbox_scan(). Acquires the write lock unless the
    caller already holds it (_lock_already_held).

    ``single_pack`` (#1087): the caller already knows `path` is one product's
    own folder (Import Preview scopes each pack's Import button to exactly the
    folder it grouped as one pack) — see _inbox_scan for why that changes the
    indexing strategy.

    ``creator_name`` (#1110): the caller's already-known real creator name
    (e.g. Import Preview's Creator field, typed or Fetch-populated before the
    user clicks Import) — only consulted when single_pack=True."""
    if not _lock_already_held:
        if not write_lock.try_acquire_for_scan():
            logger.warning("Inbox scan skipped: library write lock is held")
            return
    runner.run_inline(
        _SCAN_KEY, _inbox_scan, path=path, db=db,
        single_pack=single_pack, creator_name=creator_name,
    )


def _auto_link_sups_for_creator(db: Session, creator_id: int) -> None:
    """Auto-pair "-sup"/"supported"-named STL files with their base part on
    every model just created for this creator (#1087 follow-up).

    A pack with format-variant SUBFOLDERS ("Product (supported)" /
    "Product (unsupported)") already gets split into separate variant
    models by _walk_for_models — each holds only one variant, nothing to
    link. A pack that instead distinguishes supported/unsupported by
    FILENAME SUFFIX with no subfolders (e.g. "warrior-1.stl" /
    "warrior-1-sup.stl") has no folder signal to split on, so both land as
    plain files on the same model — reuse the same pure-heuristic matching
    the manual "AI Organize > Link sups" action offers, applied
    automatically rather than left for the user to trigger by hand."""
    models = db.query(Model).filter(Model.creator_id == creator_id).all()
    for m in models:
        if not m.stl_files:
            continue
        file_dicts = [
            {"id": f.id, "filename": f.filename, "part_name": f.part_name,
             "sup_of_id": f.sup_of_id}
            for f in m.stl_files
        ]
        suggestions = ai_organize.heuristic_link_sups(file_dicts)
        if not suggestions:
            continue
        by_filename = {f.filename: f.id for f in m.stl_files}
        by_id = {f.id: f for f in m.stl_files}
        for s in suggestions:
            base_filename = s.get("sup_base_filename")
            base_id = base_filename and by_filename.get(base_filename)
            file_id = s.get("id")
            if not base_id or base_id == file_id or file_id not in by_id:
                continue
            by_id[file_id].sup_of_id = base_id


def _inbox_scan(
    job: JobHandle, path: str, db: Session | None = None, single_pack: bool = False,
    creator_name: str | None = None,
) -> None:
    """Inbox-import worker. All indexed models get is_inbox=True. Assumes the
    write lock is held; releases it.

    Two indexing strategies, chosen by the caller (``single_pack``) rather than
    guessed from folder shape — the two callers have genuinely different correct
    answers, not just different confidence in the same answer:

    * Approach B (single_pack=False, the default — Quick import of a whole dump
      folder via /scan/inbox): each immediate subdirectory with STL files is its
      own creator-level boundary, mirroring a scan root's creator walk. Right
      when the folder holds several different creators' content side by side.
      A flat layout (STLs directly in the root) uses a single '_Inbox' creator.

    * single_pack=True (Import Preview's per-pack Import button, via
      /import/scan-folder — #1087): the caller has already established `path`
      is ONE pack — by construction, a pack is one product's content, never
      several creators' worth. Treating each immediate subfolder as its own
      creator was always wrong here: a folder shaped like
      "Product (supported)" / "Product (unsupported)" / "Product (chitubox)"
      — an extremely common print-ready-format convention — split into
      multiple made-up creators instead of one product with format variants,
      and silently orphaned any pack-level Fetch metadata/gallery images
      (which live at the pack root, one level above where those bogus
      creators' models ended up). Fixed by treating the whole pack folder as
      one creator and delegating straight to _walk_for_models — the same
      product/variant detection a real scan root's creator folder already
      gets, which already knows how to keep genuinely distinct products
      separate while grouping format variants of one product together.
      Auto-grouping runs afterward (regular scans get this for free via
      _scan_root; Approach B never needed it since each of its creators
      typically holds one model, but a single-pack creator routinely holds
      several variants of one thing).

      That one creator resolves to ``creator_name`` (case-insensitive
      get-or-create, #1110) when the caller already knows it — Import
      Preview's Creator field is typically already filled in (typed, or via
      a metadata Fetch) before the user clicks Import, so there's no need to
      invent a placeholder only to have bulk-enrich immediately reassign
      every model away from it. Blank/not-yet-known instead reuses the same
      shared '_Inbox' placeholder the flat-layout branch below already uses
      (#1110 follow-up) — one common, well-known bucket for "not yet
      triaged" content instead of a fresh one-off creator named after every
      individual un-enriched pack's own folder."""
    global _active
    _active = job
    job.update(message="importing", models_found=0, files_found=0, cancelled=False,
               read_failures=0, read_failure_samples=[])
    try:
        own_db = db is None
        _db = db or SessionLocal()
        try:
            inbox = Path(path)
            rules = ScanRules.load(_db)

            walk_failures: list[ReadFailure] = []
            if single_pack:
                known_name = (creator_name or "").strip()
                creator = resolve_creator(known_name if known_name else "_Inbox", _db)
                _db.commit()
                _msg(f"importing {inbox.name}")
                _walk_for_models(
                    folder=inbox,
                    creator=creator,
                    db=_db,
                    creator_boundary=inbox,
                    character=None,
                    stl_cache={},
                    last_scanned=None,
                    rules=rules,
                    is_inbox=True,
                    read_failures=walk_failures,
                    # `inbox` is already scoped to one product (the caller knows
                    # this whole folder tree is a single pack, #1087) — its
                    # format-variant siblings must still share the pack-root
                    # images, so the gallery boundary must not be narrowed
                    # further the way a real multi-product creator folder is
                    # (STUDIO-377).
                    boundary_is_product=True,
                )
                if not _cancelled():
                    _auto_link_sups_for_creator(_db, creator.id)
                    grouping.regroup_creator(_db, creator.id)
                    grouping.prune_empty_groups(_db)
                    _db.commit()
                    # A full scan-root run self-heals via _prune_stale_paths;
                    # this single-pack path never did, so a model whose folder
                    # got renamed/restructured/deleted out from under it (e.g.
                    # re-flattening a pack after a prior scoped import) lingers
                    # as is_inbox=True forever — Import Preview keeps grouping
                    # it into the pack card (wrong file counts, a permanent
                    # "already imported" flag) no matter what's actually on
                    # disk now, since nothing else ever re-scans this exact
                    # boundary to notice. Skip when this run had read failures
                    # (STUDIO-79) — a transient listing error must not look
                    # like a deleted folder.
                    if not walk_failures:
                        _prune_stale_paths(_db, [str(inbox)] if inbox.exists() else [])
                        _db.commit()
            elif _has_stls(inbox, recurse=False):
                # Flat layout: inbox root itself is the model (STLs directly inside)
                creator = resolve_creator("_Inbox", _db)
                _db.commit()
                _msg("importing _Inbox")
                _index_model(
                    folder=inbox,
                    creator=creator,
                    db=_db,
                    creator_boundary=None,
                    character=None,
                    stl_cache={},
                    is_inbox=True,
                    parser_rules=rules.parser_rules,
                )
            else:
                # Creator-structure layout: each immediate subdir with STLs is a creator
                child_dirs = [d for d in sorted(inbox.iterdir()) if d.is_dir() and not _is_hidden(d.name)]
                creator_ids: dict[str, int] = {}
                for child in child_dirs:
                    if _has_stls(child, recurse=True):
                        creator = _get_or_create_creator(child.name, _db)
                        creator_ids[str(child)] = creator.id
                _db.commit()

                for child in child_dirs:
                    if _cancelled():
                        job.update(state=JobState.CANCELLED, message="cancelled", cancelled=True)
                        break
                    if str(child) not in creator_ids:
                        continue
                    _msg(f"importing {child.name}")
                    creator = _db.get(Creator, creator_ids[str(child)])
                    _walk_for_models(
                        folder=child,
                        creator=creator,
                        db=_db,
                        creator_boundary=child,
                        character=None,
                        stl_cache={},
                        last_scanned=None,
                        rules=rules,
                        is_inbox=True,
                        read_failures=walk_failures,
                    )

            _report_read_failures(walk_failures)

            if not _cancelled():
                # This prune is library-wide, not scoped to the imported folder, so
                # an incomplete listing here could remove models the import never
                # touched. Skip it rather than delete on a partial view of disk.
                if walk_failures:
                    logger.warning(
                        f"Inbox import hit {len(walk_failures)} unreadable entries — "
                        "phantom prune skipped to avoid removing live models"
                    )
                else:
                    _prune_phantoms(_db)
                prog = job.payload()["progress"]
                job.update(
                    state=JobState.DONE,
                    message=(
                        f"done — {prog.get('models_found', 0)} models, "
                        f"{prog.get('files_found', 0)} files"
                    ),
                )
        finally:
            if own_db:
                _db.close()
    except Exception as e:
        logger.exception(f"Inbox scan failed: {e}")
        job.update(state=JobState.ERROR, message=f"error: {e}", error=str(e))
    finally:
        write_lock.release_scan()
        _active = None

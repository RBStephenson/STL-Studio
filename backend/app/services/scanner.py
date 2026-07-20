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
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

from sqlalchemy import text as _sqltext, func, or_

from app.database import SessionLocal
from app.models import Creator, Model, STLFile, ScanRoot, ModelTag, CollectionModel, PackOverride
from app.services.job_runner import JobHandle, JobState, runner
from app.services import name_parser, layout, grouping
from app.services.scan_rules import (
    IgnoreMatcher, load_ignore_matcher, load_tag_rules, load_parts_names,
)
from app.services.tag_sync import sync_model_tags
from app.services import write_lock
from app.services import ai_organize
from app.services.ai_organize import clean_name
from app.utils import utcnow

logger = logging.getLogger(__name__)

STL_EXTENSIONS = {".stl", ".3mf", ".obj"}
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
# Folders the user has explicitly split into per-child models (see PackOverride).
# Loaded from the DB at the start of every scan; the walk treats these as
# boundaries. Module-level because only one scan runs at a time (held by the
# library write lock) and threading it through every recursive call would be noisy.
_pack_overrides: set[str] = set()
# Configurable folder/file ignore patterns (#31). Loaded from app_settings at the
# start of every scan; the walk skips any folder it matches. Module-level for the
# same reason as the overrides above — one scan at a time, threading it through
# every recursive call would be noise.
_ignore_matcher: IgnoreMatcher = IgnoreMatcher(())


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


def _load_pack_overrides(db: Session) -> None:
    global _pack_overrides
    _pack_overrides = {row[0] for row in db.query(PackOverride.path)}


def _load_scan_rules(db: Session) -> None:
    global _ignore_matcher
    _ignore_matcher = load_ignore_matcher(db)
    # Push user tag-inference rules + parts/structural names into the name
    # parser for this run (#31).
    name_parser.set_tag_rules([(r.pattern, r.tag) for r in load_tag_rules(db)])
    name_parser.set_parts_names(load_parts_names(db))


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
    job.update(message="starting", models_found=0, files_found=0, cancelled=False, offline_roots=[])
    try:
        _db = db or SessionLocal()
        own_db = db is None
        try:
            _load_pack_overrides(_db)
            _load_scan_rules(_db)

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
                failed_creator_ids |= _scan_root(root, _db)
                root.last_scanned = utcnow()
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
                removed += _prune_stale_paths(_db, available_paths)
                _prune_stale_stl_files(
                    _db, available_paths, protected_creator_ids=failed_creator_ids,
                )
                # Drop models that a newly-added ignore pattern now covers (#31).
                removed += _prune_ignored(_db, available_paths)
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


def _prune_stale_paths(db: Session, available_root_paths: list[str]):
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

    Returns the number of models pruned (for the scan completion summary, #223).
    """
    if not available_root_paths:
        return 0
    roots_norm = [os.path.normcase(os.path.normpath(p)) for p in available_root_paths]

    def _under_online_root(folder_path: str | None) -> bool:
        if not folder_path:
            return False
        n = os.path.normcase(os.path.normpath(folder_path))
        return any(n == r or n.startswith(r + os.sep) for r in roots_norm)

    rows = db.query(Model.id, Model.folder_path).filter(Model.folder_path != None).all()  # noqa: E711
    under = [r for r in rows if _under_online_root(r.folder_path)]
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
    if not available_root_paths:
        return 0
    protected = protected_creator_ids or set()
    roots_norm = [os.path.normcase(os.path.normpath(p)) for p in available_root_paths]

    def _under_online_root(folder_path: str | None) -> bool:
        if not folder_path:
            return False
        n = os.path.normcase(os.path.normpath(folder_path))
        return any(n == r or n.startswith(r + os.sep) for r in roots_norm)

    models = (
        db.query(Model.id, Model.folder_path, Model.creator_id)
        .filter(Model.folder_path != None)  # noqa: E711
        .all()
    )
    model_ids = [
        m.id for m in models
        if m.creator_id not in protected
        and _under_online_root(m.folder_path)
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


def _prune_ignored(db: Session, root_paths: list[str]):
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
    if not _ignore_matcher.patterns or not root_paths:
        return 0
    roots_norm = {os.path.normcase(os.path.normpath(p)) for p in root_paths}

    def _is_ignored(folder_path: str | None) -> bool:
        if not folder_path:
            return False
        current = Path(folder_path)
        # Walk leaf → up, stopping when we step onto a scan root (don't test the
        # root itself — ignoring a whole root is not this feature's job) or run
        # out of parents.
        while True:
            if os.path.normcase(os.path.normpath(str(current))) in roots_norm:
                return False
            if _ignore_matcher.matches(current):
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

    Root membership is matched on the normalised path with a separator boundary
    (not a SQL LIKE prefix): folder paths and root names routinely contain '_' and
    other LIKE metacharacters, and an unanchored prefix would also match sibling
    roots ('D:/STL' vs 'D:/STLBackup'). os.path.normcase handles per-platform
    separator + case folding (case-insensitive on Windows).

    User-EXCLUDED models are never pruned: the walk returns before bumping their
    updated_at (so it always predates scan_start), and deleting them would let a
    later scan resurrect the folder as a brand-new, non-excluded model.

    Models under a creator whose walk FAILED this run (protected_creator_ids) are
    also never pruned: their folders were only partially re-indexed, so a stale
    updated_at reflects a transient error (SQLite lock, mount hiccup), not a deleted
    folder — pruning them would silently wipe live data (STUDIO-79).

    Returns the number of models pruned (for the scan completion summary, #223).
    """
    if not root_paths:
        return 0
    roots_norm = [os.path.normcase(os.path.normpath(p)) for p in root_paths]
    protected = protected_creator_ids or set()

    def _under_root(folder_path: str | None) -> bool:
        if not folder_path:
            return False
        n = os.path.normcase(os.path.normpath(folder_path))
        return any(n == r or n.startswith(r + os.sep) for r in roots_norm)

    # Fetch non-excluded candidates once (id + folder + timestamp + creator), then
    # derive both the under-root total and the stale subset in Python. Root
    # membership still needs normpath comparison (see docstring re: LIKE
    # metacharacters), so it can't move to SQL — but a single pass replaces the two
    # overlapping full-table queries this ran before (#653).
    rows = (
        db.query(Model.id, Model.folder_path, Model.updated_at, Model.creator_id)
        .filter(Model.excluded == False, Model.folder_path != None)  # noqa: E711, E712
        .all()
    )
    under = [
        r for r in rows
        if _under_root(r.folder_path) and r.creator_id not in protected
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
    """Delete Creator rows that have no models — left behind by the scraper
    creating duplicate creators with different casing, by stale-path pruning,
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
    job.update(message="starting", models_found=0, files_found=0, cancelled=False)
    try:
        db = SessionLocal()
        try:
            creator = db.get(Creator, creator_id)
            if not creator:
                job.update(state=JobState.DONE, message="creator not found")
                return

            _load_pack_overrides(db)
            _load_scan_rules(db)

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
                    layout_tags=layout_tags,
                    group_by_character=grp_by_char,
                )

            if not _cancelled():
                removed = _prune_phantoms(db, creator_id=creator_id)
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

            # Record the durable override (idempotent) and refresh the in-memory set.
            if not db.query(PackOverride).filter(PackOverride.path == str(pack)).first():
                db.add(PackOverride(path=str(pack)))
                db.commit()
            _load_pack_overrides(db)

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
            for r in db.query(ScanRoot).filter(ScanRoot.enabled == True).all():
                try:
                    pack.relative_to(Path(r.path))
                except ValueError:
                    continue
                pack_layout_tags = layout.tags_for_path(pack, Path(r.path), layout.roles_for(r.layout))
                break

            before = db.query(func.count(Model.id)).filter(Model.creator_id == creator_id).scalar() or 0
            _walk_for_models(
                folder=pack,
                creator=creator,
                db=db,
                creator_boundary=pack,
                character=None,
                stl_cache={},
                last_scanned=None,
                layout_tags=pack_layout_tags,
            )
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


def _scan_root(root: ScanRoot, db: Session) -> set[int]:
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

    def _scan_one(creator_dir: Path, layout_tags: list[str]):
        if _cancelled():
            return
        creator_id = creator_ids[str(creator_dir)]
        thread_db = SessionLocal()
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
                layout_tags=layout_tags,
                group_by_character=root.group_by_character,
            )
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
    parent_names: list[str] | None = None,
    layout_tags: list[str] | None = None,
    is_inbox: bool = False,
    group_by_character: bool = False,
):
    if not folder.is_dir():
        return

    # User-configured ignore patterns (#31): skip this folder and its entire
    # subtree. Checked before any classification so an ignored folder costs nothing.
    # The creator boundary itself is never ignored — a pattern that happened to match
    # a creator folder would silently drop every model under it; ignore is for
    # sub-folders (WIP dumps, archives, slicer project dirs), not whole creators.
    if folder != creator_boundary and _ignore_matcher.matches(folder):
        return

    # The creator-boundary folder is never itself a model. Its name may contain a
    # type keyword (e.g. "Tanuki Figures" -> "figure", "LA Figures", "X Miniatures")
    # which would otherwise trip product detection and short-circuit the whole
    # creator into a single model. Always recurse past it into the character folders.
    #
    # A folder the user has explicitly split (a pack override) is treated the same
    # way: never a model itself, always recursed past, so each child becomes its own
    # model. This is what makes an opt-in split durable across rescans.
    is_creator_root = folder == creator_boundary or str(folder) in _pack_overrides

    child_dirs = [d for d in sorted(folder.iterdir()) if d.is_dir() and not _is_hidden(d.name)]
    has_direct_stls = _has_stls(folder, recurse=False)
    any_child_stls = _any_child_has_stls_cached(child_dirs, stl_cache)
    has_any_stls = has_direct_stls or any_child_stls

    # Collect file names for signal detection. iterdir()/is_file() only raise
    # OSError (permissions, vanished mount) — narrow so a real bug isn't masked as
    # an empty folder.
    try:
        filenames = [f.name for f in folder.iterdir() if f.is_file()]
    except OSError:
        filenames = []

    # --- Step 1: name-based product detection (folder + files + parents) ---
    # Require the subtree to actually contain STLs. A folder whose *name* (or whose
    # image filenames, e.g. "Auron_bust_75mm.png") trips a scale/type signal but
    # holds no printable files — render/preview folders — must never be a model.
    signals = name_parser.parse_folder(
        str(folder),
        filenames=filenames,
        parent_names=parent_names,
    )
    product_boundary_split = False
    if not is_creator_root and signals.is_product and has_any_stls:
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
            )
            if child_signals.is_product or _is_nested_variant_boundary(child.name):
                boundary_children.append(child)

        if not boundary_children:
            _index_model(folder, creator, db, creator_boundary, character,
                         stl_cache, auto_signals=signals, last_scanned=last_scanned,
                         layout_tags=layout_tags, is_inbox=is_inbox)
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
            )

        # Only recurse into the independently qualifying boundaries. Other
        # descendants remain part of the parent model indexed above.
        child_dirs = boundary_children
        product_boundary_split = True

    # --- Step 2: has STLs + children look like parts ---
    if not product_boundary_split and not is_creator_root and has_any_stls:
        child_names = [d.name for d in child_dirs]
        if has_direct_stls and name_parser.children_look_like_parts(child_names):
            _index_model(folder, creator, db, creator_boundary, character,
                         stl_cache, auto_signals=signals, last_scanned=last_scanned,
                         layout_tags=layout_tags, is_inbox=is_inbox)
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
                     layout_tags=layout_tags, is_inbox=is_inbox)
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
        if (name_parser.parse(c.name).is_parts
                or name_parser.is_structural_folder(c.name)
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
            and not name_parser.is_structural_folder(folder.name)
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
                         layout_tags=layout_tags, is_inbox=is_inbox,
                         group_by_character=group_by_character)


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
        # a differently-cased path is a genuinely different folder. The SQL
        # lower()-match keeps this to a single narrow query per new model instead
        # of scanning every model for the creator; the _normpath guard on the
        # result rejects any ASCII-lower() false positive.
        recased_from: str | None = None
        if model is None and _normpath("A") == _normpath("a"):
            target_norm = _normpath(folder_path)
            candidates = (
                db.query(Model)
                .filter(Model.creator_id == creator.id,
                        func.lower(Model.folder_path) == folder_path.lower())
                .all()
            )
            for candidate in candidates:
                if candidate.folder_path and _normpath(candidate.folder_path) == target_norm:
                    model = candidate
                    recased_from = candidate.folder_path
                    break

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
            and folder.stat().st_mtime < last_scanned.timestamp()
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
        if (name_parser.is_structural_folder(folder.name)
                or _is_nested_variant_boundary(folder.name)):
            product = None
            top_level = None          # last ancestor before the creator boundary
            for anc in folder.parents:
                if anc == creator_boundary or anc == anc.parent:
                    break
                if name_parser.is_container_folder(anc.name):
                    continue
                top_level = anc.name
                if not name_parser.is_structural_folder(anc.name):
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
        if name_parser.is_generic_name(clean_name):
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
        elif model.name in (folder.name, clean_name) or name_parser.is_structural_folder(model.name):
            # Name still matches what the scanner would generate (raw or current
            # derivation), OR is a stale structural token (e.g. "LYS"/"STL") that
            # the scanner would never intentionally assign as a final name — in
            # both cases the user hasn't really renamed it, so let parser
            # improvements refresh it (e.g. once STUDIO-281 made "lys" structural,
            # the #641 leaf-naming now resolves it to the character). A genuine
            # user-edited (non-structural) name is still left untouched. (STUDIO-282)
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
            try:
                gallery_images = _collect_gallery_images(
                    folder,
                    boundary=creator_boundary or folder,
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
                    boundary=creator_boundary or folder,
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
    """Normalize a filesystem path for identity comparison — case- and
    separator-folded on the current platform (case-insensitive on Windows).
    Mirrors the normalization the prune paths already use so lookup and prune
    agree on model identity (STUDIO-78)."""
    return os.path.normcase(os.path.normpath(p))


def _recase_model_paths(db: Session, model: Model, old_folder_path: str, new_folder_path: str):
    """Adopt a case-only folder rename on an existing model in place (STUDIO-78).

    Updates the model's folder_path and re-cases the prefix of every child
    STLFile.path so they line up with the new-cased folder on disk. The relative
    suffix under the model folder is unchanged (only an ancestor's case differs),
    so a straight prefix swap is exact and preserves STL-level metadata
    (sup_of_id, part_name) that a delete-and-reindex would drop."""
    model.folder_path = new_folder_path
    for stl in db.query(STLFile).filter(STLFile.model_id == model.id).all():
        if stl.path and stl.path.startswith(old_folder_path):
            stl.path = new_folder_path + stl.path[len(old_folder_path):]


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

    boundary = creator_boundary or folder
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


def _find_thumbnail(model: Model, leaf: Path, boundary: Path,
                    stl_cache: dict[str, bool] | None = None):
    """
    Walk upward from leaf to creator boundary looking for an image.

    Priority at each level:
      1. PREFERRED-named subdirs (renders, images, …) — rglob for nested layouts
      2. Direct image files in the folder itself
      3. Any other subdir that doesn't contain STLs (i.e. not a model folder)
    """
    PREFERRED = {
        "renders", "render", "images", "image", "photos", "photo",
        "preview", "previews", "pics", "pictures", "gallery",
    }

    def _has_stls_cached(d: Path) -> bool:
        key = str(d)
        if stl_cache is not None:
            if key not in stl_cache:
                stl_cache[key] = _has_stls(d, recurse=True)
            return stl_cache[key]
        return _has_stls(d, recurse=True)

    def first_image(folder: Path) -> Path | None:
        try:
            children = list(folder.iterdir())
        except PermissionError:
            return None
        subdirs = [c for c in children if c.is_dir() and not _is_hidden(c.name)]

        # 1. PREFERRED subdirs first — rglob to handle nested layouts (e.g. Renders/Color/)
        for sub in sorted(subdirs):
            if sub.name.lower() in PREFERRED:
                for img in sorted(sub.rglob("*")):
                    if img.is_file() and img.suffix.lower() in IMAGE_EXTENSIONS and not _has_hidden_ancestor(img, sub):
                        return img

        # 2. Direct image files at this level
        for f in sorted(children):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                return f

        # 3. Any other subdir that isn't a model folder (no STLs inside)
        for sub in sorted(subdirs):
            if sub.name.lower() not in PREFERRED and not _has_stls_cached(sub):
                for img in sorted(sub.rglob("*")):
                    if img.is_file() and img.suffix.lower() in IMAGE_EXTENSIONS and not _has_hidden_ancestor(img, sub):
                        return img

        return None

    current = leaf
    while True:
        found = first_image(current)
        if found:
            model.thumbnail_path = str(found)
            return
        if current == boundary or current.parent == current:
            break
        current = current.parent


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
    creator = db.query(Creator).filter(Creator.name == name).first()
    if not creator:
        creator = Creator(name=name)
        db.add(creator)
        db.flush()
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
    job.update(message="importing", models_found=0, files_found=0, cancelled=False)
    try:
        own_db = db is None
        _db = db or SessionLocal()
        try:
            inbox = Path(path)
            _load_pack_overrides(_db)
            _load_scan_rules(_db)

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
                    is_inbox=True,
                )
                if not _cancelled():
                    _auto_link_sups_for_creator(_db, creator.id)
                    grouping.regroup_creator(_db, creator.id)
                    grouping.prune_empty_groups(_db)
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
                        is_inbox=True,
                    )

            if not _cancelled():
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

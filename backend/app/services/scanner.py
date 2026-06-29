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
  1. Folder name contains scale/type/modifier signals (product boundary)
  2. Folder contains STLs and all child dirs look like parts sub-folders
  3. Folder contains STLs and has no children with STLs (deepest fallback)

Auto-tags are generated from detected scale, type, and modifier tokens.
needs_review=True is set when confidence is low.
"""
import logging
import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

from sqlalchemy import text as _sqltext, func, or_

from app.database import SessionLocal
from app.models import Creator, Model, STLFile, ScanRoot, ModelTag, CollectionModel, PackOverride, GroupOverride
from app.services import name_parser, layout, grouping
from app.services.scan_rules import (
    IgnoreMatcher, load_ignore_matcher, load_tag_rules, load_parts_names,
)
from app.services.tag_sync import sync_model_tags
from app.services import write_lock
from app.utils import utcnow

logger = logging.getLogger(__name__)

STL_EXTENSIONS = {".stl", ".3mf", ".obj"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
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

# The "one scan at a time" gate is now the app-wide library write lock
# (services/write_lock.py), so a scan and a reorganize apply/undo are mutually
# exclusive — a scan must not prune/insert rows under a move in flight (#324).
_state_lock = threading.Lock()
# Serializes DB-mutating work across the parallel creator workers. SQLite allows
# only one writer; without this, workers holding an open write transaction during
# slow rglob I/O block each other past busy_timeout -> "database is locked", which
# aborts a creator's walk and silently drops its models.
_db_lock = threading.Lock()
_scan_state: dict = {"running": False, "message": "idle", "models_found": 0, "files_found": 0, "cancelled": False, "offline_roots": []}
_cancel_requested = False
# Folders the user has explicitly split into per-child models (see PackOverride).
# Loaded from the DB at the start of every scan; the walk treats these as
# boundaries. Module-level because only one scan runs at a time (held by the
# library write lock) and threading it through every recursive call would be noisy.
_pack_overrides: set[str] = set()
# User-assigned character groupings keyed by model folder_path (see GroupOverride).
# None value = explicitly ungrouped. Applied in _index_model instead of the heuristic.
_group_overrides: dict[str, str | None] = {}
# Configurable folder/file ignore patterns (#31). Loaded from app_settings at the
# start of every scan; the walk skips any folder it matches. Module-level for the
# same reason as the overrides above — one scan at a time, threading it through
# every recursive call would be noise.
_ignore_matcher: IgnoreMatcher = IgnoreMatcher(())


def get_status() -> dict:
    with _state_lock:
        return dict(_scan_state)


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


def _load_group_overrides(db: Session) -> None:
    global _group_overrides
    _group_overrides = {row[0]: row[1] for row in db.query(GroupOverride.path, GroupOverride.character)}


def _load_scan_rules(db: Session) -> None:
    global _ignore_matcher
    _ignore_matcher = load_ignore_matcher(db)
    # Push user tag-inference rules + parts/structural names into the name
    # parser for this run (#31).
    name_parser.set_tag_rules([(r.pattern, r.tag) for r in load_tag_rules(db)])
    name_parser.set_parts_names(load_parts_names(db))


def request_cancel():
    global _cancel_requested
    _cancel_requested = True


def scan_all_roots(db: Session | None = None):
    global _cancel_requested
    if not write_lock.try_acquire_for_scan():
        return
    _cancel_requested = False
    with _state_lock:
        _scan_state.update(running=True, message="starting", models_found=0, files_found=0, cancelled=False, offline_roots=[])
    try:
        _db = db or SessionLocal()
        own_db = db is None
        try:
            _load_pack_overrides(_db)
            _load_group_overrides(_db)
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
            for root in roots:
                if _cancel_requested:
                    with _state_lock:
                        _scan_state["message"] = "cancelled"
                        _scan_state["cancelled"] = True
                    break
                _scan_root(root, _db)
                root.last_scanned = utcnow()
                _db.commit()

            if not _cancel_requested:
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
                    with _state_lock:
                        _scan_state["offline_roots"] = list(offline_paths)

                removed = _prune_stale_models(_db, scan_start, available_paths)
                removed += _prune_stale_paths(_db, available_paths)
                # Drop models that a newly-added ignore pattern now covers (#31).
                removed += _prune_ignored(_db, available_paths)
                # Slicer rows must go before the phantom prune so a model whose
                # only "STL" was a slicer project is removed in the same scan.
                _prune_slicer_files(_db)
                removed += _prune_phantoms(_db)
                _prune_empty_creators(_db)

                # Replace the in-progress "scanning <creator>" message with a
                # summary the UI can show once the run finishes (#223).
                with _state_lock:
                    summary = (
                        f"done — {_scan_state['models_found']} models, "
                        f"{_scan_state['files_found']} files"
                    )
                    if removed:
                        summary += f", {removed} removed"
                    _scan_state["message"] = summary
        finally:
            if own_db:
                _db.close()
    except Exception as e:
        logger.exception(f"Scan failed: {e}")
        with _state_lock:
            _scan_state["message"] = f"error: {e}"
    finally:
        with _state_lock:
            _scan_state["running"] = False
        write_lock.release_scan()


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


def _prune_stale_models(db: Session, scan_start: datetime, root_paths: list[str]):
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

    Returns the number of models pruned (for the scan completion summary, #223).
    """
    if not root_paths:
        return 0
    roots_norm = [os.path.normcase(os.path.normpath(p)) for p in root_paths]

    def _under_root(folder_path: str | None) -> bool:
        if not folder_path:
            return False
        n = os.path.normcase(os.path.normpath(folder_path))
        return any(n == r or n.startswith(r + os.sep) for r in roots_norm)

    # Load only non-excluded candidates with a stale timestamp — the common case
    # (most models visited this scan) fetches nothing. Root membership still
    # requires Python-side normpath comparison (see docstring re: LIKE metacharacters).
    all_under_rows = (
        db.query(Model.id, Model.folder_path)
        .filter(Model.excluded == False, Model.folder_path != None)  # noqa: E711, E712
        .all()
    )
    under_all = [r for r in all_under_rows if _under_root(r.folder_path)]
    total = len(under_all)

    stale_rows = (
        db.query(Model.id, Model.folder_path)
        .filter(
            Model.excluded == False,  # noqa: E712
            Model.folder_path != None,  # noqa: E711
            Model.updated_at != None,  # noqa: E711
            Model.updated_at < scan_start,
        )
        .all()
    )
    stale_ids = [r.id for r in stale_rows if _under_root(r.folder_path)]
    if not stale_ids:
        return 0
    if _exceeds_prune_cap(len(stale_ids), total, "not visited this run"):
        return 0

    _cascade_delete_models(db, stale_ids)
    logger.info(f"Post-scan: pruned {len(stale_ids)} stale models (not visited this run)")
    return len(stale_ids)


def _prune_empty_creators(db: Session):
    """Delete Creator rows that have no models — left behind by the scraper
    creating duplicate creators with different casing, or by stale-path pruning."""
    orphans = (
        db.query(Creator)
        .filter(~Creator.id.in_(db.query(Model.creator_id).filter(Model.creator_id != None).distinct()))
        .all()
    )
    if orphans:
        for c in orphans:
            db.delete(c)
        db.commit()
        logger.info(f"Post-scan: removed {len(orphans)} creator(s) with no remaining models")


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
    Runs single-threaded (one creator) and forces a full reindex so newly added
    or changed models under that creator are picked up."""
    global _cancel_requested
    if not write_lock.try_acquire_for_scan():
        return
    _cancel_requested = False
    with _state_lock:
        _scan_state.update(running=True, message="starting", models_found=0, files_found=0, cancelled=False)
    try:
        db = SessionLocal()
        try:
            creator = db.get(Creator, creator_id)
            if not creator:
                with _state_lock:
                    _scan_state["message"] = "creator not found"
                return

            _load_pack_overrides(db)
            _load_group_overrides(db)
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
                with _state_lock:
                    _scan_state["message"] = "no folders found for creator"
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
                if _cancel_requested:
                    with _state_lock:
                        _scan_state["message"] = "cancelled"
                        _scan_state["cancelled"] = True
                    break
                with _state_lock:
                    _scan_state["message"] = f"scanning {creator_dir.name}"
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

            if not _cancel_requested:
                removed = _prune_phantoms(db, creator_id=creator_id)
                with _state_lock:
                    summary = (
                        f"done — {_scan_state['models_found']} models, "
                        f"{_scan_state['files_found']} files"
                    )
                    if removed:
                        summary += f", {removed} removed"
                    _scan_state["message"] = summary
        finally:
            db.close()
    except Exception as e:
        logger.exception(f"Creator scan failed: {e}")
        with _state_lock:
            _scan_state["message"] = f"error: {e}"
    finally:
        with _state_lock:
            _scan_state["running"] = False
        write_lock.release_scan()


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
            if not any(_has_stls(d, recurse=True) for d in child_dirs):
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


def _scan_root(root: ScanRoot, db: Session):
    root_path = Path(root.path)
    if not root_path.exists():
        logger.warning(f"Scan root not found: {root.path}")
        with _state_lock:
            _scan_state["message"] = f"path not found: {root.path}"
        return

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

    def _scan_one(creator_dir: Path, layout_tags: list[str]):
        if _cancel_requested:
            return
        creator_id = creator_ids[str(creator_dir)]
        thread_db = SessionLocal()
        try:
            creator = thread_db.get(Creator, creator_id)
            with _state_lock:
                _scan_state["message"] = f"scanning {creator_dir.name}"
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
            logger.exception(f"Error scanning creator: {creator_dir.name}")
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

    child_dirs = [d for d in sorted(folder.iterdir()) if d.is_dir()]
    has_direct_stls = _has_stls(folder, recurse=False)
    any_child_stls = _any_child_has_stls_cached(child_dirs, stl_cache)
    has_any_stls = has_direct_stls or any_child_stls

    # Collect file names for signal detection
    try:
        filenames = [f.name for f in folder.iterdir() if f.is_file()]
    except Exception:
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
    if not is_creator_root and signals.is_product and has_any_stls:
        _index_model(folder, creator, db, creator_boundary, character,
                     stl_cache, auto_signals=signals, last_scanned=last_scanned,
                     layout_tags=layout_tags, is_inbox=is_inbox)
        return

    # --- Step 2: has STLs + children look like parts ---
    if not is_creator_root and has_any_stls:
        child_names = [d.name for d in child_dirs]
        if has_direct_stls and name_parser.children_look_like_parts(child_names):
            _index_model(folder, creator, db, creator_boundary, character,
                         stl_cache, auto_signals=signals, last_scanned=last_scanned,
                         layout_tags=layout_tags, is_inbox=is_inbox)
            return

        # --- Step 3: deepest fallback — STLs here, nothing below ---
        if has_direct_stls and not any_child_stls:
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
        if name_parser.parse(c.name).is_parts or name_parser.is_structural_folder(c.name):
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
):
    folder_path = str(folder)

    # Serialize all DB interaction for this model. SQLite has a single writer;
    # holding this lock across the read/query + writes + commit keeps the worker
    # threads from contending at the SQLite level (which otherwise surfaces as
    # "database is locked" and drops a creator's models).
    with _db_lock:
        model = db.query(Model).filter(Model.folder_path == folder_path).first()

        # User-excluded model: leave it hidden. Never re-index, re-tag, or reset
        # the flag, so a rescan never resurrects something the user removed.
        if model is not None and model.excluded:
            return

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
        # cards (#641). Name it after its product instead: the grouping character,
        # else the nearest non-structural ancestor folder.
        if name_parser.is_structural_folder(folder.name):
            product = character
            if not product:
                for anc in folder.parents:
                    if anc == creator_boundary or anc == anc.parent:
                        break
                    if not name_parser.is_structural_folder(anc.name):
                        product = anc.name
                        break
            if product:
                clean_name = name_parser.display_name(product, creator.name) or product

        is_new = model is None
        if is_new:
            model = Model(
                name=clean_name,
                folder_path=folder_path,
                creator_id=creator.id,
            )
            db.add(model)
            db.flush()
        elif model.name in (folder.name, clean_name):
            # Name still matches what the scanner would generate (raw or current
            # derivation) — the user hasn't renamed it, so let parser improvements
            # refresh it. A user-edited name is left untouched.
            model.name = clean_name

        # Scanner-owned structured variant attributes (support/cut/slicer/version).
        # Kept separate from user-set custom_attributes so a rescan never clobbers
        # user edits. Recomputed every scan so parser improvements propagate.
        model.parsed_attributes = name_parser.parsed_attributes(folder.name)

        # Character grouping — use the user's durable override when present;
        # otherwise always reflect the current walk (including None) so a model
        # whose path is all-structural clears any stale character.
        if folder_path in _group_overrides:
            model.character = _group_overrides[folder_path]
        else:
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
            # Thumbnail: walk upward if not already set
            if not model.thumbnail_path:
                _find_thumbnail(model, folder, boundary=creator_boundary or folder,
                                stl_cache=stl_cache)

            _index_stl_files(model, folder, db)

        if is_inbox:
            model.is_inbox = True

        model.updated_at = utcnow()
        sync_model_tags(model, db)
        db.commit()

    with _state_lock:
        _scan_state["models_found"] += 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _has_stls(folder: Path, recurse: bool = False) -> bool:
    if recurse:
        return any(f.suffix.lower() in STL_EXTENSIONS for f in folder.rglob("*") if f.is_file())
    return any(f.suffix.lower() in STL_EXTENSIONS for f in folder.iterdir() if f.is_file())


def _any_child_has_stls_cached(child_dirs: list[Path], cache: dict[str, bool]) -> bool:
    for d in child_dirs:
        key = str(d)
        if key not in cache:
            cache[key] = _has_stls(d, recurse=True)
        if cache[key]:
            return True
    return False


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
        subdirs = [c for c in children if c.is_dir()]

        # 1. PREFERRED subdirs first — rglob to handle nested layouts (e.g. Renders/Color/)
        for sub in sorted(subdirs):
            if sub.name.lower() in PREFERRED:
                for img in sorted(sub.rglob("*")):
                    if img.is_file() and img.suffix.lower() in IMAGE_EXTENSIONS:
                        return img

        # 2. Direct image files at this level
        for f in sorted(children):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                return f

        # 3. Any other subdir that isn't a model folder (no STLs inside)
        for sub in sorted(subdirs):
            if sub.name.lower() not in PREFERRED and not _has_stls_cached(sub):
                for img in sorted(sub.rglob("*")):
                    if img.is_file() and img.suffix.lower() in IMAGE_EXTENSIONS:
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


def _index_stl_files(model: Model, folder: Path, db: Session):
    # Gather candidate STL files under this folder.
    candidates = [
        stl for stl in sorted(folder.rglob("*"))
        if stl.is_file()
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
    existing: set[str] = set()
    for i in range(0, len(candidate_paths), 500):
        chunk = candidate_paths[i:i + 500]
        existing.update(
            row[0] for row in db.query(STLFile.path).filter(STLFile.path.in_(chunk))
        )

    for stl, path_str in zip(candidates, candidate_paths):
        if path_str in existing:
            continue
        db.add(STLFile(
            model_id=model.id,
            path=path_str,
            filename=stl.name,
            size_bytes=stl.stat().st_size,
        ))
        existing.add(path_str)  # prevent duplicates within the same session
        with _state_lock:
            _scan_state["files_found"] += 1


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
    """Synchronously acquire write lock and mark scan state running.

    Returns True if the lock was acquired and state set; False if the library is
    busy. Call this in the request thread before starting the inbox daemon thread
    so the HTTP response is authoritative: a 200 means the scan is actually
    starting, not just queued behind a lock the thread might fail to acquire.
    """
    global _cancel_requested
    if not write_lock.try_acquire_for_scan():
        return False
    _cancel_requested = False
    with _state_lock:
        _scan_state.update(running=True, message="importing", models_found=0, files_found=0, cancelled=False)
    return True


def abort_inbox_scan(message: str = "error: failed to start") -> None:
    """Release the write lock and clear running state after prepare_inbox_scan()
    succeeded but the worker thread failed to launch. Without this, a failed
    thread.start() would leave the lock held and state stuck at running."""
    with _state_lock:
        _scan_state["running"] = False
        _scan_state["message"] = message
    write_lock.release_scan()


def scan_inbox_folder(
    path: str, db: Session | None = None, _lock_already_held: bool = False
) -> None:
    """Index an arbitrary folder as inbox models without adding it as a scan root.

    Approach B: each immediate subdirectory that contains STL files is treated
    as a creator-level boundary (mirrors how a scan root walks creator folders).
    If the inbox root itself has direct STL files (flat layout), a single
    '_Inbox' creator is used instead. All indexed models get is_inbox=True.

    Runs synchronously — callers launch this in a daemon thread.
    Pass _lock_already_held=True when the caller has already acquired the write
    lock via prepare_inbox_scan() to avoid a double-acquire.
    """
    global _cancel_requested
    if not _lock_already_held:
        if not write_lock.try_acquire_for_scan():
            logger.warning("Inbox scan skipped: library write lock is held")
            return
        _cancel_requested = False
        with _state_lock:
            _scan_state.update(running=True, message="importing", models_found=0, files_found=0, cancelled=False)
    try:
        own_db = db is None
        _db = db or SessionLocal()
        try:
            inbox = Path(path)
            _load_pack_overrides(_db)
            _load_group_overrides(_db)
            _load_scan_rules(_db)

            if _has_stls(inbox, recurse=False):
                # Flat layout: inbox root itself is the model (STLs directly inside)
                creator = resolve_creator("_Inbox", _db)
                _db.commit()
                with _state_lock:
                    _scan_state["message"] = "importing _Inbox"
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
                child_dirs = [d for d in sorted(inbox.iterdir()) if d.is_dir()]
                creator_ids: dict[str, int] = {}
                for child in child_dirs:
                    if _has_stls(child, recurse=True):
                        creator = _get_or_create_creator(child.name, _db)
                        creator_ids[str(child)] = creator.id
                _db.commit()

                for child in child_dirs:
                    if _cancel_requested:
                        with _state_lock:
                            _scan_state["message"] = "cancelled"
                            _scan_state["cancelled"] = True
                        break
                    if str(child) not in creator_ids:
                        continue
                    with _state_lock:
                        _scan_state["message"] = f"importing {child.name}"
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

            if not _cancel_requested:
                _prune_phantoms(_db)
                with _state_lock:
                    _scan_state["message"] = (
                        f"done — {_scan_state['models_found']} models, "
                        f"{_scan_state['files_found']} files"
                    )
        finally:
            if own_db:
                _db.close()
    except Exception as e:
        logger.exception(f"Inbox scan failed: {e}")
        with _state_lock:
            _scan_state["message"] = f"error: {e}"
    finally:
        with _state_lock:
            _scan_state["running"] = False
        write_lock.release_scan()

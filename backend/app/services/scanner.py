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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

from sqlalchemy import text as _sqltext, func

from app.database import SessionLocal
from app.models import Creator, Model, STLFile, ScanRoot, ModelTag, CollectionModel, PackOverride
from app.services import name_parser
from app.services.tag_sync import sync_model_tags
from app.utils import utcnow

logger = logging.getLogger(__name__)

STL_EXTENSIONS = {".stl", ".3mf", ".obj"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

_scan_lock = threading.Lock()
_state_lock = threading.Lock()
# Serializes DB-mutating work across the parallel creator workers. SQLite allows
# only one writer; without this, workers holding an open write transaction during
# slow rglob I/O block each other past busy_timeout -> "database is locked", which
# aborts a creator's walk and silently drops its models.
_db_lock = threading.Lock()
_scan_state: dict = {"running": False, "message": "idle", "models_found": 0, "files_found": 0, "cancelled": False}
_cancel_requested = False
# Folders the user has explicitly split into per-child models (see PackOverride).
# Loaded from the DB at the start of every scan; the walk treats these as
# boundaries. Module-level because only one scan runs at a time (held by _scan_lock)
# and threading it through every recursive call would be noisy.
_pack_overrides: set[str] = set()


def get_status() -> dict:
    return dict(_scan_state)


def _load_pack_overrides(db: Session) -> None:
    global _pack_overrides
    _pack_overrides = {row[0] for row in db.query(PackOverride.path)}


def request_cancel():
    global _cancel_requested
    _cancel_requested = True


def scan_all_roots(db: Session | None = None):
    global _cancel_requested
    if not _scan_lock.acquire(blocking=False):
        return
    _cancel_requested = False
    _scan_state.update(running=True, message="starting", models_found=0, files_found=0, cancelled=False)
    try:
        _db = db or SessionLocal()
        own_db = db is None
        try:
            _load_pack_overrides(_db)

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

            roots = _db.query(ScanRoot).filter(ScanRoot.enabled == True).all()
            for root in roots:
                if _cancel_requested:
                    _scan_state["message"] = "cancelled"
                    _scan_state["cancelled"] = True
                    break
                _scan_root(root, _db)
                root.last_scanned = utcnow()
                _db.commit()

            if not _cancel_requested:
                _prune_stale_paths(_db)
                _prune_phantoms(_db)
                _prune_empty_creators(_db)
        finally:
            if own_db:
                _db.close()
    except Exception as e:
        logger.exception(f"Scan failed: {e}")
        _scan_state["message"] = f"error: {e}"
    finally:
        _scan_state["running"] = False
        _scan_lock.release()


def _prune_stale_paths(db: Session):
    """Remove models whose folder_path no longer exists on disk.

    This cleans up orphaned DB rows left behind after a creator folder is
    renamed (e.g. 'polyminds studios' → 'PolyMind Studios'). The scanner
    never visits the old path again, so the rows survive the phantom prune.
    After removal, orphaned Creator rows (no remaining models) are also deleted.
    """
    all_models = db.query(Model.id, Model.folder_path, Model.creator_id).all()
    stale_ids = [m.id for m in all_models if m.folder_path and not Path(m.folder_path).exists()]
    if not stale_ids:
        return

    for i in range(0, len(stale_ids), 500):
        chunk = stale_ids[i:i + 500]
        db.query(STLFile).filter(STLFile.model_id.in_(chunk)).delete(synchronize_session=False)
        db.query(ModelTag).filter(ModelTag.model_id.in_(chunk)).delete(synchronize_session=False)
        db.query(CollectionModel).filter(CollectionModel.model_id.in_(chunk)).delete(synchronize_session=False)
        db.query(Model).filter(Model.id.in_(chunk)).delete(synchronize_session=False)
    db.commit()
    logger.info(f"Post-scan: pruned {len(stale_ids)} models with missing folder paths")


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
        return
    if total and len(ids) > total * 0.5:
        logger.warning(
            f"Phantom prune skipped: {len(ids)}/{total} models have no STLs — "
            "that looks like an indexing failure, not phantoms."
        )
        return

    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        db.query(STLFile).filter(STLFile.model_id.in_(chunk)).delete(synchronize_session=False)
        db.query(ModelTag).filter(ModelTag.model_id.in_(chunk)).delete(synchronize_session=False)
        db.query(CollectionModel).filter(CollectionModel.model_id.in_(chunk)).delete(synchronize_session=False)
        db.query(Model).filter(Model.id.in_(chunk)).delete(synchronize_session=False)
    db.commit()
    logger.info(f"Post-scan: pruned {len(ids)} phantom models (no STL files)")


def _creator_dirs_for(creator: Creator, db: Session) -> list[Path]:
    """Resolve the on-disk top-level folder(s) for a creator from its indexed
    models — the path segment that sits directly under a scan root. A creator
    normally maps to one folder, but we handle several defensively."""
    roots = [Path(r.path) for r in db.query(ScanRoot).filter(ScanRoot.enabled == True).all()]
    boundaries: set[Path] = set()
    for (fp,) in db.query(Model.folder_path).filter(Model.creator_id == creator.id):
        if not fp:
            continue
        p = Path(fp)
        for root in roots:
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            if rel.parts:
                boundaries.add(root / rel.parts[0])
            break

    return [d for d in sorted(boundaries) if d.exists()]


def scan_creator(creator_id: int):
    """Rescan a single creator's folder(s) — a targeted alternative to a full scan.
    Runs single-threaded (one creator) and forces a full reindex so newly added
    or changed models under that creator are picked up."""
    global _cancel_requested
    if not _scan_lock.acquire(blocking=False):
        return
    _cancel_requested = False
    _scan_state.update(running=True, message="starting", models_found=0, files_found=0, cancelled=False)
    try:
        db = SessionLocal()
        try:
            creator = db.get(Creator, creator_id)
            if not creator:
                _scan_state["message"] = "creator not found"
                return

            _load_pack_overrides(db)

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

            for creator_dir in dirs:
                if _cancel_requested:
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
                )

            if not _cancel_requested:
                _prune_phantoms(db, creator_id=creator_id)
        finally:
            db.close()
    except Exception as e:
        logger.exception(f"Creator scan failed: {e}")
        _scan_state["message"] = f"error: {e}"
    finally:
        _scan_state["running"] = False
        _scan_lock.release()


def split_pack(model_id: int) -> dict:
    """Opt-in: split a model whose folder is actually a multi-product pack into one
    model per child folder. Records a durable PackOverride so the split survives
    rescans, then deletes the collapsed model and re-walks the folder as a boundary.

    Returns {"ok": bool, "created": int, "message": str}. Runs synchronously and
    holds the scan lock so it can't race a running scan."""
    if not _scan_lock.acquire(blocking=False):
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
            db.query(ModelTag).filter(ModelTag.model_id == model_id).delete(synchronize_session=False)
            db.query(CollectionModel).filter(CollectionModel.model_id == model_id).delete(synchronize_session=False)
            db.query(STLFile).filter(STLFile.model_id == model_id).delete(synchronize_session=False)
            db.query(Model).filter(Model.id == model_id).delete(synchronize_session=False)
            db.commit()
            # Expunge just the deleted model so the re-walk's inserts (SQLite may
            # reuse the freed id) don't collide with it in the identity map. The
            # creator object stays attached for the walk below.
            db.expunge(model)

            # Re-walk the pack as a boundary: it's never a model, each child is.
            before = db.query(func.count(Model.id)).filter(Model.creator_id == creator_id).scalar() or 0
            _walk_for_models(
                folder=pack,
                creator=creator,
                db=db,
                creator_boundary=pack,
                character=None,
                stl_cache={},
                last_scanned=None,
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
        _scan_lock.release()


def _scan_root(root: ScanRoot, db: Session):
    root_path = Path(root.path)
    if not root_path.exists():
        logger.warning(f"Scan root not found: {root.path}")
        _scan_state["message"] = f"path not found: {root.path}"
        return

    creator_dirs = sorted(d for d in root_path.iterdir() if d.is_dir())

    # Capture last_scanned as a plain value before fanning out — `root` belongs to
    # the main-thread session and must not be touched from worker threads.
    root_last_scanned = root.last_scanned

    # Pre-create all Creator rows in the main session before going parallel so
    # worker threads never race to INSERT the same creator name.
    creator_ids: dict[str, int] = {}
    for creator_dir in creator_dirs:
        creator = _get_or_create_creator(creator_dir.name, db)
        creator_ids[str(creator_dir)] = creator.id
    db.commit()

    def _scan_one(creator_dir: Path):
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
            )
        except Exception:
            logger.exception(f"Error scanning creator: {creator_dir.name}")
        finally:
            thread_db.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_scan_one, d) for d in creator_dirs]
        for future in as_completed(futures):
            future.result()  # propagate any unexpected exception to the outer handler


def _walk_for_models(
    folder: Path,
    creator: Creator,
    db: Session,
    creator_boundary: Path,
    character: str | None,
    stl_cache: dict[str, bool],
    last_scanned: datetime | None,
    parent_names: list[str] | None = None,
):
    if not folder.is_dir():
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
                     stl_cache, auto_signals=signals, last_scanned=last_scanned)
        return

    # --- Step 2: has STLs + children look like parts ---
    if not is_creator_root and has_any_stls:
        child_names = [d.name for d in child_dirs]
        if has_direct_stls and name_parser.children_look_like_parts(child_names):
            _index_model(folder, creator, db, creator_boundary, character,
                         stl_cache, auto_signals=signals, last_scanned=last_scanned)
            return

        # --- Step 3: deepest fallback — STLs here, nothing below ---
        if has_direct_stls and not any_child_stls:
            _index_model(folder, creator, db, creator_boundary, character,
                         stl_cache, auto_signals=signals, last_scanned=last_scanned)
            return

    # Not a leaf — recurse. Carry the deepest *meaningful* folder as the variant
    # grouping "character": skip parts and structural folders (Presupport, STL,
    # 75mm, Bust, Unsupported…) so a character's variants all group under its real
    # name instead of scattering across structural buckets.
    next_character = character
    if (not is_creator_root
            and not signals.is_parts
            and not name_parser.is_structural_folder(folder.name)):
        next_character = folder.name

    next_parents = (parent_names or []) + [folder.name]

    for child in sorted(child_dirs):
        _walk_for_models(child, creator, db, creator_boundary,
                         character=next_character, parent_names=next_parents,
                         stl_cache=stl_cache, last_scanned=last_scanned)


def _index_model(
    folder: Path,
    creator: Creator,
    db: Session,
    creator_boundary: Path | None,
    character: str | None,
    stl_cache: dict[str, bool],
    auto_signals: name_parser.NameSignals | None = None,
    last_scanned: datetime | None = None,
):
    folder_path = str(folder)

    # Serialize all DB interaction for this model. SQLite has a single writer;
    # holding this lock across the read/query + writes + commit keeps the worker
    # threads from contending at the SQLite level (which otherwise surfaces as
    # "database is locked" and drops a creator's models).
    with _db_lock:
        model = db.query(Model).filter(Model.folder_path == folder_path).first()

        # Skip expensive file indexing when the folder hasn't changed since the
        # last scan. Metadata/tag updates still run so manual edits and parser
        # improvements are picked up.
        folder_unchanged = (
            model is not None
            and last_scanned is not None
            and folder.stat().st_mtime < last_scanned.timestamp()
        )

        is_new = model is None
        if is_new:
            model = Model(
                name=folder.name,
                folder_path=folder_path,
                creator_id=creator.id,
            )
            db.add(model)
            db.flush()

        # Character grouping — always reflect the current walk (including None),
        # so a model whose path is all-structural clears any stale character that
        # an earlier scanner version assigned from a structural folder name.
        model.character = character

        # Auto-detected signals
        if auto_signals:
            model.auto_tags = auto_signals.auto_tags
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

        model.updated_at = utcnow()
        sync_model_tags(model, db)
        db.commit()

    with _state_lock:
        _scan_state["models_found"] += 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        if stl.is_file() and stl.suffix.lower() in STL_EXTENSIONS
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
    """
    creator = db.query(Creator).filter(Creator.name.ilike(name)).first()
    if not creator:
        creator = Creator(name=name)
        db.add(creator)
        db.flush()
    return creator

"""
File system scanner.

Folder structure on disk (variable depth):
  <root>/
    <Creator>/
      config.orynt3d             ← creator-level config (optional)
      <Character>/               ← user-created grouping folder
        Images/                  ← shared images (may be here or anywhere)
        <Product Variant>/       ← extracted from a ZIP ← Model
          Akuma/                 ← parts sub-folder (not a separate model)
          Base/
        <Another Variant -Pre Supported>/   ← separate Model

Leaf detection priority:
  1. config.orynt3d with modelMode == 2 (explicit Orynt3D leaf)
  2. Folder name contains scale/type/modifier signals (product boundary)
  3. Folder contains STLs and all child dirs look like parts sub-folders
  4. Folder contains STLs and has no children with STLs (deepest fallback)

Auto-tags are generated from detected scale, type, and modifier tokens.
needs_review=True is set when confidence is low.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

from sqlalchemy import text as _sqltext

from app.database import SessionLocal
from app.models import Creator, Model, STLFile, ScanRoot
from app.services import orynt3d_parser, name_parser
from app.services.tag_sync import sync_model_tags

logger = logging.getLogger(__name__)

STL_EXTENSIONS = {".stl", ".3mf", ".obj"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

_scan_lock = threading.Lock()
_state_lock = threading.Lock()
_scan_state: dict = {"running": False, "message": "idle", "models_found": 0, "files_found": 0, "cancelled": False}
_cancel_requested = False


def get_status() -> dict:
    return dict(_scan_state)


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
            # Clear needs_review for any model that already has indexed STL files —
            # those are confirmed real products that were over-eagerly flagged.
            # Orynt3D-parsed models also get cleared since they have explicit metadata.
            result = _db.execute(_sqltext(
                """
                UPDATE models SET needs_review = 0
                WHERE needs_review = 1
                  AND (
                    orynt3d_parsed = 1
                    OR id IN (SELECT DISTINCT model_id FROM stl_files)
                  )
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
                root.last_scanned = datetime.utcnow()
                _db.commit()
        finally:
            if own_db:
                _db.close()
    except Exception as e:
        logger.exception(f"Scan failed: {e}")
        _scan_state["message"] = f"error: {e}"
    finally:
        _scan_state["running"] = False
        _scan_lock.release()


def _scan_root(root: ScanRoot, db: Session):
    root_path = Path(root.path)
    if not root_path.exists():
        logger.warning(f"Scan root not found: {root.path}")
        _scan_state["message"] = f"path not found: {root.path}"
        return

    creator_dirs = sorted(d for d in root_path.iterdir() if d.is_dir())

    # Pre-create all Creator rows in the main session before going parallel so
    # worker threads never race to INSERT the same creator name.
    creator_info: dict[str, tuple[int, dict]] = {}
    for creator_dir in creator_dirs:
        creator_meta = orynt3d_parser.parse_creator_config(str(creator_dir)) or {}
        creator_name = creator_meta.get("creator_name") or creator_dir.name
        creator = _get_or_create_creator(creator_name, db)
        creator_info[str(creator_dir)] = (creator.id, creator_meta)
    db.commit()

    def _scan_one(creator_dir: Path):
        if _cancel_requested:
            return
        creator_id, creator_meta = creator_info[str(creator_dir)]
        thread_db = SessionLocal()
        try:
            creator = thread_db.get(Creator, creator_id)
            with _state_lock:
                _scan_state["message"] = f"scanning {creator_dir.name}"
            _walk_for_models(
                folder=creator_dir,
                creator=creator,
                inherited=creator_meta,
                db=thread_db,
                creator_boundary=creator_dir,
                character=None,
                stl_cache={},
                last_scanned=root.last_scanned,
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
    inherited: dict,
    db: Session,
    creator_boundary: Path,
    character: str | None,
    stl_cache: dict[str, bool],
    last_scanned: datetime | None,
    parent_names: list[str] | None = None,
):
    if not folder.is_dir():
        return

    # --- Step 1: explicit Orynt3D leaf ---
    model_meta = orynt3d_parser.parse_model_config(str(folder))
    if model_meta and model_meta.get("is_leaf"):
        _index_model(folder, creator, model_meta, inherited, db, creator_boundary, character,
                     last_scanned=last_scanned)
        return

    child_dirs = [d for d in sorted(folder.iterdir()) if d.is_dir()]
    has_direct_stls = _has_stls(folder, recurse=False)

    # Collect file names for signal detection
    try:
        filenames = [f.name for f in folder.iterdir() if f.is_file()]
    except Exception:
        filenames = []

    # --- Step 2: name-based product detection (folder + files + parents) ---
    signals = name_parser.parse_folder(
        str(folder),
        filenames=filenames,
        parent_names=parent_names,
    )
    if signals.is_product:
        _index_model(folder, creator, model_meta, inherited, db, creator_boundary, character,
                     auto_signals=signals, last_scanned=last_scanned)
        return

    # Compute once — used in both step 3 and step 4 checks below.
    any_child_stls = _any_child_has_stls_cached(child_dirs, stl_cache)

    # --- Step 3: has STLs + children look like parts ---
    if has_direct_stls or any_child_stls:
        child_names = [d.name for d in child_dirs]
        if has_direct_stls and name_parser.children_look_like_parts(child_names):
            _index_model(folder, creator, model_meta, inherited, db, creator_boundary, character,
                         auto_signals=signals, last_scanned=last_scanned)
            return

        # --- Step 4: deepest fallback — STLs here, nothing below ---
        if has_direct_stls and not any_child_stls:
            _index_model(folder, creator, model_meta, inherited, db, creator_boundary, character,
                         auto_signals=signals, last_scanned=last_scanned)
            return

    # Not a leaf — recurse, carrying this folder name as character context
    # and adding it to parent_names for child signal detection.
    next_character = character
    if folder != creator_boundary and not signals.is_parts:
        next_character = folder.name

    next_parents = (parent_names or []) + [folder.name]

    for child in sorted(child_dirs):
        _walk_for_models(child, creator, inherited, db, creator_boundary,
                         character=next_character, parent_names=next_parents,
                         stl_cache=stl_cache, last_scanned=last_scanned)


def _index_model(
    folder: Path,
    creator: Creator,
    model_meta: dict | None,
    inherited: dict,
    db: Session,
    creator_boundary: Path | None,
    character: str | None,
    auto_signals: name_parser.NameSignals | None = None,
    last_scanned: datetime | None = None,
):
    folder_path = str(folder)
    model = db.query(Model).filter(Model.folder_path == folder_path).first()

    # Skip expensive file indexing when the folder hasn't changed since the
    # last scan. Metadata updates (tags, orynt3d) still run so manual edits
    # and parser improvements are picked up.
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

    # Character grouping
    if character:
        model.character = character

    # Auto-detected signals
    if auto_signals:
        model.auto_tags = auto_signals.auto_tags
        # Only flag needs_review for brand-new models that look genuinely
        # ambiguous: no orynt3d config AND no name/type signals AND no
        # direct STL files in this folder (only found recursively).
        # Existing models are cleared at scan start if they have STL files,
        # so we avoid re-flagging the same false positives on every rescan.
        if is_new and not model_meta and auto_signals.confidence < 0.25:
            has_direct_stls = _has_stls(folder, recurse=False)
            if not has_direct_stls:
                model.needs_review = True

    # orynt3d metadata
    if model_meta:
        if model_meta.get("name"):
            model.title = model_meta["name"]
        model.notes = model_meta.get("notes") or model.notes
        model.tags = model_meta.get("tags") or model.tags or []
        model.orynt3d_parsed = True
        model.source_site = (
            model_meta.get("source_site")
            or inherited.get("source_site")
            or model.source_site
        )
        model.source_url = model_meta.get("source_url") or model.source_url
        attrs = model_meta.get("attributes") or {}
        if attrs:
            model.custom_attributes = attrs
        model.orynt3d_collections = model_meta.get("collections") or model.orynt3d_collections or []
        if model_meta.get("cover_path"):
            model.thumbnail_path = model_meta["cover_path"]
    elif inherited:
        model.source_site = inherited.get("source_site") or model.source_site

    if not folder_unchanged:
        # Thumbnail: walk upward if not already set
        if not model.thumbnail_path:
            _find_thumbnail(model, folder, boundary=creator_boundary or folder,
                            stl_cache=stl_cache)

        _index_stl_files(model, folder, db)

    model.updated_at = datetime.utcnow()
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

"""Import pipeline endpoints (#449 epic).

Child A (#450) starts this router with the persisted source→library mapping.
Children B/C/D extend it with the pack-grouped preview projection, scoped
ingest, and batch apply. Module is named `imports` because `import` is a
reserved word.
"""
import logging
import os
import shutil
import threading
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportSourceMapping, Model, ScanRoot, STLFile
from app.routers.reorganize import _build_and_persist
from app.routers.scan import _bootstrap_roots, _configured_roots
from app.schemas import (
    DownloadImagesRequest,
    ImportApplyIneligible, ImportApplyRequest, ImportApplyResponse,
    ImportPreviewPack, ImportPreviewResponse, InboxScanRequest,
    SourceContentsEntry, SourceContentsResponse,
    SourceMappingRead, SourceMappingSet,
)
from app.services import reorganize_apply, scanner, write_lock
from app.services.reorganize_apply import ApplyError

router = APIRouter(prefix="/import", tags=["import"])


# Entry flags (Phase 1) that make a pack ineligible to move, mapped to a reason.
_INELIGIBLE_FLAGS = [
    ("unclassifiable", "missing creator/character"),
    ("collision", "destination collision"),
    ("over_length", "path too long"),
    ("reserved_name", "reserved filename"),
    ("overlaps_other", "overlaps another move"),
    ("spans_multiple_dirs", "files span multiple folders"),
    ("is_symlink", "symlinked"),
    ("escapes_scan_root", "no writable destination library"),
    ("missing_files_on_disk", "files missing on disk"),
]


def _ineligible_reasons(entry) -> list[str]:
    reasons = [label for attr, label in _INELIGIBLE_FLAGS if getattr(entry, attr, False)]
    if getattr(entry, "missing_fields", None):
        reasons.append("missing " + ", ".join(entry.missing_fields))
    return reasons or ["ineligible"]


def _allowed_bases(db: Session) -> list[str]:
    """Resolved allow set for import paths: configured scan roots + the bootstrap
    browse allowlist. Import sources come through the allowlist-guarded folder
    picker, and a pack may sit inside a configured root, so both are permitted."""
    return [os.path.realpath(str(r)) for r in _configured_roots(db) + _bootstrap_roots()]


def _pack_key(folder_path: str, source: str) -> str:
    """The pack a model belongs to = the first path segment below `source`.

    A model sitting directly in `source` (flat layout) is its own pack, keyed by
    the source basename. Lexical only (normpath), separator-safe for Windows."""
    rel = os.path.relpath(folder_path, source)
    first = rel.replace("\\", "/").split("/", 1)[0]
    if first in ("", ".", ".."):
        return os.path.basename(source.rstrip("/\\")) or source
    return first


def _collapse(values: list) -> object | None:
    """Single distinct non-empty value across the pack, else None."""
    distinct = {v for v in values if v}
    return next(iter(distinct)) if len(distinct) == 1 else None


@router.get("/source-contents", response_model=SourceContentsResponse)
def source_contents(source: str, db: Session = Depends(get_db)):
    """List a source folder's immediate subfolders as browse-first pack cards (#452).

    `already_imported` flags a subfolder that already has inbox models ingested,
    so a re-listing ("Scan for New Files") distinguishes new packs from imported
    ones. Each entry carries a recursive STL-family file count from disk (#456).
    The source is resolved and confined to the allowed roots (configured scan
    roots + bootstrap allowlist) before any disk access."""
    if not source.strip():
        raise HTTPException(status_code=400, detail="source is required")

    # Path-injection barrier (inline so CodeQL sees the guard at the sink):
    # realpath + commonpath containment against the allowed roots.
    real = os.path.realpath(source.strip())
    contained = False
    for base in _allowed_bases(db):
        try:
            if os.path.commonpath([real, base]) == base:
                contained = True
                break
        except ValueError:
            continue  # different drives (Windows)
    if not contained:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders")

    p = Path(real)
    src = real
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    # A source whose root holds STLs directly is a single flat pack (mirrors the
    # inbox scanner's flat-layout branch).
    is_flat = scanner._has_stls(p, recurse=False)

    # Recursive STL-family counts (#456) in one walk rooted at the already-confined
    # `p` (the raising barrier above dominates this sink, so no tainted path is
    # walked): the running total feeds the flat single-card, and each top-level
    # child accumulates its whole subtree for that pack's card.
    total_stls = 0
    child_stls: dict[str, int] = {}
    for dirpath, _dirnames, filenames in os.walk(p):
        n = sum(1 for f in filenames if os.path.splitext(f)[1].lower() in scanner.STL_EXTENSIONS)
        if not n:
            continue
        total_stls += n
        rel = os.path.relpath(dirpath, src)
        if rel != ".":
            top = rel.replace("\\", "/").split("/", 1)[0]
            cp = os.path.normpath(os.path.join(src, top))
            child_stls[cp] = child_stls.get(cp, 0) + n
    root_file_count = total_stls if is_flat else 0

    # Inbox model folder_paths already under this source, for the imported flag.
    prefix = src + os.sep
    imported = {
        os.path.normpath(fp)
        for (fp,) in db.query(Model.folder_path)
        .filter(Model.is_inbox == True)  # noqa: E712
        .filter((Model.folder_path == src) | (Model.folder_path.like(f"{prefix}%")))
    }

    entries: list[SourceContentsEntry] = []
    if not is_flat:
        for d in sorted(p.iterdir(), key=lambda e: e.name.lower()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            dp = os.path.normpath(str(d))
            child_prefix = dp + os.sep
            already = any(m == dp or m.startswith(child_prefix) for m in imported)
            entries.append(SourceContentsEntry(
                name=d.name, path=dp, already_imported=already,
                file_count=child_stls.get(dp, 0),
            ))

    return SourceContentsResponse(
        source=src, is_flat=is_flat, entries=entries, file_count=root_file_count,
    )


@router.post("/scan-folder", response_model=dict)
def scan_folder(body: InboxScanRequest, db: Session = Depends(get_db)):
    """Scoped inbox ingest of a single pack folder (#452, browse-first import).

    Unlike POST /scan/inbox, this does NOT reject a path overlapping a scan root:
    importing a specific folder is explicit, and the source may legitimately live
    inside a configured root. Models are indexed is_inbox=True; the move into the
    destination library is the batch apply (Child D)."""
    status = scanner.get_status()
    if status["running"]:
        raise HTTPException(status_code=409, detail="Scan already running")

    if not body.path.strip():
        raise HTTPException(status_code=400, detail="Path is required")

    # Path-injection barrier (inline; see source_contents).
    real = os.path.realpath(body.path.strip())
    contained = False
    for base in _allowed_bases(db):
        try:
            if os.path.commonpath([real, base]) == base:
                contained = True
                break
        except ValueError:
            continue
    if not contained:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders")

    p = Path(real)
    if not p.exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    if not scanner.prepare_inbox_scan():
        raise HTTPException(
            status_code=409,
            detail="Library is busy — reorganize in progress, try again shortly",
        )
    try:
        thread = threading.Thread(
            target=scanner.scan_inbox_folder,
            args=(str(p),),
            kwargs={"_lock_already_held": True},
            daemon=True,
        )
        thread.start()
    except Exception as e:
        scanner.abort_inbox_scan()
        raise HTTPException(status_code=500, detail=f"Failed to start import: {e}")

    return {"running": True, "message": "importing"}


@router.get("/preview", response_model=ImportPreviewResponse)
def import_preview(source: str, db: Session = Depends(get_db)):
    """Group the inbox models under a source folder into one card per pack (#451).

    A pack = a top-level subfolder of `source` (flat-layout models at the root
    form a single pack). Representative metadata collapses to the common value
    across the pack, or null when members disagree. The destination library is
    inherited from the persisted source→library mapping."""
    src = os.path.normpath(source.strip())
    if not src or src == ".":
        raise HTTPException(status_code=400, detail="source is required")

    prefix = src + os.sep
    models = (
        db.query(Model)
        .filter(Model.is_inbox == True)  # noqa: E712
        .filter((Model.folder_path == src) | (Model.folder_path.like(f"{prefix}%")))
        .all()
    )

    # Only count models actually under `src` after normalization (LIKE is a coarse
    # prefilter; normpath comparison is authoritative).
    buckets: dict[str, list[Model]] = {}
    for m in models:
        mp = os.path.normpath(m.folder_path)
        if mp != src and not mp.startswith(prefix):
            continue
        buckets.setdefault(_pack_key(mp, src), []).append(m)

    file_counts = dict(
        db.query(STLFile.model_id, func.count(STLFile.id))
        .filter(STLFile.model_id.in_([m.id for m in models]))
        .group_by(STLFile.model_id)
        .all()
    ) if models else {}

    packs: list[ImportPreviewPack] = []
    for key in sorted(buckets):
        members = buckets[key]
        tag_sets = [tuple(sorted(m.tags or [])) for m in members]
        # Flat-layout pack (a model sitting directly in src) → src itself;
        # otherwise the pack lives at src/<key>.
        is_flat = any(os.path.normpath(m.folder_path) == src for m in members)
        packs.append(ImportPreviewPack(
            name=key,
            source_path=src if is_flat else os.path.join(src, key),
            file_count=sum(file_counts.get(m.id, 0) for m in members),
            model_ids=sorted(m.id for m in members),
            creator_name=_collapse([m.creator.name if m.creator else None for m in members]),
            title=_collapse([m.title for m in members]),
            character=_collapse([m.character for m in members]),
            notes=_collapse([m.notes for m in members]),
            source_url=_collapse([m.source_url for m in members]),
            tags=list(_collapse(tag_sets) or ()),
        ))

    mapping = (
        db.query(ImportSourceMapping)
        .filter(ImportSourceMapping.source_path == src)
        .first()
    )
    return ImportPreviewResponse(
        source=src,
        library_id=mapping.library_id if mapping else None,
        packs=packs,
    )


@router.get("/source-mapping", response_model=SourceMappingRead | None)
def get_source_mapping(path: str, db: Session = Depends(get_db)):
    """Return the destination library mapped to a source root, or null (#450)."""
    source = path.strip()
    if not source:
        raise HTTPException(status_code=400, detail="path is required")
    return (
        db.query(ImportSourceMapping)
        .filter(ImportSourceMapping.source_path == source)
        .first()
    )


@router.put("/source-mapping", response_model=SourceMappingRead)
def set_source_mapping(body: SourceMappingSet, db: Session = Depends(get_db)):
    """Persist (upsert) a source root → destination library mapping (#450).

    The destination must be a writable library; the actual disk-write probe and
    deployment flag are still enforced at apply time (#324)."""
    source = body.source_path.strip()
    if not source:
        raise HTTPException(status_code=400, detail="source_path is required")

    library = db.query(ScanRoot).filter(ScanRoot.id == body.library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    if not library.is_writable:
        raise HTTPException(
            status_code=400,
            detail="Destination is not a writable library.",
        )

    mapping = (
        db.query(ImportSourceMapping)
        .filter(ImportSourceMapping.source_path == source)
        .first()
    )
    if mapping:
        mapping.library_id = library.id
    else:
        mapping = ImportSourceMapping(source_path=source, library_id=library.id)
        db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


_CT_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg",
    "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _image_ext(url: str, content_type: str) -> str:
    """Best-effort image extension from Content-Type, falling back to URL suffix."""
    ext = _CT_TO_EXT.get(content_type.split(";")[0].strip().lower(), "")
    if ext:
        return ext
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in _IMAGE_EXTS else ".jpg"


@router.post("/download-images")
def download_images(body: DownloadImagesRequest, db: Session = Depends(get_db)):
    """Download CDN image URLs into the pack folder so they travel with the pack
    during apply. Called from the import UI after enrichment, before apply."""
    raw_pack_path = body.pack_path.strip()
    if not raw_pack_path:
        raise HTTPException(status_code=400, detail="pack_path is required")
    if "\x00" in raw_pack_path:
        raise HTTPException(status_code=400, detail="pack_path is invalid")

    candidate_pack_path = Path(raw_pack_path)
    if not candidate_pack_path.is_absolute():
        raise HTTPException(status_code=400, detail="pack_path must be an absolute path")
    if ".." in candidate_pack_path.parts:
        raise HTTPException(status_code=400, detail="pack_path is invalid")

    pack_dir = candidate_pack_path.expanduser().resolve(strict=False)

    # Path guard: must be within a configured or bootstrap-allowed root.
    contained = False
    for base in _allowed_bases(db):
        try:
            base_dir = Path(base).expanduser().resolve(strict=False)
            pack_dir.relative_to(base_dir)
            contained = True
            break
        except ValueError:
            continue
    if not contained:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders")
    if not pack_dir.is_dir():
        raise HTTPException(status_code=404, detail="Pack folder not found")

    downloaded = 0
    with httpx.Client(timeout=30, follow_redirects=True,
                      headers={"User-Agent": "STL-Inventory/1.0"}) as client:
        for n, url in enumerate(body.image_urls[:30]):  # cap at 30 images
            try:
                r = client.get(url)
                r.raise_for_status()
                ct = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if ct in ("image/svg+xml", "text/html", "application/json"):
                    logger.warning("gallery image %d skipped — unsupported content-type %r", n, ct)
                    continue
                ext = _image_ext(url, ct)
                # Guard: ext must be a known-safe image extension — reject anything
                # that could escape the filename (e.g. a crafted URL suffix).
                if ext not in _IMAGE_EXTS:
                    logger.warning("gallery image %d skipped — unexpected ext %r", n, ext)
                    continue
                dest = pack_dir / f"gallery_{n:02d}{ext}"
                dest.write_bytes(r.content)
                downloaded += 1
            except Exception as e:
                logger.warning("gallery image %d download failed: %s", n, e)
    return {"downloaded": downloaded}


def _move_non_stl_files(
    old_folder: str,
    new_folder: str,
    models: list,
    db: Session,
) -> None:
    """Move every non-STL file from old_folder to new_folder (preserving relative
    paths) and update image_paths / other_files on all models in that folder.

    Called after the reorganize engine has already moved the STL files, so only
    non-tracked files remain. Images go into model.image_paths; everything else
    into model.other_files."""
    if not os.path.isdir(old_folder):
        return

    new_images: list[str] = []
    new_others: list[str] = []

    for dirpath, dirnames, filenames in os.walk(old_folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if filename.startswith("."):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext in scanner.STL_EXTENSIONS:
                continue  # already moved by the reorganize engine

            src = Path(os.path.join(dirpath, filename)).resolve()
            rel = os.path.relpath(str(src), old_folder)
            dst = (Path(new_folder) / rel).resolve()

            # Verify the resolved destination is still inside new_folder to
            # prevent symlink-based traversal escaping the target directory.
            if not dst.is_relative_to(Path(new_folder).resolve()):
                logger.warning("Skipping %r — resolved outside target folder", str(src))
                continue

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                if ext in _IMAGE_EXTS:
                    new_images.append(str(dst))
                else:
                    new_others.append(str(dst))
            except Exception as e:
                logger.warning("Could not move %r → %r: %s", src, dst, e)

    for m in models:
        if new_images:
            m.image_paths = new_images
        if new_others:
            m.other_files = new_others
        # Remap thumbnail_path if it pointed into the old folder (stale after move).
        if m.thumbnail_path and m.thumbnail_path.startswith(old_folder + os.sep):
            rel = os.path.relpath(m.thumbnail_path, old_folder)
            remapped = os.path.join(new_folder, rel)
            m.thumbnail_path = remapped if os.path.exists(remapped) else None


def _cleanup_non_stl_folders(old_to_new: dict[str, str], db: Session) -> None:
    """Move non-STL files from import folders to their library destinations and
    remove the source folder. Only runs when the destination already exists on
    disk — handles the case where STLs were moved by a prior import session but
    the gallery images were left behind."""
    for old_folder, new_folder in old_to_new.items():
        if not os.path.isdir(old_folder):
            continue
        if not os.path.isdir(new_folder):
            logger.warning(
                "Destination %r does not exist; skipping non-STL cleanup for %r",
                new_folder, old_folder,
            )
            continue
        # Find the library model at the destination so we can update image_paths.
        dest_models = db.query(Model).filter(Model.folder_path == new_folder).all()
        try:
            _move_non_stl_files(old_folder, new_folder, dest_models, db)
            db.commit()
            old_resolved = os.path.realpath(old_folder)
            try:
                shutil.rmtree(old_resolved)
            except Exception as e:
                logger.warning("Could not remove old pack folder %r: %s", old_resolved, e)
        except Exception:
            logger.exception("Non-STL cleanup failed for %r → %r", old_folder, new_folder)


@router.post("/apply", response_model=ImportApplyResponse)
def import_apply(body: ImportApplyRequest, db: Session = Depends(get_db)):
    """Batch-move the ingested inbox packs under a source into their mapped
    library (#453). Builds a manifest scoped to those inbox models (destination =
    mapped library via the source→library mapping) and runs it through the
    existing reorganize apply engine — drift verification + crash-safe undo log,
    is_inbox cleared on move (#324). After the STL move, all remaining files
    (images, PDFs, etc.) are moved to the library folder and the old pack folder
    is removed."""
    src = os.path.realpath(body.source.strip())
    if not body.source.strip():
        raise HTTPException(status_code=400, detail="source is required")

    allowed_roots = [os.path.realpath(root) for root in _configured_roots(db)]
    if not any(
        os.path.commonpath([src, root]) == root
        for root in allowed_roots
    ):
        raise HTTPException(status_code=400, detail="source must be within a configured scan root")

    mapping = (
        db.query(ImportSourceMapping)
        .filter(ImportSourceMapping.source_path == src)
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=400, detail="No destination library mapped for this source.")

    # Use {creator}/{title} template so imports land in creator/slug-of-title.
    # slugify_title=True converts the {title} segment to a lowercase-dashes slug.
    resp = _build_and_persist(
        db, "{creator}/{title}", None, None, inbox_source=src, slugify_title=True
    )
    eligible_ids = [e.model_id for e in resp.entries if e.eligible]
    ineligible = [
        ImportApplyIneligible(
            model_id=e.model_id, proposed_dir=e.proposed_dir, reasons=_ineligible_reasons(e),
        )
        for e in resp.entries if not e.eligible
    ]

    # Capture old folder paths for ALL manifest entries (eligible + ineligible) so
    # we can move non-STL files and remove old pack folders regardless of eligibility.
    all_model_ids = [e.model_id for e in resp.entries]
    all_folder_map: dict[int, str] = {
        m.id: m.folder_path
        for m in db.query(Model).filter(Model.id.in_(all_model_ids)).all()
        if m.folder_path
    }
    # old→new from ALL manifest entries; we only move non-STL files when the
    # destination already exists on disk (covers "files missing on disk" ineligible
    # models whose STLs were already moved by a prior import).
    all_old_to_new: dict[str, str] = {}
    for entry in resp.entries:
        old = all_folder_map.get(entry.model_id, "")
        if old and old not in all_old_to_new and entry.proposed_dir:
            all_old_to_new[old] = entry.proposed_dir

    if not eligible_ids:
        # No STLs to move, but still clean up non-STL files (gallery images, etc.)
        # that were downloaded into the import folder before eligibility was checked.
        _cleanup_non_stl_folders(all_old_to_new, db)
        return ImportApplyResponse(
            manifest_id=resp.manifest_id, moved_models=0, moved_files=0,
            skipped=len(ineligible), ineligible=ineligible,
        )

    eligible_set = set(eligible_ids)

    try:
        result = reorganize_apply.apply_manifest(db, resp.manifest_id, eligible_ids)
    except write_lock.LibraryBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ApplyError as e:
        raise HTTPException(status_code=e.status, detail={"message": str(e), **e.detail})

    # Move all remaining non-STL files (images, PDFs, etc.) from each old folder
    # to the new library folder, then remove the now-empty source folder.
    try:
        model_by_id = {
            m.id: m
            for m in db.query(Model).filter(Model.id.in_(eligible_ids)).all()
        }
        for old_folder, new_folder in all_old_to_new.items():
            # For ineligible packs only move non-STL files if the destination
            # already exists; eligible packs always get moved.
            if not os.path.isdir(new_folder):
                continue
            models_here = [
                model_by_id[mid]
                for mid, old in all_folder_map.items()
                if old == old_folder and mid in model_by_id
            ]
            _move_non_stl_files(old_folder, new_folder, models_here, db)
            # Resolve before rmtree so any symlink traversal is collapsed first.
            old_resolved = os.path.realpath(old_folder)
            try:
                shutil.rmtree(old_resolved)
            except Exception as rmtree_err:
                logger.warning("Could not remove old pack folder %r: %s", old_resolved, rmtree_err)
        db.commit()
    except Exception:
        logger.exception("Non-STL file move/cleanup failed; STL files were already moved successfully")

    # Clean up any stale empty directories left in the source root.
    try:
        for dirpath, _, filenames in os.walk(src, topdown=False):
            if not filenames:
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass
    except Exception:
        pass

    return ImportApplyResponse(
        manifest_id=result.manifest_id,
        moved_models=result.moved_models,
        moved_files=result.moved_files,
        skipped=len(ineligible),
        ineligible=ineligible,
        undo_log=result.undo_log,
    )

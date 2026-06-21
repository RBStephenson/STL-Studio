"""Import pipeline endpoints (#449 epic).

Child A (#450) starts this router with the persisted source→library mapping.
Children B/C/D extend it with the pack-grouped preview projection, scoped
ingest, and batch apply. Module is named `imports` because `import` is a
reserved word.
"""
import os
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportSourceMapping, Model, ScanRoot, STLFile
from app.routers.reorganize import _build_and_persist
from app.routers.scan import _bootstrap_roots, _configured_roots
from app.schemas import (
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


def _count_stls(folder: Path, allowed_bases: list[str]) -> int:
    """Recursive count of STL-family files under a folder (#456), so a pack card
    shows its size before import. Reuses the scanner's extension set so it matches
    what an inbox scan would actually ingest. A pure filesystem walk — no DB.

    The folder is already confined by the caller, but the containment barrier is
    re-applied inline here (realpath + commonpath) so CodeQL sees the guard at the
    walk sink — a tainted path that escaped the allowlist returns 0, never walks."""
    real = os.path.realpath(str(folder))
    contained = False
    for base in allowed_bases:
        try:
            if os.path.commonpath([real, base]) == base:
                contained = True
                break
        except ValueError:
            continue  # different drives (Windows)
    if not contained:
        return 0
    return sum(
        1 for f in Path(real).rglob("*")
        if f.is_file() and f.suffix.lower() in scanner.STL_EXTENSIONS
    )


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
    bases = _allowed_bases(db)
    contained = False
    for base in bases:
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
    # Root count only feeds the flat single-card; for the subfolder layout each
    # entry carries its own recursive count, so the root walk would be wasted.
    root_file_count = _count_stls(p, bases) if is_flat else 0

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
                file_count=_count_stls(d, bases),
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


@router.post("/apply", response_model=ImportApplyResponse)
def import_apply(body: ImportApplyRequest, db: Session = Depends(get_db)):
    """Batch-move the ingested inbox packs under a source into their mapped
    library (#453). Builds a manifest scoped to those inbox models (destination =
    mapped library via the source→library mapping) and runs it through the
    existing reorganize apply engine — drift verification + crash-safe undo log,
    is_inbox cleared on move (#324). No second mover."""
    src = os.path.realpath(body.source.strip())
    if not body.source.strip():
        raise HTTPException(status_code=400, detail="source is required")

    mapping = (
        db.query(ImportSourceMapping)
        .filter(ImportSourceMapping.source_path == src)
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=400, detail="No destination library mapped for this source.")

    resp = _build_and_persist(db, None, None, None, inbox_source=src)
    eligible_ids = [e.model_id for e in resp.entries if e.eligible]
    ineligible = [
        ImportApplyIneligible(
            model_id=e.model_id, proposed_dir=e.proposed_dir, reasons=_ineligible_reasons(e),
        )
        for e in resp.entries if not e.eligible
    ]

    if not eligible_ids:
        return ImportApplyResponse(
            manifest_id=resp.manifest_id, moved_models=0, moved_files=0,
            skipped=len(ineligible), ineligible=ineligible,
        )

    try:
        result = reorganize_apply.apply_manifest(db, resp.manifest_id, eligible_ids)
    except write_lock.LibraryBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ApplyError as e:
        raise HTTPException(status_code=e.status, detail={"message": str(e), **e.detail})

    return ImportApplyResponse(
        manifest_id=result.manifest_id,
        moved_models=result.moved_models,
        moved_files=result.moved_files,
        skipped=len(ineligible),
        ineligible=ineligible,
        undo_log=result.undo_log,
    )

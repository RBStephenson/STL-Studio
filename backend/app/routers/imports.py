"""Import pipeline endpoints (#449 epic).

Child A (#450) starts this router with the persisted source→library mapping.
Children B/C/D extend it with the pack-grouped preview projection, scoped
ingest, and batch apply. Module is named `imports` because `import` is a
reserved word.
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportSourceMapping, Model, ScanRoot, STLFile
from app.schemas import (
    ImportPreviewPack, ImportPreviewResponse, SourceMappingRead, SourceMappingSet,
)

router = APIRouter(prefix="/import", tags=["import"])


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

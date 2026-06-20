"""Import pipeline endpoints (#449 epic).

Child A (#450) starts this router with the persisted source→library mapping.
Children B/C/D extend it with the pack-grouped preview projection, scoped
ingest, and batch apply. Module is named `imports` because `import` is a
reserved word.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportSourceMapping, ScanRoot
from app.schemas import SourceMappingRead, SourceMappingSet

router = APIRouter(prefix="/import", tags=["import"])


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

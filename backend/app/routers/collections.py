from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Collection, CollectionModel, Model
from app.schemas import (
    CollectionBase,
    CollectionBulkAdd,
    CollectionBulkAddResponse,
    CollectionRead,
    CollectionUpdate,
    ModelRead,
)
from app.services.thumbnails import (
    ThumbnailDownloadError,
    clear_collection_cover,
    fetch_image_bytes,
    store_collection_cover,
)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("", response_model=list[CollectionRead])
def list_collections(db: Session = Depends(get_db)):
    rows = (
        db.query(Collection, func.count(Model.id).label("cnt"))
        .outerjoin(CollectionModel, CollectionModel.collection_id == Collection.id)
        .outerjoin(Model, (Model.id == CollectionModel.model_id) & (Model.excluded == False))
        .group_by(Collection.id)
        .order_by(Collection.name)
        .all()
    )
    result = []
    for collection, cnt in rows:
        cr = CollectionRead.model_validate(collection)
        cr.model_count = cnt
        result.append(cr)
    return result


@router.post("", response_model=CollectionRead, status_code=201)
def create_collection(body: CollectionBase, db: Session = Depends(get_db)):
    col = Collection(**body.model_dump())
    db.add(col)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A collection with that name already exists")
    db.refresh(col)
    return col


@router.get("/{collection_id}/models", response_model=list[ModelRead])
def get_collection_models(collection_id: int, db: Session = Depends(get_db)):
    col = db.query(Collection).filter(Collection.id == collection_id).first()
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
    models = (
        db.query(Model)
        .join(CollectionModel, CollectionModel.model_id == Model.id)
        .filter(CollectionModel.collection_id == collection_id, Model.excluded == False)
        .order_by(Model.title, Model.name)
        .all()
    )
    return models


@router.post("/{collection_id}/models/bulk", response_model=CollectionBulkAddResponse)
def bulk_add_models_to_collection(collection_id: int, body: CollectionBulkAdd, db: Session = Depends(get_db)):
    """Add multiple models to a collection in one request (STUDIO-373).

    Any requested id that belongs to a variant group expands to every
    non-excluded model in that group — selecting a collapsed group card in the
    Library grid only carries the representative model's id, so this is what
    makes "add the whole group" work from that single click. Directly-selected
    ids are added as given, whether or not they're excluded, since excluded
    models can only reach this endpoint via explicit selection (the Library
    grid never shows them). Declared before the /{model_id} route below so
    "bulk" isn't swallowed by that route's int path param.
    """
    _col_or_404(collection_id, db)
    if not body.model_ids:
        raise HTTPException(status_code=400, detail="No model IDs provided")

    seed_models = db.query(Model).filter(Model.id.in_(body.model_ids)).all()
    if not seed_models:
        raise HTTPException(status_code=404, detail="No matching models found")

    expanded_ids = {m.id for m in seed_models}
    group_ids = {m.variant_group_id for m in seed_models if m.variant_group_id is not None}
    if group_ids:
        siblings = (
            db.query(Model.id)
            .filter(Model.variant_group_id.in_(group_ids), Model.excluded == False)
            .all()
        )
        expanded_ids.update(model_id for (model_id,) in siblings)

    existing_ids = {
        row.model_id
        for row in db.query(CollectionModel.model_id).filter(
            CollectionModel.collection_id == collection_id,
            CollectionModel.model_id.in_(expanded_ids),
        )
    }
    to_add = expanded_ids - existing_ids
    for model_id in to_add:
        db.add(CollectionModel(collection_id=collection_id, model_id=model_id))
    db.commit()
    return CollectionBulkAddResponse(added=len(to_add), total=len(expanded_ids))


@router.post("/{collection_id}/models/{model_id}", status_code=204)
def add_model_to_collection(collection_id: int, model_id: int, db: Session = Depends(get_db)):
    col = db.query(Collection).filter(Collection.id == collection_id).first()
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
    mdl = db.query(Model).filter(Model.id == model_id).first()
    if not mdl:
        raise HTTPException(status_code=404, detail="Model not found")
    existing = db.query(CollectionModel).filter(
        CollectionModel.collection_id == collection_id,
        CollectionModel.model_id == model_id,
    ).first()
    if not existing:
        db.add(CollectionModel(collection_id=collection_id, model_id=model_id))
        db.commit()


@router.patch("/{collection_id}", response_model=CollectionRead)
def update_collection(collection_id: int, body: CollectionUpdate, db: Session = Depends(get_db)):
    col = db.query(Collection).filter(Collection.id == collection_id).first()
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(col, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A collection with that name already exists")
    db.refresh(col)
    return col


@router.delete("/{collection_id}", status_code=204)
def delete_collection(collection_id: int, db: Session = Depends(get_db)):
    col = db.query(Collection).filter(Collection.id == collection_id).first()
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
    # Manual cascade: PRAGMA foreign_keys is off, so without this the link
    # rows linger and a future collection that reuses the rowid inherits
    # the deleted collection's members (#214).
    db.query(CollectionModel).filter(
        CollectionModel.collection_id == collection_id
    ).delete(synchronize_session=False)
    clear_collection_cover(collection_id)
    db.delete(col)
    db.commit()


@router.delete("/{collection_id}/models/{model_id}", status_code=204)
def remove_model_from_collection(collection_id: int, model_id: int, db: Session = Depends(get_db)):
    link = db.query(CollectionModel).filter(
        CollectionModel.collection_id == collection_id,
        CollectionModel.model_id == model_id,
    ).first()
    if link:
        db.delete(link)
        db.commit()


# ---------------------------------------------------------------------------
# Collection cover image
# ---------------------------------------------------------------------------

class _CoverFromUrl(BaseModel):
    url: str


class _CoverFromModel(BaseModel):
    model_id: int


def _col_or_404(collection_id: int, db: Session) -> Collection:
    col = db.query(Collection).filter(Collection.id == collection_id).first()
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
    return col


def _read_response(col: Collection, db: Session) -> CollectionRead:
    cnt = (
        db.query(func.count(Model.id))
        .join(CollectionModel, CollectionModel.model_id == Model.id)
        .filter(CollectionModel.collection_id == col.id, Model.excluded == False)
        .scalar() or 0
    )
    cr = CollectionRead.model_validate(col)
    cr.model_count = cnt
    return cr


@router.post("/{collection_id}/cover/from-url", response_model=CollectionRead)
async def set_cover_from_url(collection_id: int, body: _CoverFromUrl, db: Session = Depends(get_db)):
    col = _col_or_404(collection_id, db)
    try:
        ext, data = await fetch_image_bytes(body.url)
    except ThumbnailDownloadError as e:
        raise HTTPException(status_code=422, detail=str(e))
    path = store_collection_cover(collection_id, ext, data)
    col.cover_image_path = str(path)
    db.commit()
    db.refresh(col)
    return _read_response(col, db)


@router.post("/{collection_id}/cover/upload", response_model=CollectionRead)
async def upload_cover(
    collection_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    col = _col_or_404(collection_id, db)
    if file.content_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise HTTPException(status_code=400, detail="Only PNG/JPEG/WebP/GIF images are accepted")
    ext_map = {
        "image/png": ".png", "image/jpeg": ".jpg",
        "image/webp": ".webp", "image/gif": ".gif",
    }
    ext = ext_map[file.content_type]
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (max 15 MB)")
    path = store_collection_cover(collection_id, ext, data)
    col.cover_image_path = str(path)
    db.commit()
    db.refresh(col)
    return _read_response(col, db)


@router.post("/{collection_id}/cover/from-model", response_model=CollectionRead)
def set_cover_from_model(collection_id: int, body: _CoverFromModel, db: Session = Depends(get_db)):
    col = _col_or_404(collection_id, db)
    mdl = db.query(Model).filter(Model.id == body.model_id).first()
    if not mdl:
        raise HTTPException(status_code=404, detail="Model not found")

    from pathlib import Path as _Path

    # Priority: thumbnail_path → primary_image_path → first image_path
    candidates: list[str] = []
    if mdl.thumbnail_path:
        candidates.append(mdl.thumbnail_path)
    if mdl.primary_image_path:
        candidates.append(mdl.primary_image_path)
    if isinstance(mdl.image_paths, list):
        candidates.extend(p for p in mdl.image_paths if isinstance(p, str))

    src_path: _Path | None = None
    for c in candidates:
        p = _Path(c)
        if p.exists() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            src_path = p
            break

    if src_path is None:
        raise HTTPException(status_code=422, detail="That model has no usable local image")

    path = store_collection_cover(collection_id, src_path.suffix.lower(), src_path.read_bytes())
    col.cover_image_path = str(path)
    db.commit()
    db.refresh(col)
    return _read_response(col, db)


@router.delete("/{collection_id}/cover", response_model=CollectionRead)
def clear_cover(collection_id: int, db: Session = Depends(get_db)):
    col = _col_or_404(collection_id, db)
    clear_collection_cover(collection_id)
    col.cover_image_path = None
    db.commit()
    db.refresh(col)
    return _read_response(col, db)

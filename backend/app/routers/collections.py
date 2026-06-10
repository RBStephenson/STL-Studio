from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Collection, CollectionModel, Model
from app.schemas import CollectionBase, CollectionRead, CollectionUpdate, ModelRead

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

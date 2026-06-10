"""Paint Shelf (inventory) endpoints — brands, lines, and paints (M1, #240).

`matchable` is always derived from `finish` server-side (spec §8.6); the
create/update schemas don't expose it. Code-pattern validation against
paint_line.code_pattern is #244 and slots into create/update here.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.painting.models import Paint, PaintBrand, PaintLine
from app.painting.schemas import (
    BrandCreate, BrandRead,
    PaintLineCreate, PaintLineRead, PaintLineUpdate,
    PaintCreate, PaintList, PaintRead, PaintUpdate,
    derive_matchable,
)

router = APIRouter()

# Fields where an explicit JSON null is a valid "clear this" request; the
# rest are non-nullable columns, so null means "leave unchanged" and is dropped.
_NULLABLE_PAINT_FIELDS = {"hex", "value_pct", "notes", "source"}


def _get_or_404(db: Session, model, id_: int, label: str):
    row = db.get(model, id_)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} {id_} not found")
    return row


# ---------------------------------------------------------------------------
# Brands & lines
# ---------------------------------------------------------------------------

@router.get("/brands", response_model=list[BrandRead])
def list_brands(db: Session = Depends(get_db)):
    return (
        db.query(PaintBrand)
        .options(joinedload(PaintBrand.lines))
        .order_by(PaintBrand.name)
        .all()
    )


@router.post("/brands", response_model=BrandRead, status_code=201)
def create_brand(body: BrandCreate, db: Session = Depends(get_db)):
    name = body.name.strip()
    existing = db.query(PaintBrand).filter(PaintBrand.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Brand '{existing.name}' already exists")
    brand = PaintBrand(name=name)
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand


@router.post("/lines", response_model=PaintLineRead, status_code=201)
def create_line(body: PaintLineCreate, db: Session = Depends(get_db)):
    _get_or_404(db, PaintBrand, body.brand_id, "Brand")
    name = body.name.strip()
    dup = (
        db.query(PaintLine)
        .filter(PaintLine.brand_id == body.brand_id, PaintLine.name.ilike(name))
        .first()
    )
    if dup:
        raise HTTPException(status_code=409, detail=f"Line '{dup.name}' already exists for this brand")
    line = PaintLine(brand_id=body.brand_id, name=name, code_pattern=body.code_pattern)
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


@router.patch("/lines/{line_id}", response_model=PaintLineRead)
def update_line(line_id: int, body: PaintLineUpdate, db: Session = Depends(get_db)):
    line = _get_or_404(db, PaintLine, line_id, "Line")
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is None:
        updates.pop("name")  # name is non-nullable; null = leave unchanged
    for key, value in updates.items():
        setattr(line, key, value)
    db.commit()
    db.refresh(line)
    return line


# ---------------------------------------------------------------------------
# Paints
# ---------------------------------------------------------------------------

@router.get("/paints", response_model=PaintList)
def list_paints(
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=500),
    q: str = Query(""),
    line_id: int | None = None,
    brand_id: int | None = None,
    finish: str | None = None,
    owned: bool | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Paint)
    if q:
        like = f"%{q}%"
        query = query.filter(Paint.name.ilike(like) | Paint.code.ilike(like))
    if line_id is not None:
        query = query.filter(Paint.paint_line_id == line_id)
    if brand_id is not None:
        query = query.join(PaintLine).filter(PaintLine.brand_id == brand_id)
    if finish is not None:
        query = query.filter(Paint.finish == finish)
    if owned is not None:
        query = query.filter(Paint.owned == owned)

    total = query.count()
    items = (
        query.order_by(Paint.name, Paint.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/paints/{paint_id}", response_model=PaintRead)
def get_paint(paint_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Paint, paint_id, "Paint")


@router.post("/paints", response_model=PaintRead, status_code=201)
def create_paint(body: PaintCreate, db: Session = Depends(get_db)):
    _get_or_404(db, PaintLine, body.paint_line_id, "Line")
    dup = (
        db.query(Paint)
        .filter(Paint.paint_line_id == body.paint_line_id, Paint.code == body.code)
        .first()
    )
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"Paint code '{body.code}' already exists in this line ({dup.name})",
        )
    paint = Paint(**body.model_dump(), matchable=derive_matchable(body.finish))
    db.add(paint)
    db.commit()
    db.refresh(paint)
    return paint


@router.patch("/paints/{paint_id}", response_model=PaintRead)
def update_paint(paint_id: int, body: PaintUpdate, db: Session = Depends(get_db)):
    paint = _get_or_404(db, Paint, paint_id, "Paint")
    updates = body.model_dump(exclude_unset=True)
    # Non-nullable columns: an explicit null means "leave unchanged".
    for key in list(updates):
        if updates[key] is None and key not in _NULLABLE_PAINT_FIELDS:
            updates.pop(key)
    if "paint_line_id" in updates:
        _get_or_404(db, PaintLine, updates["paint_line_id"], "Line")
    for key, value in updates.items():
        setattr(paint, key, value)
    if "finish" in updates:
        paint.matchable = derive_matchable(paint.finish)
    db.commit()
    db.refresh(paint)
    return paint


@router.delete("/paints/{paint_id}")
def delete_paint(paint_id: int, db: Session = Depends(get_db)):
    paint = _get_or_404(db, Paint, paint_id, "Paint")
    # Guides reference paints by FK; deleting one out from under a guide
    # would orphan its swatches/mixes (spec §8.4 validates paint.exists).
    from app.painting.models import GuideMixComponent, GuideSwatch

    referenced = (
        db.query(GuideSwatch).filter(GuideSwatch.paint_id == paint_id).first()
        or db.query(GuideMixComponent).filter(GuideMixComponent.paint_id == paint_id).first()
    )
    if referenced:
        raise HTTPException(
            status_code=409,
            detail="Paint is used by a guide — mark it owned=false instead of deleting",
        )
    db.delete(paint)
    db.commit()
    return {"ok": True}

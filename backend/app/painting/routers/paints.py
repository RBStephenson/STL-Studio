"""Paint Shelf (inventory) endpoints — brands, lines, and paints (M1, #240).

`matchable` is always derived from `finish` server-side (spec §8.6); the
create/update schemas don't expose it. Paint codes are validated against the
owning line's `code_pattern` on create/update (#244, spec §6.2).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.painting.models import Paint, PaintBrand, PaintLine
from app.painting.schemas import (
    BrandCreate, BrandRead,
    ForcedPaintCreate,
    PaintLineCreate, PaintLineRead, PaintLineUpdate,
    PaintCreate, PaintList, PaintRead, PaintUpdate,
    derive_matchable,
)

# Synthetic shelf location for paints force-added during guide import (#417).
_IMPORTED_BRAND = "Imported"
_IMPORTED_LINE = "Uncategorized"
from app.painting.services.validation import validate_code, validate_pattern

router = APIRouter()

# Fields where an explicit JSON null is a valid "clear this" request; the
# rest are non-nullable columns, so null means "leave unchanged" and is dropped.
_NULLABLE_PAINT_FIELDS = {"hex", "value_pct", "notes", "source", "size"}


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
    if (error := validate_pattern(body.code_pattern)) is not None:
        raise HTTPException(status_code=422, detail=error)
    line = PaintLine(brand_id=body.brand_id, name=name, code_pattern=body.code_pattern)
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def _get_or_create_imported_line(db: Session) -> PaintLine:
    """The synthetic 'Imported / Uncategorized' line that force-added paints land
    in (#417). Created on first use; no code pattern so any code is accepted."""
    brand = db.query(PaintBrand).filter(PaintBrand.name == _IMPORTED_BRAND).first()
    if brand is None:
        brand = PaintBrand(name=_IMPORTED_BRAND)
        db.add(brand)
        db.flush()
    line = (
        db.query(PaintLine)
        .filter(PaintLine.brand_id == brand.id, PaintLine.name == _IMPORTED_LINE)
        .first()
    )
    if line is None:
        line = PaintLine(brand_id=brand.id, name=_IMPORTED_LINE, code_pattern=None)
        db.add(line)
        db.flush()
    return line


@router.patch("/lines/{line_id}", response_model=PaintLineRead)
def update_line(line_id: int, body: PaintLineUpdate, db: Session = Depends(get_db)):
    line = _get_or_404(db, PaintLine, line_id, "Line")
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is None:
        updates.pop("name")  # name is non-nullable; null = leave unchanged
    if (error := validate_pattern(updates.get("code_pattern"))) is not None:
        raise HTTPException(status_code=422, detail=error)
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
    line = _get_or_404(db, PaintLine, body.paint_line_id, "Line")
    if (error := validate_code(body.code, line.code_pattern)) is not None:
        raise HTTPException(status_code=422, detail=error)
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


@router.post("/paints/import-forced", response_model=PaintRead, status_code=201)
def force_add_paint(body: ForcedPaintCreate, db: Session = Depends(get_db)):
    """Force-add a paint encountered during guide import that isn't on the shelf
    (#417). Lands in the synthetic 'Imported / Uncategorized' line as
    known-but-not-owned. Idempotent by name within that line — re-forcing the
    same paint returns the existing row rather than duplicating it."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Paint name is required")
    line = _get_or_create_imported_line(db)
    existing = (
        db.query(Paint)
        .filter(Paint.paint_line_id == line.id, Paint.name.ilike(name))
        .first()
    )
    if existing is not None:
        return existing
    paint = Paint(
        paint_line_id=line.id,
        code=name,
        name=name,
        hex=body.hex,
        finish="matte",
        matchable=derive_matchable("matte"),
        owned=False,
    )
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
    # Validate the effective code against the effective line whenever either
    # changes; an unrelated PATCH never re-validates (no retroactive lockout
    # when a pattern is added to a line with existing paints).
    if "code" in updates or "paint_line_id" in updates:
        line = _get_or_404(
            db, PaintLine, updates.get("paint_line_id", paint.paint_line_id), "Line"
        )
        code = updates.get("code", paint.code)
        if (error := validate_code(code, line.code_pattern)) is not None:
            raise HTTPException(status_code=422, detail=error)
        # Editing a code or moving the paint to another line must not collide
        # with an existing (line, code) identity — the create path already
        # guards this; the update path didn't (#445).
        conflict = (
            db.query(Paint)
            .filter(
                Paint.paint_line_id == line.id,
                Paint.code == code,
                Paint.id != paint.id,
            )
            .first()
        )
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Paint code '{code}' already exists in this line ({conflict.name})",
            )
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

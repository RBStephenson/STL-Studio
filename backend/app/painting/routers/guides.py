"""Guide CRUD endpoints (M2, #258).

The relational Tab -> Phase -> Step -> Swatch/MixComponent spine plus the
JSON display blocks (spec §6.2-6.5). Whole-guide upsert: POST takes the full
nested tree; PATCH updates header/JSON fields and, when `tabs` is supplied,
replaces the entire content spine. The renderer (#259), exporter (#260),
importer (#261), and model-link UI (#263) build on these.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Model
from app.painting.models import (
    Guide, GuideCategory, GuideReferenceImage, GuideSeries,
)
from app.painting.schemas import (
    CategoryCreate, CategoryRead,
    GuideCreate, GuideList, GuideListItem, GuideRead, GuideUpdate,
    SeriesCreate, SeriesRead,
)
from app.painting.services.guides import build_tabs, collect_paint_ids, missing_paint_ids
from app.utils import utcnow

router = APIRouter()

# Guide-header fields that are nullable columns: an explicit JSON null clears
# them. Everything else with None means "leave unchanged" on PATCH.
_NULLABLE_GUIDE_FIELDS = {
    "category_id", "series_id", "model_id", "scale", "franchise",
    "reference_image_id", "light_source", "philosophy_note",
    "creator_credit", "character_brief", "theme", "thinning_config",
}
# JSON-block fields that arrive as Pydantic models and must be stored as dicts.
_BLOCK_FIELDS = {"creator_credit", "character_brief", "theme", "thinning_config"}


def _get_or_404(db: Session, model, id_: int, label: str):
    row = db.get(model, id_)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} {id_} not found")
    return row


def _validate_refs(db: Session, *, category_id, series_id, model_id, reference_image_id):
    """FK existence checks for the optional guide references (422 if dangling)."""
    if category_id is not None and db.get(GuideCategory, category_id) is None:
        raise HTTPException(status_code=422, detail=f"Category {category_id} not found")
    if series_id is not None and db.get(GuideSeries, series_id) is None:
        raise HTTPException(status_code=422, detail=f"Series {series_id} not found")
    if model_id is not None and db.get(Model, model_id) is None:
        raise HTTPException(status_code=422, detail=f"Model {model_id} not found")
    if reference_image_id is not None and db.get(GuideReferenceImage, reference_image_id) is None:
        raise HTTPException(
            status_code=422, detail=f"Reference image {reference_image_id} not found"
        )


def _validate_paints(db: Session, tabs_in):
    missing = missing_paint_ids(db, collect_paint_ids(tabs_in))
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Swatch/mix references unknown paint id(s): {missing}",
        )


def _slug_conflict(db: Session, slug: str, *, exclude_id: int | None = None):
    q = db.query(Guide).filter(Guide.slug == slug)
    if exclude_id is not None:
        q = q.filter(Guide.id != exclude_id)
    return q.first()


# ---------------------------------------------------------------------------
# Categories & series (guides reference these; importer #261 seeds them)
# ---------------------------------------------------------------------------

@router.get("/categories", response_model=list[CategoryRead])
def list_categories(db: Session = Depends(get_db)):
    cats = db.query(GuideCategory).order_by(
        GuideCategory.sort_order, GuideCategory.display_name
    ).all()
    counts = dict(
        db.query(Guide.category_id, func.count(Guide.id))
        .group_by(Guide.category_id)
        .all()
    )
    out = []
    for c in cats:
        item = CategoryRead.model_validate(c)
        item.guide_count = counts.get(c.id, 0)
        out.append(item)
    return out


@router.post("/categories", response_model=CategoryRead, status_code=201)
def create_category(body: CategoryCreate, db: Session = Depends(get_db)):
    if db.query(GuideCategory).filter(GuideCategory.slug == body.slug).first():
        raise HTTPException(status_code=409, detail=f"Category '{body.slug}' already exists")
    cat = GuideCategory(**body.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.get("/series", response_model=list[SeriesRead])
def list_series(db: Session = Depends(get_db)):
    return db.query(GuideSeries).order_by(GuideSeries.display_name).all()


@router.post("/series", response_model=SeriesRead, status_code=201)
def create_series(body: SeriesCreate, db: Session = Depends(get_db)):
    if db.query(GuideSeries).filter(GuideSeries.slug == body.slug).first():
        raise HTTPException(status_code=409, detail=f"Series '{body.slug}' already exists")
    series = GuideSeries(**body.model_dump())
    db.add(series)
    db.commit()
    db.refresh(series)
    return series


# ---------------------------------------------------------------------------
# Guides
# ---------------------------------------------------------------------------

@router.get("/guides", response_model=GuideList)
def list_guides(
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=500),
    q: str = Query(""),
    status: str | None = None,
    scale: str | None = None,
    category_id: int | None = None,
    series_id: int | None = None,
    model_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Guide)
    if q:
        query = query.filter(Guide.title.ilike(f"%{q}%"))
    if status is not None:
        query = query.filter(Guide.status == status)
    if scale is not None:
        query = query.filter(Guide.scale == scale)
    if category_id is not None:
        query = query.filter(Guide.category_id == category_id)
    if series_id is not None:
        query = query.filter(Guide.series_id == series_id)
    if model_id is not None:
        query = query.filter(Guide.model_id == model_id)

    total = query.count()
    items = (
        query.order_by(Guide.title, Guide.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [GuideListItem.model_validate(g) for g in items],
    }


@router.get("/guides/{guide_id}", response_model=GuideRead)
def get_guide(guide_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Guide, guide_id, "Guide")


@router.post("/guides", response_model=GuideRead, status_code=201)
def create_guide(body: GuideCreate, db: Session = Depends(get_db)):
    if _slug_conflict(db, body.slug):
        raise HTTPException(status_code=409, detail=f"Guide slug '{body.slug}' already exists")
    _validate_refs(
        db, category_id=body.category_id, series_id=body.series_id,
        model_id=body.model_id, reference_image_id=body.reference_image_id,
    )
    _validate_paints(db, body.tabs)

    guide = Guide(
        slug=body.slug,
        title=body.title,
        category_id=body.category_id,
        series_id=body.series_id,
        model_id=body.model_id,
        scale=body.scale,
        status=body.status,
        franchise=body.franchise,
        creator_credit=body.creator_credit.model_dump() if body.creator_credit else None,
        reference_image_id=body.reference_image_id,
        light_source=body.light_source,
        philosophy_note=body.philosophy_note,
        paint_lines_used=body.paint_lines_used,
        technique_tags=body.technique_tags,
        character_brief=body.character_brief.model_dump() if body.character_brief else None,
        theme=body.theme.model_dump() if body.theme else None,
        thinning_config=body.thinning_config.model_dump() if body.thinning_config else None,
        tabs=build_tabs(body.tabs),
    )
    if body.status == "published":
        guide.published_at = utcnow()
    db.add(guide)
    db.commit()
    db.refresh(guide)
    return guide


@router.patch("/guides/{guide_id}", response_model=GuideRead)
def update_guide(guide_id: int, body: GuideUpdate, db: Session = Depends(get_db)):
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    updates = body.model_dump(exclude_unset=True)

    # Replace the content spine only when tabs is explicitly supplied.
    tabs_supplied = "tabs" in updates
    tabs_in = body.tabs if tabs_supplied else None
    updates.pop("tabs", None)

    if "slug" in updates:
        if updates["slug"] is None:
            updates.pop("slug")  # non-nullable; null = leave unchanged
        elif _slug_conflict(db, updates["slug"], exclude_id=guide.id):
            raise HTTPException(status_code=409, detail=f"Guide slug '{updates['slug']}' already exists")
    if "title" in updates and updates["title"] is None:
        updates.pop("title")

    _validate_refs(
        db,
        category_id=updates.get("category_id"),
        series_id=updates.get("series_id"),
        model_id=updates.get("model_id"),
        reference_image_id=updates.get("reference_image_id"),
    )
    if tabs_in is not None:
        _validate_paints(db, tabs_in)

    # Drop nulls for non-nullable header fields; keep them for nullable ones.
    for key in list(updates):
        if updates[key] is None and key not in _NULLABLE_GUIDE_FIELDS:
            updates.pop(key)

    becoming_published = updates.get("status") == "published" and guide.status != "published"

    for key, value in updates.items():
        # Block fields were dumped to dicts by model_dump() already.
        setattr(guide, key, value)

    if tabs_in is not None:
        guide.tabs = build_tabs(tabs_in)   # delete-orphan clears the old subtree
    if becoming_published and guide.published_at is None:
        guide.published_at = utcnow()

    db.commit()
    db.refresh(guide)
    return guide


@router.delete("/guides/{guide_id}")
def delete_guide(guide_id: int, db: Session = Depends(get_db)):
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    db.delete(guide)   # cascade clears tabs/phases/steps/swatches/mix
    db.commit()
    return {"ok": True}

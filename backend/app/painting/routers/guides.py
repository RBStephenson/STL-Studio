"""Guide CRUD endpoints (M2, #258).

The relational Tab -> Phase -> Step -> Swatch/MixComponent spine plus the
JSON display blocks (spec §6.2-6.5). Whole-guide upsert: POST takes the full
nested tree; PATCH updates header/JSON fields and, when `tabs` is supplied,
replaces the entire content spine. The renderer (#259), exporter (#260),
importer (#261), and model-link UI (#263) build on these.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Model
from app.painting.models import (
    Guide, GuideCategory, GuideReferenceImage, GuideSeries,
)
from app.painting.schemas import (
    CategoryCreate, CategoryRead,
    GuideCreate, GuideImportRequest, GuideImportResult, GuideList, GuideListItem,
    GuideRead, GuideUpdate, SeriesCreate, SeriesRead,
)
from app.painting.services.guides import build_tabs, collect_paint_ids, missing_paint_ids
from app.painting.services.importing import import_guide_html, make_db_resolver, with_overrides
from app.painting.services.pdf import ChromiumNotInstalledError, render_guide_pdf
from app.painting.services.rendering import attach_resolved_paints, render_guide_html
from app.utils import utcnow

router = APIRouter()

# Guide-header fields that are nullable columns: an explicit JSON null clears
# them. Everything else with None means "leave unchanged" on PATCH.
_NULLABLE_GUIDE_FIELDS = {
    "category_id", "series_id", "model_id", "scale", "franchise",
    "reference_image_id", "light_source", "philosophy_note",
    "creator_credit", "character_brief", "theme", "thinning_config",
    "title_lead", "subtitle", "category_label", "quote", "head_style",
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


@router.get("/guides/model-ids")
def guide_model_ids(db: Session = Depends(get_db)):
    """The distinct model ids that have at least one guide — drives the Library
    'has guide' badge (#263) without coupling the core models endpoint to the
    painting module. Declared before /guides/{guide_id} so it isn't shadowed."""
    rows = db.query(Guide.model_id).filter(Guide.model_id.isnot(None)).distinct().all()
    return {"model_ids": [r[0] for r in rows]}


@router.get("/guides/{guide_id}", response_model=GuideRead)
def get_guide(guide_id: int, db: Session = Depends(get_db)):
    return attach_resolved_paints(db, _get_or_404(db, Guide, guide_id, "Guide"))


@router.get("/guides/{guide_id}/export", response_class=Response)
def export_guide_html(guide_id: int, db: Session = Depends(get_db)):
    """Serialize a guide to the legacy self-contained HTML file (spec §9.5).

    The download target for the importer's round-trip golden test (#261)."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    html = render_guide_html(db, guide)
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{guide.slug}.html"'},
    )


@router.get("/guides/{guide_id}/export/pdf", response_class=Response)
async def export_guide_pdf(guide_id: int, db: Session = Depends(get_db)):
    """Render a guide to a print-ready PDF via headless Chromium (spec §9.4).

    Reuses the static-HTML export with assets inlined and print media emulated,
    so the PDF matches the in-browser print view. Single-guide only."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    try:
        pdf = await render_guide_pdf(db, guide)
    except ChromiumNotInstalledError:
        raise HTTPException(
            status_code=503,
            detail=(
                "PDF rendering needs Chromium, which isn't installed. "
                "Run `playwright install chromium` and try again."
            ),
        )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{guide.slug}.pdf"'},
    )


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
        title_lead=body.title_lead,
        subtitle=body.subtitle,
        category_id=body.category_id,
        category_label=body.category_label,
        series_id=body.series_id,
        model_id=body.model_id,
        scale=body.scale,
        status=body.status,
        franchise=body.franchise,
        quote=body.quote,
        creator_credit=body.creator_credit.model_dump() if body.creator_credit else None,
        reference_image_id=body.reference_image_id,
        light_source=body.light_source,
        philosophy_note=body.philosophy_note,
        paint_lines_used=[p.model_dump() for p in body.paint_lines_used],
        technique_tags=body.technique_tags,
        character_brief=body.character_brief.model_dump() if body.character_brief else None,
        theme=body.theme.model_dump() if body.theme else None,
        head_style=body.head_style,
        thinning_config=body.thinning_config.model_dump() if body.thinning_config else None,
        tabs=build_tabs(body.tabs),
    )
    if body.status == "published":
        guide.published_at = utcnow()
    db.add(guide)
    db.commit()
    db.refresh(guide)
    return attach_resolved_paints(db, guide)


@router.post("/guides/import", response_model=GuideImportResult, status_code=201)
def import_guide(body: GuideImportRequest, db: Session = Depends(get_db)):
    """Parse a legacy guide HTML file into a draft guide + import report (#261).

    Resolves swatch paints against the Paint Shelf; unresolved ones are dropped
    from the draft and listed in the report (the inventory-gap list, §9.7).
    Lands as draft for human review — never auto-published.

    `dry_run` parses + reports without persisting so the UI can resolve
    unresolved paints first; `paint_overrides` then maps those names to chosen
    shelf paints on the committing call (#417)."""
    overrides = {o.name: o.paint_id for o in body.paint_overrides}
    resolver = with_overrides(make_db_resolver(db), overrides)
    draft, report = import_guide_html(body.html, slug=body.slug, resolve_paint=resolver)
    if body.dry_run:
        return {"guide": None, "report": report.as_dict()}
    guide = create_guide(GuideCreate.model_validate(draft), db)
    return {"guide": guide, "report": report.as_dict()}


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
    return attach_resolved_paints(db, guide)


@router.delete("/guides/{guide_id}")
def delete_guide(guide_id: int, db: Session = Depends(get_db)):
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    db.delete(guide)   # cascade clears tabs/phases/steps/swatches/mix
    db.commit()
    return {"ok": True}

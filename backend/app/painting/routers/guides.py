"""Guide CRUD endpoints (M2, #258).

The relational Tab -> Phase -> Step -> Swatch/MixComponent spine plus the
JSON display blocks (spec §6.2-6.5). Whole-guide upsert: POST takes the full
nested tree; PATCH updates header/JSON fields and, when `tabs` is supplied,
replaces the entire content spine. The renderer (#259), exporter (#260),
importer (#261), and model-link UI (#263) build on these.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AppSetting, Model
from app.painting.models import (
    Guide, GuideCategory, GuideReferenceImage, GuideSeries,
)
from app.painting.schemas import (
    CategoryCreate, CategoryRead,
    GuideCreate, GuideImportRequest, GuideImportResult, GuideList, GuideListItem,
    GuideRead, GuideUpdate, GuideValidationResult,
    ReferenceCandidateList, ReferenceFromModel, ReferenceImageRead,
    SeriesCreate, SeriesRead,
)
from app.painting.services import images
from app.painting.services.guides import build_tabs, collect_paint_ids, missing_paint_ids
from app.painting.services.importing import import_guide_html, make_db_resolver, with_overrides
from app.painting.services.pdf import (
    ChromiumNotInstalledError,
    EmptySeriesError,
    StampConfig,
    render_guide_pdf,
    render_series_pdf,
)
from app.painting.services.rendering import attach_resolved_paints, render_guide_html
from app.painting.services.validation import validate_guide
from app.painting.services import draft_jobs, generation
from app.utils import utcnow

router = APIRouter()

# Guide-header fields that are nullable columns: an explicit JSON null clears
# them. Everything else with None means "leave unchanged" on PATCH.
_NULLABLE_GUIDE_FIELDS = {
    "category_id", "series_id", "model_id", "scale", "franchise",
    "reference_image_id", "light_source", "philosophy_note",
    "creator_credit", "character_brief", "theme", "thinning_config",
    "title_lead", "subtitle", "category_label", "quote", "head_style",
    "series_badge",
}
# JSON-block fields that arrive as Pydantic models and must be stored as dicts.
_BLOCK_FIELDS = {"creator_credit", "character_brief", "theme", "thinning_config"}


def _get_or_404(db: Session, model, id_: int, label: str):
    row = db.get(model, id_)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} {id_} not found")
    return row


_GUIDE_THEME_DEFAULTS_KEY = "guide_theme_defaults"


def _default_guide_theme(db: Session) -> dict | None:
    """The app-level default guide theme (#514), or None when none is configured.

    New guides that don't carry their own theme inherit this. An all-None stored
    theme counts as "not configured" so behaviour matches the corpus default.
    """
    row = db.get(AppSetting, _GUIDE_THEME_DEFAULTS_KEY)
    if row is None or not isinstance(row.value, dict):
        return None
    if not any(v is not None for v in row.value.values()):
        return None
    return row.value


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


@router.get("/guides/{guide_id}/validation", response_model=GuideValidationResult)
def get_guide_validation(
    guide_id: int,
    strict: bool = True,
    db: Session = Depends(get_db),
):
    """Validator findings for the editor panel (#489, spec §8.4). `ok` is False
    when any block-severity flag remains — the same gate publish enforces.

    Pass `?strict=false` to suppress authoring-quality checks
    (`value_intent_missing`, `value_compression`) that are noise for imported
    guides lacking those metadata fields."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    flags = validate_guide(db, guide, strict=strict)
    return GuideValidationResult(ok=not any(f.severity == "block" for f in flags), flags=flags)


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


_CHROMIUM_MISSING_DETAIL = (
    "PDF rendering needs Chromium, which isn't installed. "
    "Run `playwright install chromium` and try again."
)


def _stamp_from_query(footer: bool, tier: str | None, watermark: bool) -> StampConfig:
    """Build per-export reward stamping from query params (spec §4.6, Q5)."""
    return StampConfig(footer=footer, tier_label=tier, watermark=watermark)


@router.get("/guides/{guide_id}/export/pdf", response_class=Response)
async def export_guide_pdf(
    guide_id: int,
    db: Session = Depends(get_db),
    footer: bool = Query(True, description="Patreon-exclusive footer (on by default)"),
    tier: str | None = Query(None, description="Optional tier label for the footer"),
    watermark: bool = Query(False, description="Diagonal watermark (off by default)"),
):
    """Render a guide to a print-ready PDF via headless Chromium (spec §9.4).

    Reuses the static-HTML export with assets inlined and print media emulated,
    so the PDF matches the in-browser print view. Single-guide only."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    try:
        pdf = await render_guide_pdf(db, guide, _stamp_from_query(footer, tier, watermark))
    except ChromiumNotInstalledError:
        raise HTTPException(status_code=503, detail=_CHROMIUM_MISSING_DETAIL)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{guide.slug}.pdf"'},
    )


@router.get("/series/{series_id}/export/pdf", response_class=Response)
async def export_series_pdf(
    series_id: int,
    db: Session = Depends(get_db),
    cover: bool = Query(True, description="Prepend a cover page (spec Q4)"),
    footer: bool = Query(True, description="Patreon-exclusive footer (on by default)"),
    tier: str | None = Query(None, description="Optional tier label for the footer"),
    watermark: bool = Query(False, description="Diagonal watermark (off by default)"),
):
    """Render a series of published guides into one bundled PDF (spec §9.4).

    Optional cover page; per-export reward stamping. 404 when the series doesn't
    exist or has no published guides to bundle."""
    series = _get_or_404(db, GuideSeries, series_id, "Series")
    try:
        pdf = await render_series_pdf(
            db,
            series,
            _stamp_from_query(footer, tier, watermark),
            cover=cover,
        )
    except EmptySeriesError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ChromiumNotInstalledError:
        raise HTTPException(status_code=503, detail=_CHROMIUM_MISSING_DETAIL)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{series.slug}-bundle.pdf"'},
    )


@router.post("/guides/{guide_id}/draft", status_code=202)
def start_guide_draft(guide_id: int, db: Session = Depends(get_db)):
    """Kick off async AI draft generation for a guide (#524, spec §8.3).

    Returns 202 + the initial job status; poll the status endpoint. 503 when AI
    Guide Drafts isn't enabled/configured, 409 when a draft is already
    generating for this guide. The result is always a draft — generation never
    publishes."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    try:
        generation.load_guides_config(db)
    except generation.MissingApiKeyError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if not draft_jobs.start_generation(guide.id):
        raise HTTPException(
            status_code=409, detail="A draft is already generating for this guide."
        )
    return draft_jobs.get_status(guide.id)


@router.get("/guides/{guide_id}/draft/status")
def guide_draft_status(guide_id: int, db: Session = Depends(get_db)):
    """Poll the draft-generation job status for a guide (#524)."""
    _get_or_404(db, Guide, guide_id, "Guide")
    return draft_jobs.get_status(guide_id)


# ---------------------------------------------------------------------------
# Reference image (#535, spec §8.5): user upload + Claude-vision source. The
# fallback chain (STL-folder / web search / AI-gen) is #494.
# ---------------------------------------------------------------------------

@router.post(
    "/guides/{guide_id}/reference-image",
    response_model=ReferenceImageRead,
    status_code=201,
)
async def upload_reference_image(
    guide_id: int,
    file: UploadFile = File(...),
    alt_text: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Attach a reference image to a guide (replaces any existing one).

    Stored on the local data volume; the bytes feed Claude vision at draft time
    and the GET endpoint serves them for preview. 422 on a bad/oversize file."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    raw = await file.read()
    try:
        row = images.store_upload(db, guide, raw, alt_text=alt_text)
    except images.ReferenceImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    db.refresh(row)
    return row


@router.get(
    "/guides/{guide_id}/reference-image/candidates",
    response_model=ReferenceCandidateList,
)
def list_reference_candidates(guide_id: int, db: Session = Depends(get_db)):
    """Reference-image candidates from the guide's linked STL model (#494 rung 0).

    Paths are served for preview via the existing /files/image endpoint.
    Empty list when there's no linked model or no indexed folder images."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    return ReferenceCandidateList(candidates=images.list_model_candidates(db, guide))


@router.post(
    "/guides/{guide_id}/reference-image/from-model",
    response_model=ReferenceImageRead,
    status_code=201,
)
def reference_from_model(
    guide_id: int, body: ReferenceFromModel, db: Session = Depends(get_db)
):
    """Adopt one of the linked model's folder images as the reference (#494 rung 0).

    `index` refers to the candidates list from the GET endpoint."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    try:
        row = images.store_from_model(db, guide, body.index, alt_text=body.alt_text)
    except images.ReferenceImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    db.refresh(row)
    return row


@router.get("/guides/{guide_id}/reference-image", response_class=Response)
def get_reference_image(guide_id: int, db: Session = Depends(get_db)):
    """Serve the guide's reference-image bytes for preview. 404 when none set."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    loaded = images.load_reference(db, guide)
    if loaded is None:
        raise HTTPException(status_code=404, detail="Guide has no reference image")
    raw, media_type = loaded
    return Response(content=raw, media_type=media_type,
                    headers={"Cache-Control": "no-cache"})


@router.delete("/guides/{guide_id}/reference-image", status_code=200)
def delete_reference_image(guide_id: int, db: Session = Depends(get_db)):
    """Clear the guide's reference image (FK + row + file). Idempotent."""
    guide = _get_or_404(db, Guide, guide_id, "Guide")
    images.clear_reference(db, guide)
    db.commit()
    return {"ok": True}


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
        theme=body.theme.model_dump() if body.theme else _default_guide_theme(db),
        head_style=body.head_style,
        series_badge=[c.model_dump() for c in body.series_badge] if body.series_badge else None,
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
    overrides = [(o.name, o.brand, o.paint_id) for o in body.paint_overrides]
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

    # Publish gate (#489, spec §8.4): a guide can't go published while any
    # block-severity validation flag remains. Validates the post-update content.
    if becoming_published:
        blocking = [f for f in validate_guide(db, guide) if f.severity == "block"]
        if blocking:
            db.rollback()
            raise HTTPException(status_code=422, detail={
                "message": "Resolve blocking validation issues before publishing.",
                "flags": [f.model_dump() for f in blocking],
            })

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

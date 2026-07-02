import logging
import os
import shutil
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, exists, select, case, cast, String
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Model, Creator, ModelTag, CollectionModel, ScanRoot, STLFile, VariantGroup, GroupingStrategy
from app.schemas import (
    ModelList, ModelRead, ModelDetail, CreatorRead,
    ModelUpdate, ThumbnailUpdate, ThumbnailFromUrl, BatchThumbnailFromUrl, FavoriteUpdate, RatingUpdate, QueueReorder, GroupReorder,
    PrintStatusUpdate, ExcludeUpdate, STLFileUpdate, BulkTagUpdate,
    BulkExcludeUpdate, BulkReviewUpdate, BulkEnrichUpdate,
    BatchSetSourceUrl, GroupRepUpdate, BulkDeleteRequest, BulkDeleteResponse,
    GroupMergeBody, GroupSplitBody, GroupPatchBody, VariantGroupRead, GroupingStrategyBody,
    AiOrganizeResult, AiOrganizeSuggestion,
)

_log = logging.getLogger(__name__)
from app.services.thumbnails import ThumbnailDownloadError, download_thumbnail, fetch_image_bytes, store_thumbnail
from app.services.variant_sync import propagate_source_url
from app.services.scrapers.base import detect_site
from urllib.parse import urlparse
from app.services.tag_sync import sync_model_tags, bulk_sync_model_tags
from app.services import scanner, grouping, ai_organize
from app.services.scanner import resolve_creator
from app.config import settings
from app.utils import utcnow

router = APIRouter(prefix="/models", tags=["models"])


def _apply_filters(
    q,
    *,
    search: str = "",
    creator_id: int | None = None,
    exclude_creator_id: int | None = None,
    source_site: str | None = None,
    tag: str | None = None,
    exclude_tag: str | None = None,
    has_thumbnail: bool | None = None,
    needs_review: bool | None = None,
    is_inbox: bool | None = None,
    nsfw: bool | None = None,
    is_favorite: bool | None = None,
    print_status: str | None = None,
    exclude_printed: bool = False,
    min_rating: int | None = None,
    excluded: bool = False,
    added_within_days: int | None = None,
    support_status: str | None = None,
    slicer: str | None = None,
):
    """Apply standard Library filters to a Model query. Does not handle sort, page, or character."""
    q = q.filter(Model.excluded == excluded)
    if search:
        like = f"%{search}%"
        q = q.filter(
            Model.title.ilike(like)
            | Model.name.ilike(like)
            | Model.description.ilike(like)
            | Model.character.ilike(like)
        )
    if creator_id:
        q = q.filter(Model.creator_id == creator_id)
    if exclude_creator_id:
        # Keep NULL-creator models visible: SQL `!=` silently drops NULL rows.
        q = q.filter((Model.creator_id != exclude_creator_id) | (Model.creator_id == None))
    if source_site:
        q = q.filter(Model.source_site == source_site)
    if tag:
        tag_norm = tag.strip().lower()
        q = q.filter(
            exists().where(
                (ModelTag.model_id == Model.id) & (ModelTag.tag == tag_norm)
            )
        )
    if exclude_tag:
        excl_norm = exclude_tag.strip().lower()
        q = q.filter(
            ~exists().where(
                (ModelTag.model_id == Model.id) & (ModelTag.tag == excl_norm)
            )
        )
    if has_thumbnail is True:
        q = q.filter((Model.thumbnail_path != None) | (Model.thumbnail_url != None))
    if has_thumbnail is False:
        q = q.filter((Model.thumbnail_path == None) & (Model.thumbnail_url == None))
    if needs_review is not None:
        q = q.filter(Model.needs_review == needs_review)
    if is_inbox is not None:
        q = q.filter(Model.is_inbox == is_inbox)
    if nsfw is not None:
        q = q.filter(Model.nsfw == nsfw)
    if is_favorite is not None:
        q = q.filter(Model.is_favorite == is_favorite)
    if print_status is not None:
        q = q.filter(Model.print_status == print_status)
    if exclude_printed:
        # Hide already-printed models. NULL print_status stays visible (mirrors
        # the exclude_creator pattern: SQL `!=` silently drops NULL rows).
        q = q.filter((Model.print_status != "printed") | (Model.print_status == None))
    if min_rating is not None:
        q = q.filter(Model.user_rating != None, Model.user_rating >= min_rating)
    if added_within_days is not None:
        q = q.filter(Model.created_at >= utcnow() - timedelta(days=added_within_days))
    # Scanner-detected variant attributes live in the parsed_attributes JSON blob.
    # json_extract returns the scalar value (or NULL when the key is absent).
    if support_status:
        q = q.filter(
            func.json_extract(Model.parsed_attributes, "$.support_status") == support_status
        )
    if slicer:
        q = q.filter(
            func.json_extract(Model.parsed_attributes, "$.slicer") == slicer
        )
    return q


def _clear_queue_state(model) -> None:
    """Drop a model out of the active print queue without touching print history.

    A queued/printing model reverts to 'none' and loses its queue ordering; a
    printed model keeps its 'printed' status, printed_at and print_count.
    """
    if model.print_status in ("queued", "printing"):
        model.print_status = "none"
    model.queued_at = None
    model.queue_position = None


def _order_cols(sort: str) -> tuple:
    """Return the SQLAlchemy order-by columns for the given sort key."""
    if sort == "queue":
        # Print queue order: favorited (unprinted) models always float to the top,
        # then manual drag order (queue_position), then insertion time as a tiebreak.
        # `is_(None)` sorts False(0) before True(1), so positioned items precede
        # any legacy un-positioned ones.
        return (
            Model.is_favorite.desc(),
            Model.queue_position.is_(None),
            Model.queue_position.asc(),
            Model.queued_at.asc(),
        )
    elif sort == "queued_at":
        return (Model.queued_at.asc(),)
    elif sort == "printed_at":
        return (Model.printed_at.desc(),)
    elif sort == "added":
        # Newest first; id breaks ties within a scan batch (#170).
        return (Model.created_at.desc(), Model.id.desc())
    elif sort == "rating":
        # Highest-rated first; unrated (NULL) sinks to the bottom, then name (#167).
        return (Model.user_rating.is_(None), Model.user_rating.desc(), Model.name)
    else:
        return (Model.character, Model.name)


def _apply_sort(q, sort: str):
    """Order a Model query by the given sort key, handling joins where needed.

    Centralized so list_models and neighbors stay in lockstep (Prev/Next must
    walk the same order the grid shows). `creator` sorts alphabetically by the
    related Creator name — models with no creator sort last — then falls back to
    the default character/name order within a creator. Everything else delegates
    to the column-only `_order_cols`.
    """
    if sort == "creator":
        return q.outerjoin(Creator, Model.creator_id == Creator.id).order_by(
            Creator.name.is_(None), Creator.name, Model.character, Model.name
        )
    return q.order_by(*_order_cols(sort))


# Representative precedence within a variant group, expressed as ORDER BY columns:
# user-flagged rep wins (#193); else manual drag order (#399); else a
# favorited/queued member so its status chips surface on the Library card (#302
# auto-promotion); else a thumbnailed member (#300); else the lowest id.
# `func.row_number()` over this order picks the rep as rn == 1.
def _rep_order():
    has_thumb = (Model.thumbnail_path != None) | (Model.thumbnail_url != None)
    pinned = (Model.is_favorite == True) | (Model.print_status.in_(("queued", "printing")))
    # Manual drag order (#399) outranks the favorited/queued/thumbnail heuristic
    # but not an explicit set-as-thumbnail rep. `variant_order.is_(None)` sorts
    # False(0) before True(1), so manually-ordered members precede un-ordered ones,
    # then by ascending position — making the dragged front model the rep.
    return (
        Model.is_group_rep.desc(),
        Model.variant_order.is_(None),
        Model.variant_order.asc(),
        pinned.desc(),
        has_thumb.desc(),
        Model.id.asc(),
    )


def _group_key_sql():
    """SQL grouping key (#678 Phase 3): the durable variant_group_id, string-encoded
    "vg:<id>". NULL when the model has no group — those rows are always kept
    un-collapsed. `character` is no longer a grouping key (Phases 1-2 migrated
    every live character grouping into a durable VariantGroup)."""
    vg = Model.variant_group_id
    return case((vg.isnot(None), "vg:" + cast(vg, String)), else_=None)


def _group_key_py(m) -> str | None:
    """Python mirror of _group_key_sql for in-memory lookups (must stay in sync)."""
    if m.variant_group_id is not None:
        return f"vg:{m.variant_group_id}"
    return None


def _collapse_variants(q):
    """Collapse a variant group to one representative, entirely in SQL.

    Grouping is keyed solely by the durable variant_group_id (#678 Phase 3) — see
    _group_key_sql. A model is hidden only when it belongs to a group of size > 1
    and is not its representative. The designated rep (variant_groups.rep_model_id)
    wins; otherwise the heuristic _rep_order decides. Ungrouped rows are always kept.
    """
    gkey = _group_key_sql()
    # is_rep_pref: a model that is its group's designated rep sorts first (0).
    is_rep_pref = case((Model.id == VariantGroup.rep_model_id, 0), else_=1)
    sub = (
        q.outerjoin(VariantGroup, Model.variant_group_id == VariantGroup.id)
        .with_entities(
            Model.id.label("id"),
            gkey.label("gk"),
            func.count().over(partition_by=gkey).label("cnt"),
            func.row_number().over(
                partition_by=gkey,
                order_by=(is_rep_pref, *_rep_order()),
            ).label("rn"),
        )
        .subquery()
    )
    keep = select(sub.c.id).where(
        (sub.c.gk == None) | (sub.c.cnt == 1) | (sub.c.rn == 1)
    )
    return q.filter(Model.id.in_(keep))


def _resolve_group_rep(q, model_id: int) -> int:
    """Map a model to its variant group's representative within the filtered set.

    Used by neighbors so Prev/Next on a grouped non-rep still pages from the
    representative card. Returns model_id unchanged when it isn't in the filtered
    set or can't group."""
    row = q.filter(Model.id == model_id).with_entities(Model.variant_group_id).first()
    if row is None or row.variant_group_id is None:
        return model_id
    gq = q.outerjoin(VariantGroup, Model.variant_group_id == VariantGroup.id)
    is_rep_pref = case((Model.id == VariantGroup.rep_model_id, 0), else_=1)
    gq = gq.filter(Model.variant_group_id == row.variant_group_id)
    rep = (
        gq.order_by(is_rep_pref, *_rep_order())
        .with_entities(Model.id)
        .first()
    )
    return rep.id if rep else model_id


@router.get("", response_model=ModelList)
def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=200),
    search: str = Query("", alias="q"),
    creator_id: int | None = None,
    exclude_creator_id: int | None = None,
    character: str | None = None,
    source_site: str | None = None,
    tag: str | None = None,
    exclude_tag: str | None = None,
    has_thumbnail: bool | None = None,
    needs_review: bool | None = None,
    is_inbox: bool = False,  # False = hide inbox (default); True = inbox only
    nsfw: bool | None = None,
    is_favorite: bool | None = None,
    print_status: str | None = None,
    exclude_printed: bool = False,  # hide already-printed models (keeps variant grouping)
    min_rating: int | None = Query(None, ge=1, le=5),
    excluded: bool = False,  # default: hide user-excluded models; pass true for the Excluded view
    added_within_days: int | None = Query(None, ge=1, le=365),  # "Recently added" window (#170)
    support_status: str | None = None,
    slicer: str | None = None,
    sort: str = Query("name"),  # "name" | "added" | "creator" | "rating" | "queue" | "queued_at" | "printed_at"
    group_variants: bool = Query(True),
    db: Session = Depends(get_db),
):
    q = _apply_filters(
        db.query(Model),
        search=search, creator_id=creator_id, exclude_creator_id=exclude_creator_id,
        source_site=source_site, tag=tag, exclude_tag=exclude_tag,
        has_thumbnail=has_thumbnail, needs_review=needs_review, is_inbox=is_inbox,
        nsfw=nsfw, is_favorite=is_favorite,
        print_status=print_status, exclude_printed=exclude_printed, min_rating=min_rating,
        excluded=excluded, added_within_days=added_within_days,
        support_status=support_status, slicer=slicer,
    )
    # character filter is list_models-only (not exposed via Library URL state)
    if character:
        q = q.filter(Model.character.ilike(f"%{character}%"))

    # Variant grouping: collapse multi-variant characters to one representative card.
    # Non-reps are computed from the *filtered* set so a model that is the only match
    # under the current filters is never hidden by a sibling that doesn't match.
    if group_variants:
        q = _collapse_variants(q)

    total = q.count()
    items = (
        _apply_sort(q, sort)
        .options(joinedload(Model.variant_group))  # explain tooltip without N+1
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Build variant count map for annotating group representatives, keyed by the
    # group key (vg:<id>). Scoped to the groups actually on this page so the query
    # never scans the whole table (#393).
    vc_map: dict[str, int] = {}
    if group_variants and items:
        vg_ids = {m.variant_group_id for m in items if m.variant_group_id is not None}
        if vg_ids:
            for gid, cnt in (
                db.query(Model.variant_group_id, func.count(Model.id))
                .filter(Model.excluded == False, Model.variant_group_id.in_(vg_ids))
                .group_by(Model.variant_group_id)
                .having(func.count(Model.id) > 1)
            ):
                vc_map[f"vg:{gid}"] = cnt

    item_reads = []
    for m in items:
        r = ModelRead.model_validate(m)
        if group_variants:
            key = _group_key_py(m)
            vc = vc_map.get(key, 1) if key else 1
            if vc > 1:
                r = r.model_copy(update={"variant_count": vc})
        item_reads.append(r)

    return ModelList(total=total, page=page, page_size=page_size, items=item_reads)


@router.get("/creators/list", response_model=list[CreatorRead])
def list_creators(db: Session = Depends(get_db)):
    rows = (
        db.query(Creator, func.count(Model.id).label("cnt"))
        .filter(func.substr(Creator.name, 1, 1) != "_")
        .outerjoin(Model, (Model.creator_id == Creator.id) & (Model.excluded == False))
        .group_by(Creator.id)
        .order_by(Creator.name)
        .all()
    )
    result = []
    for creator, cnt in rows:
        cr = CreatorRead.model_validate(creator)
        cr.model_count = cnt
        result.append(cr)
    return result


@router.get("/stats")
def model_stats(db: Session = Depends(get_db)):
    # All counts ignore user-excluded models so the stats match the visible grid.
    base = db.query(func.count(Model.id)).filter(Model.excluded == False)
    total = base.scalar()
    needs_review = base.filter(Model.needs_review == True).scalar()
    no_thumbnail = db.query(func.count(Model.id)).filter(
        Model.excluded == False, Model.thumbnail_path == None, Model.thumbnail_url == None
    ).scalar()
    favorites = db.query(func.count(Model.id)).filter(
        Model.excluded == False, Model.is_favorite == True
    ).scalar()
    queued = db.query(func.count(Model.id)).filter(
        Model.excluded == False, Model.print_status == "queued"
    ).scalar()
    printing = db.query(func.count(Model.id)).filter(
        Model.excluded == False, Model.print_status == "printing"
    ).scalar()
    printed = db.query(func.count(Model.id)).filter(
        Model.excluded == False, Model.print_status == "printed"
    ).scalar()
    excluded = db.query(func.count(Model.id)).filter(Model.excluded == True).scalar()
    return {
        "total": total, "needs_review": needs_review, "no_thumbnail": no_thumbnail,
        "favorites": favorites, "queued": queued, "printing": printing,
        "printed": printed, "excluded": excluded,
    }


@router.get("/tags/all")
def list_tags(db: Session = Depends(get_db)):
    """Return all unique tags with usage counts, sorted by frequency."""
    rows = (
        db.query(ModelTag.tag, func.count(ModelTag.id).label("count"))
        .join(Model, Model.id == ModelTag.model_id)
        .filter(Model.excluded == False)
        .group_by(ModelTag.tag)
        .order_by(func.count(ModelTag.id).desc())
        .all()
    )
    return [{"tag": row.tag, "count": row.count} for row in rows]


@router.post("/tags/rebuild")
def rebuild_tags(db: Session = Depends(get_db)):
    """Rebuild the model_tags index from the JSON tag columns on all models."""
    from app.services.tag_sync import rebuild_all_tags
    count = rebuild_all_tags(db)
    return {"ok": True, "rows": count}


@router.patch("/tags/rename")
def rename_tag(body: dict, db: Session = Depends(get_db)):
    """Rename a tag on all models that carry it."""
    old = (body.get("old_tag") or "").strip().lower()
    new = (body.get("new_tag") or "").strip().lower()
    if not old or not new:
        raise HTTPException(status_code=422, detail="old_tag and new_tag are required")
    if old == new:
        return {"ok": True, "updated": 0}
    if db.query(ModelTag).filter(ModelTag.tag == old).count() == 0:
        raise HTTPException(status_code=404, detail=f"Tag '{old}' not found")

    affected = (
        db.query(Model)
        .join(ModelTag, ModelTag.model_id == Model.id)
        .filter(ModelTag.tag == old)
        .distinct()
        .all()
    )
    for model in affected:
        tags = list(model.tags or [])
        if old in tags:
            tags = [new if t == old else t for t in tags]
            # deduplicate while preserving order
            seen: set[str] = set()
            tags = [t for t in tags if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]
            model.tags = tags
        sync_model_tags(model, db)
    db.commit()
    return {"ok": True, "updated": len(affected)}


@router.post("/tags/merge")
def merge_tags(body: dict, db: Session = Depends(get_db)):
    """Merge source_tag into target_tag: all models get target_tag, source_tag removed."""
    source = (body.get("source_tag") or "").strip().lower()
    target = (body.get("target_tag") or "").strip().lower()
    if not source or not target:
        raise HTTPException(status_code=422, detail="source_tag and target_tag are required")
    if source == target:
        return {"ok": True, "updated": 0}
    if db.query(ModelTag).filter(ModelTag.tag == source).count() == 0:
        raise HTTPException(status_code=404, detail=f"Tag '{source}' not found")

    affected = (
        db.query(Model)
        .join(ModelTag, ModelTag.model_id == Model.id)
        .filter(ModelTag.tag == source)
        .distinct()
        .all()
    )
    for model in affected:
        tags = list(model.tags or [])
        if source in tags:
            tags = [t for t in tags if t != source]
            if target not in tags:
                tags.append(target)
            model.tags = tags
        sync_model_tags(model, db)
    db.commit()
    return {"ok": True, "updated": len(affected)}


@router.delete("/tags/{tag}")
def delete_tag(tag: str, db: Session = Depends(get_db)):
    """Remove a tag from all models that carry it."""
    tag = tag.strip().lower()
    if not tag:
        raise HTTPException(status_code=422, detail="tag is required")
    if db.query(ModelTag).filter(ModelTag.tag == tag).count() == 0:
        raise HTTPException(status_code=404, detail=f"Tag '{tag}' not found")

    affected = (
        db.query(Model)
        .join(ModelTag, ModelTag.model_id == Model.id)
        .filter(ModelTag.tag == tag)
        .distinct()
        .all()
    )
    for model in affected:
        model.tags = [t for t in (model.tags or []) if t != tag]
        sync_model_tags(model, db)
    db.commit()
    return {"ok": True, "updated": len(affected)}


@router.get("/characters")
def list_characters(creator_id: int = Query(...), db: Session = Depends(get_db)):
    """Return sorted distinct character (group) names for a creator."""
    rows = (
        db.query(Model.character)
        .filter(
            Model.creator_id == creator_id,
            Model.character != None,
            Model.excluded == False,
        )
        .distinct()
        .order_by(Model.character)
        .all()
    )
    return [r[0] for r in rows]


@router.get("/variants", response_model=ModelList)
def list_variants(
    creator_id: int | None = Query(None),
    character: str | None = Query(None),
    group_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Return all variant models for a group.

    Prefer the durable `group_id` (#616); otherwise fall back to the legacy
    (creator_id, character) pair. The designated rep (variant_groups.rep_model_id)
    leads, then the heuristic rep order."""
    has_thumb = case(
        ((Model.thumbnail_path != None) | (Model.thumbnail_url != None), 0),
        else_=1,
    )
    q = db.query(Model).filter(Model.excluded == False)
    if group_id is not None:
        q = q.filter(Model.variant_group_id == group_id)
    elif creator_id is not None and character is not None:
        q = q.filter(Model.creator_id == creator_id, Model.character == character)
    else:
        raise HTTPException(status_code=400, detail="Provide group_id or (creator_id and character).")

    q = q.outerjoin(VariantGroup, Model.variant_group_id == VariantGroup.id)
    is_rep_pref = case((Model.id == VariantGroup.rep_model_id, 0), else_=1)
    items = (
        q.order_by(
            is_rep_pref,
            Model.is_group_rep.desc(),
            Model.variant_order.is_(None),
            Model.variant_order.asc(),
            has_thumb,
            Model.name,
        )
        .all()
    )
    return ModelList(total=len(items), page=1, page_size=max(len(items), 1), items=items)


@router.patch("/stl-files/{file_id}")
def update_stl_file(file_id: int, body: STLFileUpdate, db: Session = Depends(get_db)):
    """Update metadata on a single STL file (e.g. part_type)."""
    from app.models import STLFile
    f = db.query(STLFile).filter(STLFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="STL file not found")
    data = body.model_dump(exclude_unset=True)
    if "part_type" in data:
        pt = data["part_type"]
        f.part_type = pt.strip() if pt and pt.strip() else None
    if "part_name" in data:
        pn = data["part_name"]
        f.part_name = pn.strip() if pn and pn.strip() else None
    if "sup_of_id" in data:
        sup_id = data["sup_of_id"]
        if sup_id is not None:
            if sup_id == file_id:
                raise HTTPException(status_code=400, detail="sup_of_id cannot reference the file itself")
            target = db.query(STLFile).filter(STLFile.id == sup_id).first()
            if not target:
                raise HTTPException(status_code=400, detail="sup_of_id references a nonexistent file")
            if target.model_id != f.model_id:
                raise HTTPException(status_code=400, detail="sup_of_id must reference a file within the same model")
        f.sup_of_id = sup_id
    db.commit()
    return {"ok": True}


@router.post("/{model_id}/ai-organize", response_model=AiOrganizeResult)
def ai_organize_model(model_id: int, db: Session = Depends(get_db)):
    """Call the configured AI organizer to normalize part names and link sup files."""
    from app.models import STLFile, AppSetting
    from app.services import secrets as _secrets

    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if not model.stl_files:
        raise HTTPException(status_code=400, detail="Model has no STL files to organize")

    # Read organizer config from app_settings
    enabled_row = db.get(AppSetting, "ai_organize_enabled")
    if not enabled_row or enabled_row.value != "true":
        raise HTTPException(status_code=400, detail="AI organizer is not enabled")

    url_row = db.get(AppSetting, "ai_organize_url")
    model_row = db.get(AppSetting, "ai_organize_model")
    url = url_row.value if url_row else ""
    org_model = model_row.value if model_row else ""
    api_key = _secrets.get_organize_api_key(db) or ""

    file_dicts = [
        {"id": f.id, "filename": f.filename, "part_type": f.part_type, "part_name": f.part_name}
        for f in model.stl_files
    ]
    by_filename = {f.filename: f.id for f in model.stl_files}
    by_id = {f.id: f for f in model.stl_files}

    try:
        suggestions = ai_organize.run(file_dicts, url, org_model, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    applied: list[AiOrganizeSuggestion] = []
    for s in suggestions:
        file_id = s.get("id")
        if not isinstance(file_id, int) or file_id not in by_id:
            continue
        f = by_id[file_id]

        part_type = s.get("part_type")
        part_name = s.get("part_name")
        sup_base_filename = s.get("sup_base_filename")

        if part_type is not None:
            f.part_type = part_type.strip() or None
        if part_name is not None:
            f.part_name = part_name.strip() or None

        resolved_sup_id: int | None = None
        if sup_base_filename:
            base_id = by_filename.get(sup_base_filename)
            if base_id and base_id != file_id:
                f.sup_of_id = base_id
                resolved_sup_id = base_id

        applied.append(AiOrganizeSuggestion(
            id=file_id,
            part_type=f.part_type,
            part_name=f.part_name,
            sup_of_id=resolved_sup_id,
        ))

    db.commit()
    return AiOrganizeResult(
        applied=applied,
        message=f"Applied suggestions to {len(applied)} file(s).",
    )


@router.patch("/bulk")
def bulk_tag_models(body: BulkTagUpdate, db: Session = Depends(get_db)):
    """Add or remove tags across multiple models in one request."""
    ids = body.ids
    add_tags = [t.strip().lower() for t in body.add_tags if t.strip()]
    remove_set = {t.strip().lower() for t in body.remove_tags if t.strip()}

    if not ids:
        raise HTTPException(status_code=400, detail="No model IDs provided")

    models_to_update = db.query(Model).filter(Model.id.in_(ids)).all()
    for model in models_to_update:
        current = list(model.tags or [])
        if add_tags:
            current = list(dict.fromkeys(current + add_tags))
        if remove_set:
            current = [t for t in current if t not in remove_set]
        model.tags = current
        model.updated_at = utcnow()

    bulk_sync_model_tags(models_to_update, db)
    db.commit()
    return {"ok": True, "updated": len(models_to_update)}


# NB: these /bulk/... routes must be declared before /{model_id}/exclude etc.,
# or FastAPI would match "bulk" as the model_id path param and 422 on int parse.
@router.patch("/bulk/exclude")
def bulk_exclude_models(body: BulkExcludeUpdate, db: Session = Depends(get_db)):
    """Exclude (hide) or restore multiple models in one request. Mirrors the
    single-model exclude: hiding also clears any lingering print-queue state."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="No model IDs provided")

    models_to_update = db.query(Model).filter(Model.id.in_(body.ids)).all()
    for model in models_to_update:
        model.excluded = body.excluded
        if body.excluded:
            _clear_queue_state(model)
    db.commit()
    return {"ok": True, "updated": len(models_to_update)}


@router.patch("/bulk/review")
def bulk_review_models(body: BulkReviewUpdate, db: Session = Depends(get_db)):
    """Mark or clear the needs-review flag across multiple models in one request."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="No model IDs provided")

    models_to_update = db.query(Model).filter(Model.id.in_(body.ids)).all()
    for model in models_to_update:
        model.needs_review = body.needs_review
        model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "updated": len(models_to_update)}


@router.patch("/bulk/enrich")
def bulk_enrich_models(body: BulkEnrichUpdate, db: Session = Depends(get_db)):
    """Set creator, title, notes, and/or source_url across multiple models in one
    request. Any field omitted from the payload is left unchanged on each model.
    Grouping (character/variant_group) is not editable here (#678 Phase 5) — use
    the durable-group merge/split/patch endpoints instead."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="No model IDs provided")
    # Trim before validation: a whitespace-only creator_name is truthy but must
    # not create a blank-named Creator (#439).
    creator_name = body.creator_name.strip() if body.creator_name is not None else None
    if body.creator_name is not None and not creator_name:
        raise HTTPException(status_code=400, detail="Creator name cannot be blank")
    if not any([
        creator_name, body.title is not None,
        body.notes is not None, body.source_url is not None,
    ]):
        raise HTTPException(status_code=400, detail="At least one field to update must be provided")

    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")

    creator_id = resolve_creator(creator_name, db).id if creator_name else None
    models_to_update = db.query(Model).filter(Model.id.in_(body.ids)).all()
    for model in models_to_update:
        if creator_id is not None:
            model.creator_id = creator_id
        if body.title is not None:
            model.title = body.title.strip() or None
        if body.notes is not None:
            model.notes = body.notes.strip() or None
        if body.source_url is not None:
            model.source_url = body.source_url.strip() or None
            if model.source_url:
                propagate_source_url(db, model)
        model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "updated": len(models_to_update)}


@router.delete("/bulk", response_model=BulkDeleteResponse)
def bulk_delete_models(body: BulkDeleteRequest, db: Session = Depends(get_db)):
    """Permanently remove models from the database, optionally deleting their files.

    Deletion order: CollectionModel links → STLFile records → Model records. If
    delete_files=True, each unique folder_path is removed from disk after the DB
    transaction commits, provided the path is contained within a known scan root
    (path-injection guard). Empty parent directories are NOT removed — the caller
    owns the cleanup policy."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="No model IDs provided")

    models_to_delete = db.query(Model).filter(Model.id.in_(body.ids)).all()
    if not models_to_delete:
        raise HTTPException(status_code=404, detail="No matching models found")

    # Collect folders before touching the DB (needed for disk deletion).
    folder_paths = list({m.folder_path for m in models_to_delete if m.folder_path})

    # Path guard: build allowed roots once, used only when delete_files=True.
    if body.delete_files and folder_paths:
        roots = [os.path.realpath(r.path) for r in db.query(ScanRoot).all()]

        def _within_roots(p: str) -> bool:
            real = os.path.realpath(p)
            for root in roots:
                try:
                    if os.path.commonpath([real, root]) == root:
                        return True
                except ValueError:
                    pass
            return False

        unsafe = [p for p in folder_paths if not _within_roots(p)]
        if unsafe:
            raise HTTPException(
                status_code=400,
                detail=f"Some folders are outside known scan roots and cannot be deleted: {unsafe}",
            )

    model_ids = [m.id for m in models_to_delete]

    # Delete child records manually (no ON DELETE CASCADE on these FKs).
    db.query(CollectionModel).filter(CollectionModel.model_id.in_(model_ids)).delete(
        synchronize_session=False
    )
    db.query(STLFile).filter(STLFile.model_id.in_(model_ids)).delete(
        synchronize_session=False
    )
    db.query(Model).filter(Model.id.in_(model_ids)).delete(synchronize_session=False)
    db.commit()

    folders_removed = 0
    if body.delete_files:
        for path in folder_paths:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                    folders_removed += 1
            except Exception as exc:
                _log.warning("Could not delete folder %r: %s", path, exc)

    return BulkDeleteResponse(deleted=len(model_ids), folders_removed=folders_removed)


@router.patch("/{model_id}")
async def update_model(model_id: int, body: ModelUpdate, db: Session = Depends(get_db)):
    """Partial update of model metadata fields — only fields actually sent apply."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    data = body.model_dump(exclude_unset=True)
    allowed = {
        "title", "description", "notes", "source_url", "source_site",
        "license", "category", "tags", "removed_auto_tags", "custom_attributes",
        "nsfw", "needs_review", "thumbnail_url", "primary_image_path", "image_paths",
    }
    # The metadata editor resubmits the whole form, so only treat thumbnail_url
    # as "changed" when it differs from what's stored. A new remote URL is
    # downloaded to a local file (remote CDNs block hot-linking in <img> tags);
    # if that fails we keep the URL but clear the local path so the URL at
    # least takes display precedence.
    new_thumb_url = data.get("thumbnail_url")
    if new_thumb_url and new_thumb_url != model.thumbnail_url:
        try:
            model.thumbnail_path = str(await download_thumbnail(model.id, new_thumb_url))
            data["thumbnail_url"] = None
        except ThumbnailDownloadError:
            model.thumbnail_path = None
    for key, value in data.items():
        if key in allowed:
            if key in ("tags", "removed_auto_tags") and isinstance(value, list):
                value = list(dict.fromkeys(t.strip().lower() for t in value if t.strip()))
            setattr(model, key, value)

    # If image_paths was updated and primary_image_path is no longer in the list, clear it.
    if "image_paths" in data and isinstance(data["image_paths"], list):
        if model.primary_image_path and model.primary_image_path not in data["image_paths"]:
            model.primary_image_path = None

    if data.get("creator_name"):
        model.creator_id = resolve_creator(data["creator_name"], db).id

    if data.get("source_url"):
        propagate_source_url(db, model)

    model.updated_at = utcnow()
    sync_model_tags(model, db)
    db.commit()
    return {"ok": True}


@router.patch("/{model_id}/thumbnail")
def set_thumbnail(model_id: int, body: ThumbnailUpdate, db: Session = Depends(get_db)):
    """Set thumbnail_path or thumbnail_url on a model."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    data = body.model_dump(exclude_unset=True)
    if "thumbnail_path" in data:
        model.thumbnail_path = data["thumbnail_path"] or None
    if "thumbnail_url" in data:
        model.thumbnail_url = data["thumbnail_url"] or None
    db.commit()
    return {"ok": True}


@router.patch("/{model_id}/group-rep")
def set_group_rep(model_id: int, body: GroupRepUpdate, db: Session = Depends(get_db)):
    """Designate a model as its variant group's display thumbnail (#193).

    Sets `is_group_rep` on this model and clears it from every sibling in the
    same (creator, character) group, so at most one member is the rep. Pass
    `is_group_rep=false` to clear it and fall back to the heuristic. 400 if the
    model isn't part of a group (no creator/character).
    """
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.creator_id is None or not model.character:
        raise HTTPException(status_code=400, detail="Model is not part of a variant group.")

    if body.is_group_rep:
        # Clear the flag across the whole group first, then set it on this model.
        db.query(Model).filter(
            Model.creator_id == model.creator_id,
            Model.character == model.character,
            Model.id != model.id,
        ).update({Model.is_group_rep: False}, synchronize_session=False)
        model.is_group_rep = True
    else:
        model.is_group_rep = False
    model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "is_group_rep": model.is_group_rep}


@router.post("/group/thumbnail/from-url")
async def batch_thumbnail_from_url(body: BatchThumbnailFromUrl, db: Session = Depends(get_db)):
    """Assign one image to every model in a group (#184).

    The image is fetched ONCE (reusing the single-model HTML/og:image follow),
    then the same bytes are written to each member's per-model thumbnail file.
    On a download failure we fall back to storing the bare URL on every member
    and clearing their local paths — the same graceful degradation the single
    from-url path uses (#285) — so the UI can still try to render directly.
    Unknown ids are skipped and reported. 409 if a scan is running, since it
    would overwrite character/grouping mid-write.

    Registered BEFORE `/{model_id}/thumbnail/from-url` so the literal `group`
    segment isn't captured as a model_id (FastAPI matches in declaration order).
    """
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")

    if not body.model_ids:
        raise HTTPException(status_code=400, detail="model_ids must not be empty.")

    requested = list(dict.fromkeys(body.model_ids))  # de-dupe, preserve order
    models = db.query(Model).filter(Model.id.in_(requested)).all()
    found = {m.id for m in models}
    missing = [mid for mid in requested if mid not in found]

    try:
        ext, data = await fetch_image_bytes(body.url)
    except ThumbnailDownloadError as e:
        # Graceful degrade: store the bare URL on every member so the UI can try
        # to render it directly, even though the server-side download failed.
        for model in models:
            model.thumbnail_path = None
            model.thumbnail_url = body.url
            model.updated_at = utcnow()
        db.commit()
        return {
            "ok": True,
            "downloaded": False,
            "detail": str(e),
            "updated": [m.id for m in models],
            "missing": missing,
        }

    for model in models:
        path = store_thumbnail(model.id, ext, data)
        model.thumbnail_path = str(path)
        model.thumbnail_url = None
        model.updated_at = utcnow()
    db.commit()
    return {
        "ok": True,
        "downloaded": True,
        "updated": [m.id for m in models],
        "missing": missing,
    }


@router.post("/{model_id}/thumbnail/from-url")
async def set_thumbnail_from_url(
    model_id: int,
    body: ThumbnailFromUrl,
    db: Session = Depends(get_db),
):
    """Download a remote image server-side and store it as the local thumbnail.

    Remote CDNs commonly block hot-linking, so downloading to a local file is
    the reliable path. When the server-side download fails we *don't* dead-end
    with a 422 (the model is left unchanged and the picker shows nothing usable);
    instead we fall back to storing the bare URL and clearing the local path —
    the same graceful degradation PATCH /models/{id} and /scrape/apply use, so
    the UI can still try to render the image directly (#285). The response's
    `downloaded` flag lets the caller warn that it may not load if the host
    blocks embedding.
    """
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    try:
        path = await download_thumbnail(model_id, body.url)
    except ThumbnailDownloadError as e:
        model.thumbnail_path = None
        model.thumbnail_url = body.url
        model.updated_at = utcnow()
        db.commit()
        return {"ok": True, "path": None, "downloaded": False, "detail": str(e)}

    model.thumbnail_path = str(path)
    model.thumbnail_url = None
    model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "path": str(path), "downloaded": True}


@router.post("/{model_id}/thumbnail/upload")
async def upload_thumbnail(
    model_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Store a captured PNG from the 3D viewer as this model's thumbnail."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if file.content_type not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(status_code=400, detail="Only PNG/JPEG/WebP images are accepted")

    out = store_thumbnail(model_id, ".png", await file.read())

    model.thumbnail_path = str(out)
    model.thumbnail_url = None
    db.commit()
    return {"ok": True, "path": str(out)}


@router.patch("/{model_id}/favorite")
def set_favorite(model_id: int, body: FavoriteUpdate, db: Session = Depends(get_db)):
    """Toggle a model's favorite flag."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    model.is_favorite = body.is_favorite
    db.commit()
    return {"ok": True, "is_favorite": model.is_favorite}


@router.patch("/{model_id}/rating")
def set_rating(model_id: int, body: RatingUpdate, db: Session = Depends(get_db)):
    """Set a model's 1–5 star rating, or clear it (rating=null) back to unrated (#167)."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    model.user_rating = body.rating
    model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "user_rating": model.user_rating}


@router.patch("/queue/reorder")
def reorder_queue(body: QueueReorder, db: Session = Depends(get_db)):
    """Persist a manual drag order for the print queue. `ids` is the queue in the
    user's desired order; we store each model's index as its queue_position.
    Favorites still float to the top at display time (see list_models sort)."""
    pos_by_id = {mid: i for i, mid in enumerate(body.ids)}
    if not pos_by_id:
        return {"ok": True, "updated": 0}
    models = db.query(Model).filter(Model.id.in_(pos_by_id)).all()
    for m in models:
        m.queue_position = pos_by_id[m.id]
    db.commit()
    return {"ok": True, "updated": len(models)}


@router.patch("/group/reorder")
def reorder_group(body: GroupReorder, db: Session = Depends(get_db)):
    """Persist a manual model order within a variant group (#399).

    `ids` is the group's members in the user's desired order; each member's index
    becomes its `variant_order`, and the lowest order is the group's representative
    card (see _rep_order). An **empty `ids` resets** the whole (creator, character)
    group — clears every member's variant_order so the heuristic order resumes.
    Ids that don't belong to the group are ignored. Scans never touch
    variant_order, so no scan-in-progress guard is needed."""
    group = db.query(Model).filter(
        Model.creator_id == body.creator_id,
        Model.character == body.character,
    )
    if not body.ids:
        updated = group.update({Model.variant_order: None}, synchronize_session=False)
        db.commit()
        return {"ok": True, "reset": True, "updated": updated}

    pos_by_id = {mid: i for i, mid in enumerate(body.ids)}
    members = group.all()
    touched = 0
    for m in members:
        # Members listed in `ids` get their drag position; any group member the
        # client omitted is sent to the back (keeps a stable, gap-free order).
        m.variant_order = pos_by_id.get(m.id, len(pos_by_id))
        touched += 1
    db.commit()
    return {"ok": True, "reset": False, "updated": touched}


@router.patch("/{model_id}/print-status")
def set_print_status(model_id: int, body: PrintStatusUpdate, db: Session = Depends(get_db)):
    """Set a model's print lifecycle status — the single source of truth for print
    tracking (none|queued|printing|printed).

    Maintains the supporting timestamps the status string can't carry: queue
    ordering (queued_at/queue_position) and print history (printed_at/print_count).
    """
    from app.schemas import PRINT_STATUSES
    if body.status not in PRINT_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(PRINT_STATUSES)}")
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    was_queued = model.print_status == "queued"
    was_printed = model.print_status == "printed"
    model.print_status = body.status

    if body.status == "queued":
        # Appending to the queue: new entries go to the end of the manual order
        # (favorites still float to the top at display time).
        if not was_queued:
            model.queued_at = utcnow()
            max_pos = db.query(func.max(Model.queue_position)).filter(
                Model.print_status == "queued"
            ).scalar()
            model.queue_position = (max_pos or 0) + 1
    elif body.status == "printed":
        model.queued_at = None
        model.queue_position = None
        # Only a real none/queued/printing → printed transition counts as a new
        # print; re-setting an already-printed model must not inflate the count.
        if not was_printed:
            model.printed_at = utcnow()
            model.print_count = (model.print_count or 0) + 1
    else:  # none | printing — leaves the active queue
        model.queued_at = None
        model.queue_position = None
        # Reverting away from printed (e.g. a status advanced by mistake) undoes
        # the print it recorded so phantom counts don't accumulate (#379).
        if was_printed:
            model.print_count = max((model.print_count or 0) - 1, 0)
            if model.print_count == 0:
                model.printed_at = None

    db.commit()
    return {"ok": True, "print_status": model.print_status, "print_count": model.print_count}


@router.patch("/{model_id}/exclude")
def set_excluded(model_id: int, body: ExcludeUpdate, db: Session = Depends(get_db)):
    """Hide a model from the viewer (or restore it). Files on disk are untouched;
    the scanner preserves this flag so an excluded model is never resurrected."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    model.excluded = body.excluded
    if body.excluded:
        # A hidden model shouldn't linger in print-queue state.
        _clear_queue_state(model)
    db.commit()
    return {"ok": True, "excluded": model.excluded}


@router.post("/{model_id}/split")
def split_pack(model_id: int, db: Session = Depends(get_db)):
    """Split a model whose folder is actually a multi-product pack into one model
    per child folder (opt-in; persisted so it survives rescans). The original
    model is replaced by its children, so the caller should navigate away."""
    if not db.query(Model.id).filter(Model.id == model_id).first():
        raise HTTPException(status_code=404, detail="Model not found")
    result = scanner.split_pack(model_id)
    if not result["ok"]:
        # A running scan is a conflict; everything else is a bad request.
        code = 409 if "scan is already running" in result["message"] else 400
        raise HTTPException(status_code=code, detail=result["message"])
    return result


# ---------------------------------------------------------------------------
# Manual variant groups (#617): user-curated merge / split / relabel. These set
# source="manual" so the scanner's proposal engine never reassigns the members.
# ---------------------------------------------------------------------------

def _mark_ungrouped(db: Session, model: Model) -> None:
    """Pin a model as explicitly ungrouped, sticky across rescans (#678 Phase 5).

    Used when a model is deliberately removed from its group (split, or a
    dissolve that drops a group below 2 members) — without this the proposal
    engine would happily re-propose the same auto group on the next scan."""
    model.no_group = True
    model.updated_at = utcnow()


def _prune_empty_group(db: Session, group_id: int | None) -> None:
    """Delete a group that has dropped below 2 members; clear the lone member."""
    if group_id is None:
        return
    remaining = db.query(Model).filter(Model.variant_group_id == group_id).all()
    if len(remaining) < 2:
        for m in remaining:
            m.variant_group_id = None
            _mark_ungrouped(db, m)
        grp = db.get(VariantGroup, group_id)
        if grp is not None:
            db.delete(grp)


@router.post("/groups/merge", response_model=VariantGroupRead)
def merge_group(body: GroupMergeBody, db: Session = Depends(get_db)):
    """Merge models into one manual variant group. Creates the group when
    group_id is omitted, else extends it. Marks the group manual so a rescan
    won't undo it. 409 while a scan is running."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")
    ids = list(dict.fromkeys(body.model_ids))
    if len(ids) < 2 and body.group_id is None:
        raise HTTPException(status_code=400, detail="Need at least two models to form a group.")

    models = db.query(Model).filter(Model.id.in_(ids)).all()
    if not models:
        raise HTTPException(status_code=400, detail="No valid models to merge.")
    creator_ids = {m.creator_id for m in models}
    if len(creator_ids) > 1:
        raise HTTPException(status_code=400, detail="Can't merge models from different creators.")
    creator_id = next(iter(creator_ids))

    if body.group_id is not None:
        group = db.get(VariantGroup, body.group_id)
        if group is None:
            raise HTTPException(status_code=404, detail="Group not found.")
        if body.label is not None:
            group.label = body.label
    else:
        label = body.label or models[0].character or models[0].name
        group = VariantGroup(
            creator_id=creator_id, label=label, source="manual",
            reason="manual", confidence=1.0,
        )
        db.add(group)
        db.flush()
    group.source = "manual"

    orphaned = {m.variant_group_id for m in models if m.variant_group_id not in (None, group.id)}
    for m in models:
        m.variant_group_id = group.id
        # An explicit merge overrides any earlier "keep me out" pin (#678 Phase 5).
        m.no_group = False
        m.updated_at = utcnow()
    if group.rep_model_id is None:
        group.rep_model_id = next((m.id for m in models if m.is_group_rep), models[0].id)
    db.flush()
    for gid in orphaned:
        _prune_empty_group(db, gid)
    db.commit()
    db.refresh(group)
    return group


@router.post("/groups/{group_id}/split", response_model=dict)
def split_group(group_id: int, body: GroupSplitBody, db: Session = Depends(get_db)):
    """Remove members from a group (they become ungrouped). The remaining group is
    marked manual so the split sticks across rescans. Dissolves the group if it
    drops below two members. 409 while a scan is running."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")
    group = db.get(VariantGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found.")
    ids = set(body.model_ids)
    removed = (
        db.query(Model)
        .filter(Model.variant_group_id == group_id, Model.id.in_(ids))
        .all()
    )
    for m in removed:
        m.variant_group_id = None
        _mark_ungrouped(db, m)
    group.source = "manual"
    # If the designated rep left, fall back to a remaining member.
    if group.rep_model_id in ids:
        rest = db.query(Model).filter(Model.variant_group_id == group_id).first()
        group.rep_model_id = rest.id if rest else None
    db.flush()
    _prune_empty_group(db, group_id)
    db.commit()
    return {"ok": True, "removed": [m.id for m in removed]}


@router.patch("/groups/{group_id}", response_model=VariantGroupRead)
def patch_group(group_id: int, body: GroupPatchBody, db: Session = Depends(get_db)):
    """Relabel a group or set its representative. Marks the group manual."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")
    group = db.get(VariantGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found.")
    if body.label is not None:
        group.label = body.label
    if body.rep_model_id is not None:
        rep = db.get(Model, body.rep_model_id)
        if rep is None or rep.variant_group_id != group_id:
            raise HTTPException(status_code=400, detail="rep_model_id must be a member of the group.")
        group.rep_model_id = body.rep_model_id
    group.source = "manual"
    db.commit()
    db.refresh(group)
    return group


@router.get("/grouping-strategy")
def get_grouping_strategy(path: str = Query(...), db: Session = Depends(get_db)):
    """Effective grouping strategy for a folder path (nearest ancestor, default auto)."""
    strategies = [(grouping._norm(p), s) for (p, s) in db.query(GroupingStrategy.path, GroupingStrategy.strategy)]
    return {"path": path, "strategy": grouping._resolve_strategy(path, strategies)}


@router.post("/grouping-strategy")
def set_grouping_strategy(body: GroupingStrategyBody, db: Session = Depends(get_db)):
    """Set a per-subtree grouping strategy (#618). "off" leaves the subtree's
    models ungrouped; "auto" clears the override (restores the proposal engine).
    Re-runs the engine for affected creators so the change shows immediately.
    409 while a scan is running."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")
    if body.strategy not in ("auto", "off"):
        raise HTTPException(status_code=400, detail="strategy must be 'auto' or 'off'.")

    norm = grouping._norm(body.path)
    if body.strategy == "off":
        stmt = (
            _sqlite_insert(GroupingStrategy)
            .values(path=body.path, strategy="off")
            .on_conflict_do_update(index_elements=["path"], set_={"strategy": "off"})
        )
        db.execute(stmt)
    else:
        db.query(GroupingStrategy).filter(GroupingStrategy.path == body.path).delete()
    db.flush()

    # Re-group only the creators that actually have models under this subtree so
    # the strategy takes effect now rather than at the next scan.
    path_prefix = body.path.rstrip("/\\")
    affected = (
        db.query(Model.creator_id)
        .filter(
            Model.creator_id != None,  # noqa: E711
            (Model.folder_path == body.path)
            | Model.folder_path.like(path_prefix + "%"),
        )
        .distinct()
        .all()
    )
    for (creator_id,) in affected:
        grouping.regroup_creator(db, creator_id)
    db.commit()
    return {"ok": True, "path": body.path, "strategy": body.strategy}


def _host_label(url: str) -> str | None:
    """Bare hostname (sans leading 'www.') for store URLs we don't scrape, so a
    Patreon/Etsy/personal store page still records *some* source_site."""
    host = (urlparse(url if "//" in url else f"https://{url}").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None


@router.post("/group/source-url")
def batch_set_source_url(body: BatchSetSourceUrl, db: Session = Depends(get_db)):
    """Set one store-page URL on a selected set of variants (#500).

    Selection-scoped and overwriting: writes `source_url`/`source_site` to
    exactly the given ids, replacing any existing URL. Unlike the single-model
    paths it does NOT call `propagate_source_url` — the user picked these
    variants, so unselected siblings are deliberately left untouched.

    `source_site` is derived from the URL: a known storefront key when the host
    matches (`detect_site`), else the bare hostname so non-scraped stores still
    carry a label. Unknown ids are skipped and reported. 409 if a scan is
    running (it would overwrite fields on commit). Registered under `/group/`
    so the literal segment isn't captured as a `{model_id}`."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")

    if not body.model_ids:
        raise HTTPException(status_code=400, detail="model_ids must not be empty.")

    url = body.source_url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="source_url must not be empty.")
    source_site = detect_site(url) or _host_label(url)
    if not source_site:
        raise HTTPException(status_code=400, detail="source_url must be a valid URL.")

    requested = list(dict.fromkeys(body.model_ids))  # de-dupe, preserve order
    models = db.query(Model).filter(Model.id.in_(requested)).all()
    found = {m.id for m in models}

    for model in models:
        model.source_url = url
        model.source_site = source_site
        model.source_last_fetched = utcnow()
        model.updated_at = utcnow()
    db.commit()

    return {
        "ok": True,
        "source_site": source_site,
        "updated": [m.id for m in models],
        "missing": [mid for mid in requested if mid not in found],
    }




@router.get("/{model_id}/neighbors")
def get_neighbors(
    model_id: int,
    search: str = Query("", alias="q"),
    creator_id: int | None = None,
    exclude_creator_id: int | None = None,
    source_site: str | None = None,
    tag: str | None = None,
    exclude_tag: str | None = None,
    has_thumbnail: bool | None = None,
    needs_review: bool | None = None,
    is_inbox: bool | None = None,
    nsfw: bool | None = None,
    is_favorite: bool | None = None,
    print_status: str | None = None,
    exclude_printed: bool = False,
    min_rating: int | None = Query(None, ge=1, le=5),
    excluded: bool = False,
    added_within_days: int | None = Query(None, ge=1, le=365),
    sort: str = Query("name"),
    group_variants: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Return the prev/next model IDs adjacent to model_id in the filtered+sorted list.

    Handles non-representative variants: if model_id is a grouped non-rep, its
    group's representative is located instead, so Prev/Next still pages correctly.
    """
    q = _apply_filters(
        db.query(Model),
        search=search, creator_id=creator_id, exclude_creator_id=exclude_creator_id,
        source_site=source_site, tag=tag, exclude_tag=exclude_tag,
        has_thumbnail=has_thumbnail, needs_review=needs_review, is_inbox=is_inbox,
        nsfw=nsfw, is_favorite=is_favorite,
        print_status=print_status, exclude_printed=exclude_printed, min_rating=min_rating,
        excluded=excluded, added_within_days=added_within_days,
    )

    target_id = model_id
    if group_variants:
        target_id = _resolve_group_rep(q, model_id)
        q = _collapse_variants(q)

    ids = [row[0] for row in _apply_sort(q.with_entities(Model.id), sort).all()]
    try:
        idx = ids.index(target_id)
    except ValueError:
        return {"prev_id": None, "next_id": None}

    return {
        "prev_id": ids[idx - 1] if idx > 0 else None,
        "next_id": ids[idx + 1] if idx < len(ids) - 1 else None,
    }


@router.get("/{model_id}", response_model=ModelDetail)
def get_model(model_id: int, db: Session = Depends(get_db)):
    model = (
        db.query(Model)
        .options(
            joinedload(Model.stl_files),
            joinedload(Model.creator),
            joinedload(Model.collection_links),
        )
        .filter(Model.id == model_id)
        .first()
    )
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    result = ModelDetail.model_validate(model)
    result.native_folder_path = settings.to_native_path(model.folder_path)
    result.collection_ids = [link.collection_id for link in model.collection_links]
    return result

from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, exists, text as _sql
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Model, Creator, ModelTag, CollectionModel, GroupOverride
from app.schemas import (
    ModelList, ModelRead, ModelDetail, CreatorRead,
    ModelUpdate, ThumbnailUpdate, ThumbnailFromUrl, FavoriteUpdate, QueueUpdate, QueueReorder,
    PrintedUpdate, ExcludeUpdate, STLFileUpdate, BulkTagUpdate, SetGroupBody,
)
from app.services.thumbnails import ThumbnailDownloadError, download_thumbnail, store_thumbnail
from app.services.variant_sync import propagate_source_url
from app.services.tag_sync import sync_model_tags
from app.services import scanner
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
    nsfw: bool | None = None,
    is_favorite: bool | None = None,
    in_queue: bool | None = None,
    printed: bool | None = None,
    excluded: bool = False,
    added_within_days: int | None = None,
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
    if nsfw is not None:
        q = q.filter(Model.nsfw == nsfw)
    if is_favorite is not None:
        q = q.filter(Model.is_favorite == is_favorite)
    if in_queue is not None:
        q = q.filter(Model.in_queue == in_queue)
    if printed is True:
        q = q.filter(Model.printed_at != None)
    if printed is False:
        q = q.filter(Model.printed_at == None)
    if added_within_days is not None:
        q = q.filter(Model.created_at >= utcnow() - timedelta(days=added_within_days))
    return q


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
    else:
        return (Model.character, Model.name)


def _collapse_variants(q) -> tuple:
    """Apply variant grouping to a query.

    Returns (filtered_query, rep_by_nonrep) where rep_by_nonrep maps each
    non-representative model ID to its group representative's ID.
    """
    from collections import defaultdict
    rows = q.with_entities(
        Model.id, Model.creator_id, Model.character,
        Model.thumbnail_path, Model.thumbnail_url,
    ).all()
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        if row.character and row.creator_id is not None:
            groups[(row.creator_id, row.character)].append(row)
    rep_by_nonrep: dict[int, int] = {}
    non_rep_ids: list[int] = []
    for group_rows in groups.values():
        if len(group_rows) <= 1:
            continue
        with_thumb = [r for r in group_rows if r.thumbnail_path or r.thumbnail_url]
        rep_id = min(with_thumb, key=lambda r: r.id).id if with_thumb else min(group_rows, key=lambda r: r.id).id
        for r in group_rows:
            if r.id != rep_id:
                non_rep_ids.append(r.id)
                rep_by_nonrep[r.id] = rep_id
    if non_rep_ids:
        q = q.filter(~Model.id.in_(non_rep_ids))
    return q, rep_by_nonrep


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
    nsfw: bool | None = None,
    is_favorite: bool | None = None,
    in_queue: bool | None = None,
    printed: bool | None = None,
    excluded: bool = False,  # default: hide user-excluded models; pass true for the Excluded view
    added_within_days: int | None = Query(None, ge=1, le=365),  # "Recently added" window (#170)
    sort: str = Query("name"),  # "name" | "queued_at" | "printed_at" | "added"
    group_variants: bool = Query(True),
    db: Session = Depends(get_db),
):
    q = _apply_filters(
        db.query(Model),
        search=search, creator_id=creator_id, exclude_creator_id=exclude_creator_id,
        source_site=source_site, tag=tag, exclude_tag=exclude_tag,
        has_thumbnail=has_thumbnail, needs_review=needs_review,
        nsfw=nsfw, is_favorite=is_favorite, in_queue=in_queue,
        printed=printed, excluded=excluded, added_within_days=added_within_days,
    )
    # character filter is list_models-only (not exposed via Library URL state)
    if character:
        q = q.filter(Model.character.ilike(f"%{character}%"))

    # Variant grouping: collapse multi-variant characters to one representative card.
    # Non-reps are computed from the *filtered* set so a model that is the only match
    # under the current filters is never hidden by a sibling that doesn't match.
    if group_variants:
        q, _ = _collapse_variants(q)

    total = q.count()
    order_cols = _order_cols(sort)
    items = q.order_by(*order_cols).offset((page - 1) * page_size).limit(page_size).all()

    # Build variant count map for annotating group representatives
    vc_map: dict[tuple[int, str], int] = {}
    if group_variants and items:
        count_rows = db.execute(_sql("""
            SELECT creator_id, character, COUNT(*) AS cnt
            FROM models
            WHERE character IS NOT NULL AND excluded = 0
            GROUP BY creator_id, character
            HAVING COUNT(*) > 1
        """)).fetchall()
        vc_map = {(r[0], r[1]): r[2] for r in count_rows}

    item_reads = []
    for m in items:
        r = ModelRead.model_validate(m)
        if group_variants and m.character and m.creator_id:
            vc = vc_map.get((m.creator_id, m.character), 1)
            if vc > 1:
                r = r.model_copy(update={"variant_count": vc})
        item_reads.append(r)

    return ModelList(total=total, page=page, page_size=page_size, items=item_reads)


@router.get("/creators/list", response_model=list[CreatorRead])
def list_creators(db: Session = Depends(get_db)):
    rows = (
        db.query(Creator, func.count(Model.id).label("cnt"))
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
        Model.excluded == False, Model.in_queue == True
    ).scalar()
    printed = db.query(func.count(Model.id)).filter(
        Model.excluded == False, Model.printed_at != None
    ).scalar()
    excluded = db.query(func.count(Model.id)).filter(Model.excluded == True).scalar()
    return {
        "total": total, "needs_review": needs_review, "no_thumbnail": no_thumbnail,
        "favorites": favorites, "queued": queued, "printed": printed,
        "excluded": excluded,
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
    creator_id: int = Query(...),
    character: str = Query(...),
    db: Session = Depends(get_db),
):
    """Return all variant models for a (creator, character) group."""
    items = (
        db.query(Model)
        .filter(
            Model.creator_id == creator_id,
            Model.character == character,
            Model.excluded == False,
        )
        .order_by(Model.name)
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
        f.part_type = pt.strip().lower() if pt and pt.strip() else None
    db.commit()
    return {"ok": True}


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
        sync_model_tags(model, db)

    db.commit()
    return {"ok": True, "updated": len(models_to_update)}


@router.patch("/{model_id}")
async def update_model(model_id: int, body: ModelUpdate, db: Session = Depends(get_db)):
    """Partial update of model metadata fields — only fields actually sent apply."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    data = body.model_dump(exclude_unset=True)
    allowed = {
        "title", "description", "notes", "source_url", "source_site",
        "license", "category", "tags", "custom_attributes", "nsfw",
        "needs_review", "thumbnail_url",
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
            if key == "tags" and isinstance(value, list):
                value = list(dict.fromkeys(t.strip().lower() for t in value if t.strip()))
            setattr(model, key, value)

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


@router.patch("/{model_id}/queue")
def set_queue(model_id: int, body: QueueUpdate, db: Session = Depends(get_db)):
    """Add/remove a model from the print queue. New items append to the end of the
    manual order (favorites still float to the top at display time)."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    model.in_queue = body.in_queue
    if body.in_queue:
        model.queued_at = utcnow()
        max_pos = db.query(func.max(Model.queue_position)).filter(Model.in_queue == True).scalar()
        model.queue_position = (max_pos or 0) + 1
    else:
        model.queued_at = None
        model.queue_position = None
    db.commit()
    return {"ok": True, "in_queue": model.in_queue}


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


@router.patch("/{model_id}/printed")
def set_printed(model_id: int, body: PrintedUpdate, db: Session = Depends(get_db)):
    """Mark a model printed (clears the queue) or un-mark it."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if body.printed:
        model.printed_at = utcnow()
        # Marking printed removes it from the active queue.
        model.in_queue = False
        model.queued_at = None
    else:
        model.printed_at = None
    db.commit()
    return {"ok": True, "printed_at": model.printed_at}


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
        model.in_queue = False
        model.queued_at = None
        model.queue_position = None
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


@router.post("/{model_id}/set-group")
def set_group(model_id: int, body: SetGroupBody, db: Session = Depends(get_db)):
    """Assign a model to a specific character group (or explicitly ungroup it).
    The override is persisted so it survives rescans. Also updates model.character
    immediately so the change takes effect without waiting for a rescan.
    Returns 409 if a scan is running — the scan would overwrite character on commit."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")

    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    character = body.character.strip() if body.character and body.character.strip() else None

    # Atomic upsert — avoids a TOCTOU race if two requests arrive simultaneously.
    stmt = (
        _sqlite_insert(GroupOverride)
        .values(path=model.folder_path, character=character)
        .on_conflict_do_update(index_elements=["path"], set_={"character": character})
    )
    db.execute(stmt)

    model.character = character
    model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "character": character}


@router.delete("/{model_id}/set-group")
def clear_group(model_id: int, db: Session = Depends(get_db)):
    """Remove a group override, restoring heuristic grouping on the next rescan.
    Clears model.character immediately so the UI reflects the removed override
    (the heuristic value is unknown until the next scan)."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    deleted = db.query(GroupOverride).filter(GroupOverride.path == model.folder_path).delete()
    model.character = None
    model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "deleted": deleted > 0}


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
    nsfw: bool | None = None,
    is_favorite: bool | None = None,
    in_queue: bool | None = None,
    printed: bool | None = None,
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
        has_thumbnail=has_thumbnail, needs_review=needs_review,
        nsfw=nsfw, is_favorite=is_favorite, in_queue=in_queue,
        printed=printed, excluded=excluded, added_within_days=added_within_days,
    )

    target_id = model_id
    if group_variants:
        q, rep_by_nonrep = _collapse_variants(q)
        target_id = rep_by_nonrep.get(model_id, model_id)

    ids = [row[0] for row in q.with_entities(Model.id).order_by(*_order_cols(sort)).all()]
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
    override = db.query(GroupOverride).filter(GroupOverride.path == model.folder_path).first()
    if override:
        result.has_group_override = True
        result.group_override = override.character
    return result

"""Core model listing, detail, and CRUD endpoints (prefix `/models`).

Tag, group, print-queue, and thumbnail endpoints live in sibling routers
(tags.py, groups.py, print_queue.py, thumbnails.py) after STUDIO-58 split this
1400-line module up. This router owns the `/{model_id}` catch-all routes, so it
must be included LAST in create_app — otherwise `GET /{model_id}` would shadow
literal paths like `/grouping-strategy` on the sibling routers.
"""
import logging
import os
import shutil
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, exists, select, case, cast, String
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Model, Creator, ModelTag, CollectionModel, ScanRoot, STLFile, VariantGroup
from app.schemas import (
    ModelList, ModelRead, ModelDetail, CreatorRead,
    ModelUpdate, STLFileUpdate, BulkDeleteRequest, BulkDeleteResponse,
)
from app.services.thumbnails import ThumbnailDownloadError, download_thumbnail
from app.services.variant_sync import propagate_source_url
from app.services.tag_sync import sync_model_tags
from app.services.scanner import resolve_creator
from app.config import settings
from app.utils import utcnow, like_escape

_log = logging.getLogger(__name__)

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
        q = q.filter(Model.character.ilike(f"%{like_escape(character)}%", escape="\\"))

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
            except OSError as exc:
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

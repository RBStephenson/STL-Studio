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
from dataclasses import dataclass
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, exists, select, case, cast, String
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Model, Creator, ModelTag, CollectionModel, ScanRoot, STLFile, VariantGroup
from app.schemas import (
    ModelList, ModelRead, ModelDetail, CreatorRead, CreatorCreate,
    ModelUpdate, STLFileUpdate, BulkDeleteRequest, BulkDeleteResponse,
    AiOrganizeRequest, AiOrganizeResult, AiOrganizeSuggestion,
    AiOrganizeSuggestionPreview, AiOrganizePreviewResult,
    AiOrganizeApplyRequest, OtherFileDeleteRequest,
)
from app.services.path_guard import is_within_roots
from app.services.thumbnails import ThumbnailDownloadError, download_thumbnail
from app.services.variant_sync import propagate_source_url
from app.services.tag_sync import sync_model_tags
from app.services import ai_organize, reorganize
from app.services.reorganize_template import ReorganizeTemplateError
from app.services.scanner import resolve_creator
from app.routers.reorganize import _stored_template, _slugify_all, _slugify_filenames
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
        like = f"%{like_escape(search)}%"
        q = q.filter(
            Model.title.ilike(like, escape="\\")
            | Model.name.ilike(like, escape="\\")
            | Model.description.ilike(like, escape="\\")
            | Model.character.ilike(like, escape="\\")
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


def _sort_order_cols(sort: str) -> tuple:
    """Return the ORDER BY columns for `sort`, including the `creator` case.

    Split out from `_apply_sort` so `get_neighbors` can feed the identical
    column list into a LAG/LEAD `over(order_by=...)` window instead of
    duplicating the sort-key logic (#86)."""
    if sort == "creator":
        return (Creator.name.is_(None), Creator.name, Model.character, Model.name)
    return _order_cols(sort)


def _apply_sort(q, sort: str):
    """Order a Model query by the given sort key, handling joins where needed.

    Centralized so list_models and neighbors stay in lockstep (Prev/Next must
    walk the same order the grid shows). `creator` sorts alphabetically by the
    related Creator name — models with no creator sort last — then falls back to
    the default character/name order within a creator. Everything else delegates
    to the column-only `_order_cols`.
    """
    if sort == "creator":
        q = q.outerjoin(Creator, Model.creator_id == Creator.id)
    return q.order_by(*_sort_order_cols(sort))


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


@router.post("/creators", response_model=CreatorRead, status_code=201)
def create_creator(body: CreatorCreate, db: Session = Depends(get_db)):
    """Add a creator manually (no models required). Same case-insensitive
    dedup rule as resolve_creator(), so this can't fork a duplicate row that a
    later scan/enrich would otherwise resolve to. Best-effort creates the
    creator's library directory on disk; a failure there never fails the
    request, since the creator row is the source of truth."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Creator name is required")
    existing = db.query(Creator).filter(func.lower(Creator.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Creator '{existing.name}' already exists")

    creator = Creator(name=name, source_url=body.source_url)
    db.add(creator)
    db.commit()
    db.refresh(creator)

    try:
        target = reorganize.creator_scan_dir(
            db, _stored_template(db, None), name, slugify=_slugify_all(db)
        )
        if target:
            os.makedirs(target, exist_ok=True)
    except (OSError, ReorganizeTemplateError) as e:
        _log.warning("Could not create library directory for creator %r: %s", name, e)

    result = CreatorRead.model_validate(creator)
    result.model_count = 0
    return result


def _stat_count(condition):
    """A single conditional-sum column for model_stats' one-pass query."""
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


@router.get("/stats")
def model_stats(db: Session = Depends(get_db)):
    # STUDIO-89: a single pass over the table with conditional sums, instead of
    # 8 independent count() queries. All counts (other than `excluded` itself)
    # ignore user-excluded models so the stats match the visible grid.
    not_excluded = Model.excluded == False
    row = db.query(
        _stat_count(not_excluded).label("total"),
        _stat_count(not_excluded & (Model.needs_review == True)).label("needs_review"),
        _stat_count(
            not_excluded & (Model.thumbnail_path == None) & (Model.thumbnail_url == None)
        ).label("no_thumbnail"),
        _stat_count(not_excluded & (Model.is_favorite == True)).label("favorites"),
        _stat_count(not_excluded & (Model.print_status == "queued")).label("queued"),
        _stat_count(not_excluded & (Model.print_status == "printing")).label("printing"),
        _stat_count(not_excluded & (Model.print_status == "printed")).label("printed"),
        _stat_count(Model.excluded == True).label("excluded"),
    ).one()
    return {
        "total": row.total, "needs_review": row.needs_review, "no_thumbnail": row.no_thumbnail,
        "favorites": row.favorites, "queued": row.queued, "printing": row.printing,
        "printed": row.printed, "excluded": row.excluded,
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
    if f.model.locked:
        raise HTTPException(status_code=409, detail="This model is locked (organized) — unlock it to edit its files")
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


@dataclass
class _OrganizeConfig:
    """Resolved organizer endpoint. A dataclass (not a tuple) so the secret
    ``api_key`` field stays isolated under static analysis — packing it into a
    tuple alongside the URL spreads its taint to every element on unpack and
    trips CodeQL's clear-text-logging query even though the key is never logged."""
    url: str
    model: str
    api_key: str
    timeout: int
    api_type: str
    effort: str | None
    batch_size: int | None
    reasoning_enabled: bool


def _load_organize_config(db) -> "_OrganizeConfig":
    """Resolve the AI organizer's endpoint. Raises HTTPException on misconfiguration.

    The organizer is driven by a named AiApiConfig assigned via the
    ``ai_organize_api`` setting (the "Use API" selector in the UI); both
    OpenAI-compatible (e.g. Ollama) and Anthropic connections are supported. For
    backward compatibility with installs that predate named configs, it falls
    back to the legacy ``ai_organize_url`` / ``ai_organize_model`` app_settings
    when no config is assigned.
    """
    from app.models import AppSetting, AiApiConfig
    from app.services import secrets as _secrets

    enabled_row = db.get(AppSetting, "ai_organize_enabled")
    if not enabled_row or not bool(enabled_row.value):
        raise HTTPException(status_code=400, detail="AI organizer is not enabled")

    # Preferred path: a named AiApiConfig assigned to the organize function.
    api_row = db.get(AppSetting, "ai_organize_api")
    config_id = api_row.value if api_row else None
    if config_id:
        cfg = db.get(AiApiConfig, int(config_id))
        if not cfg:
            raise HTTPException(
                status_code=400,
                detail="The AI API assigned to organizing no longer exists — reselect one in Settings.",
            )
        key = _secrets.get_ai_api_config_key(db, cfg.id) or ""
        if cfg.api_type == "anthropic":
            if not cfg.model:
                raise HTTPException(
                    status_code=400,
                    detail="The Anthropic API assigned to organizing has no model selected.",
                )
            return _OrganizeConfig("", cfg.model, key, cfg.request_timeout, "anthropic", cfg.effort, cfg.batch_size, False)
        # OpenAI-compatible (Ollama, LM Studio, …).
        if not cfg.url:
            raise HTTPException(
                status_code=400,
                detail="This OpenAI-compatible API has no URL set — add one in Settings.",
            )
        return _OrganizeConfig(cfg.url, cfg.model or "", key, cfg.request_timeout, "openai", None, cfg.batch_size, cfg.reasoning_enabled)

    # Legacy fallback: standalone ai_organize_* app_settings.
    url_row = db.get(AppSetting, "ai_organize_url")
    model_row = db.get(AppSetting, "ai_organize_model")
    return _OrganizeConfig(
        url_row.value if url_row else "",
        model_row.value if model_row else "",
        _secrets.get_organize_api_key(db) or "",
        10,
        "openai",
        None,
        None,
        False,
    )


def _snap_within(suggested: str, cats: list[str]) -> str | None:
    """Exact (case-insensitive) match, then singular/plural fuzzy match,
    against a single candidate list — shared by both passes in
    _normalize_type below."""
    low = suggested.lower()
    for cat in cats:
        if cat.lower() == low:
            return cat
    for cat in cats:
        cl = cat.lower()
        if cl == low + "s" or cl == low + "es":
            return cat
        if low.endswith("y") and cl == low[:-1] + "ies":
            return cat
        if low == cl + "s" or low == cl + "es":
            return cat
        if cl.endswith("y") and low == cl[:-1] + "ies":
            return cat
    return None


def _normalize_type(suggested: str, existing: list[str]) -> str:
    """Snap a suggested category to the closest existing one.

    Handles case differences and singular/plural variants so the AI's "Accessory"
    maps to an existing "Accessories" (and vice-versa) rather than creating a
    duplicate category with a slightly different name.

    Canonical categories (ai_organize.CANONICAL_PART_TYPES) are checked
    before any other already-in-DB category (#963): a stale, non-canonical
    value left behind by an earlier bug — e.g. "Hand" applied before this
    normalization existed — must never "shadow" the real canonical match
    ("Hands") just because it happens to already be sitting in the database.
    Without this split, "Hand" would exact-match itself in `existing` and
    never reach the singular/plural check that maps it to "Hands".
    """
    if not existing:
        return suggested
    canonical_hit = _snap_within(suggested, ai_organize.CANONICAL_PART_TYPES)
    if canonical_hit:
        return canonical_hit
    return _snap_within(suggested, existing) or suggested


# User-facing copy for LLM outcomes that aren't a technical error (which
# already carries its own detail). AI Organize is success-via-API-or-nothing
# (#821): heuristic-derived suggestions are never presented as if the AI
# produced them, so every non-"ok" status returns zero suggestions and one of
# these explanations instead.
_LLM_STATUS_MESSAGES = {
    "disabled": "AI Organize has no API configured. Assign one under Settings → AI & Integrations.",
    "skipped": "The AI wasn't called — this model has no files to send it (only pre-supported variants, which inherit their base file's category).",
}


@router.post("/{model_id}/ai-organize", response_model=AiOrganizePreviewResult)
def ai_organize_model(model_id: int, body: AiOrganizeRequest = AiOrganizeRequest(), db: Session = Depends(get_db)):
    """Call the AI organizer and return suggestions without writing to the DB.

    Suggestions are only returned when the AI call actually succeeded
    (``llm_status == "ok"``) — heuristic-only results are never silently
    substituted, so the client can trust that a non-empty response means the
    AI genuinely ran (#821). The client reviews, optionally edits, then calls
    /ai-organize/apply.

    ``body.strategy`` (#878): "parts" (default) categorizes by physical part
    type, snapped to the canonical list below. "unit" groups by in-game
    unit/character instead — those suggestions are freeform (already
    Pascal-cased by the service) and skip the canonical-list snap, since
    there's no fixed list of unit names to snap to. "link_sups" (#967) is a
    pure heuristic, no LLM/API involved at all — it matches a currently-
    unlinked sup/supported/hollowed-named file to its likely base part by
    name; unlike the other two strategies it works even with no AI API
    configured (the config load below is skipped entirely for it).
    """
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if not model.stl_files:
        raise HTTPException(status_code=400, detail="Model has no STL files to organize")

    file_dicts = [
        {"id": f.id, "filename": f.filename, "part_type": f.part_type,
         "part_name": f.part_name, "sup_of_id": f.sup_of_id}
        for f in model.stl_files
    ]
    by_filename = {f.filename: f.id for f in model.stl_files}
    by_id_filename = {f.id: f.filename for f in model.stl_files}

    if body.strategy == "link_sups":
        organize_result = ai_organize.run(file_dicts, "", "", "", strategy="link_sups")
    else:
        org_cfg = _load_organize_config(db)

        # Collect all category names AI suggestions should snap to: the app's
        # fixed canonical list (so a fresh library still gets clean names, not
        # just whatever's already stored) plus any custom categories already in
        # this library (e.g. "Accessory" → "Accessories"). Unit-based suggestions
        # are freeform and never snapped, so this list is unused for that strategy.
        existing_types: list[str] = sorted(set(ai_organize.CANONICAL_PART_TYPES) | {
            row[0] for row in
            db.query(STLFile.part_type).filter(STLFile.part_type.isnot(None)).distinct().all()
        })

        try:
            organize_result = ai_organize.run(
                file_dicts, org_cfg.url, org_cfg.model, org_cfg.api_key,
                timeout=org_cfg.timeout, api_type=org_cfg.api_type, effort=org_cfg.effort,
                strategy=body.strategy, batch_size=org_cfg.batch_size,
                reasoning_enabled=org_cfg.reasoning_enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    llm = organize_result.llm
    if llm.status != "ok":
        return AiOrganizePreviewResult(
            suggestions=[],
            llm_status=llm.status,
            llm_detail=llm.detail or _LLM_STATUS_MESSAGES.get(llm.status),
        )

    raw = organize_result.suggestions
    if body.strategy == "parts":
        for s in raw:
            if s.get("part_type"):
                s["part_type"] = _normalize_type(s["part_type"], existing_types)

    previews: list[AiOrganizeSuggestionPreview] = []
    for s in raw:
        file_id = s.get("id")
        if not isinstance(file_id, int) or file_id not in by_id_filename:
            continue
        sup_base_filename = s.get("sup_base_filename") or None
        resolved_sup_id: int | None = None
        if sup_base_filename:
            cand = by_filename.get(sup_base_filename)
            if cand and cand != file_id:
                resolved_sup_id = cand
        previews.append(AiOrganizeSuggestionPreview(
            id=file_id,
            filename=by_id_filename[file_id],
            part_type=s.get("part_type") or None,
            part_name=s.get("part_name") or None,
            sup_of_id=resolved_sup_id,
            sup_base_filename=sup_base_filename if resolved_sup_id else None,
        ))

    return AiOrganizePreviewResult(
        suggestions=previews,
        llm_status=organize_result.llm.status,
        llm_detail=organize_result.llm.detail,
    )


@router.post("/{model_id}/ai-organize/apply", response_model=AiOrganizeResult)
def ai_organize_apply(model_id: int, body: AiOrganizeApplyRequest, db: Session = Depends(get_db)):
    """Apply user-confirmed AI suggestions to the model's STL files."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.locked:
        raise HTTPException(status_code=409, detail="This model is locked (organized) — unlock it to apply changes")

    by_id = {f.id: f for f in model.stl_files}

    applied: list[AiOrganizeSuggestion] = []
    for item in body.items:
        f = by_id.get(item.id)
        if not f:
            continue
        if item.part_type is not None:
            f.part_type = item.part_type.strip() or None
        if item.part_name is not None:
            f.part_name = item.part_name.strip() or None
        if item.sup_of_id is not None:
            target = by_id.get(item.sup_of_id)
            if target and target.id != f.id:
                f.sup_of_id = target.id
        elif item.sup_of_id is None and "sup_of_id" in item.model_fields_set:
            f.sup_of_id = None
        applied.append(AiOrganizeSuggestion(
            id=f.id,
            part_type=f.part_type,
            part_name=f.part_name,
            sup_of_id=f.sup_of_id,
        ))

    db.commit()
    return AiOrganizeResult(
        applied=applied,
        message=f"Applied changes to {len(applied)} file(s).",
    )


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
        unsafe = [p for p in folder_paths if not is_within_roots(p, roots)]
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
        "removed_image_paths",
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
            elif key == "removed_image_paths" and isinstance(value, list):
                value = list(dict.fromkeys(p for p in value if isinstance(p, str) and p))
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


@router.delete("/{model_id}/other-files")
def delete_other_file(model_id: int, body: OtherFileDeleteRequest, db: Session = Depends(get_db)):
    """Delete one entry from a model's other_files, on disk and in the DB (#880).

    Best-effort on disk: a file that's already gone (e.g. removed outside the
    app) still gets cleared from other_files rather than leaving a stale
    listing behind — that mismatch is the actual bug this endpoint fixes.
    """
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    other_files = model.other_files or []
    if body.path not in other_files:
        raise HTTPException(status_code=404, detail="File not found on this model")

    roots = [os.path.realpath(r.path) for r in db.query(ScanRoot).all()]
    if not is_within_roots(body.path, roots):
        raise HTTPException(status_code=400, detail="File is outside known scan roots")

    try:
        os.remove(body.path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not delete file: {exc}")

    model.other_files = [p for p in other_files if p != body.path]
    model.updated_at = utcnow()
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

    # Bounded query (#86): let SQL compute the adjacent IDs via LAG/LEAD over the
    # same ordering list_models uses, instead of materializing every filtered ID
    # into Python and scanning for the target with .index(). Only ever returns
    # the single row for target_id.
    if sort == "creator":
        q = q.outerjoin(Creator, Model.creator_id == Creator.id)
    order_cols = _sort_order_cols(sort)
    ranked = q.with_entities(
        Model.id.label("id"),
        func.lag(Model.id).over(order_by=order_cols).label("prev_id"),
        func.lead(Model.id).over(order_by=order_cols).label("next_id"),
    ).subquery()

    row = (
        db.query(ranked.c.prev_id, ranked.c.next_id)
        .filter(ranked.c.id == target_id)
        .first()
    )
    if row is None:
        return {"prev_id": None, "next_id": None}

    return {"prev_id": row.prev_id, "next_id": row.next_id}


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

    try:
        template = _stored_template(db, None)
        manifest = reorganize.build_manifest(
            db, template, model_ids=[model.id], slugify_all=_slugify_all(db),
            slugify_filenames=_slugify_filenames(db),
        )
        entry = manifest.entries[0] if manifest.entries else None
        result.unorganized = bool(entry and entry.kind != "in_place")
    except ReorganizeTemplateError as e:
        _log.warning("Could not compute organize status for model %s: %s", model_id, e)

    return result

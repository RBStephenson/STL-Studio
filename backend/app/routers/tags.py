"""Tag management and bulk metadata endpoints, split out of the models router
(STUDIO-58). Paths are unchanged (prefix `/models`)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Model, ModelTag
from app.schemas import BulkTagUpdate, BulkEnrichUpdate, TagRenameBody, TagMergeBody
from app.services.tag_sync import bulk_sync_model_tags
from app.services import scanner
from app.services.scanner import resolve_creator
from app.services.variant_sync import propagate_source_url
from app.utils import utcnow

router = APIRouter(prefix="/models", tags=["models"])


def _suppress_auto_tag(model: Model, tag: str) -> None:
    """Suppress `tag` on this model if the scanner applied it (auto_tags).

    model_tags rows regenerate from auto_tags on every sync, so merely
    removing a tag from model.tags can't make an auto-applied tag go away —
    it resurrects on the next sync (STUDIO-328). removed_auto_tags is the
    existing suppression list _tag_map_for already honors; recording the tag
    there is what actually deletes an auto tag."""
    autos = {a.strip().lower() for a in (model.auto_tags or []) if a.strip()}
    if tag in autos:
        removed = list(model.removed_auto_tags or [])
        if tag not in removed:
            model.removed_auto_tags = removed + [tag]


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
def rename_tag(body: TagRenameBody, db: Session = Depends(get_db)):
    """Rename a tag on all models that carry it."""
    old = body.old_tag.strip().lower()
    new = body.new_tag.strip().lower()
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
        # The model may carry `old` only as an auto tag (that's how it joined
        # `affected` at all) — suppress the auto tag and promote the renamed
        # value to a user tag, otherwise the rename silently no-ops and the
        # old tag resurrects on the next sync (STUDIO-328).
        _suppress_auto_tag(model, old)
        if new not in tags:
            tags.append(new)
        model.tags = tags
        model.updated_at = utcnow()
    bulk_sync_model_tags(affected, db)
    db.commit()
    return {"ok": True, "updated": len(affected)}


@router.post("/tags/merge")
def merge_tags(body: TagMergeBody, db: Session = Depends(get_db)):
    """Merge source_tag into target_tag: all models get target_tag, source_tag removed."""
    source = body.source_tag.strip().lower()
    target = body.target_tag.strip().lower()
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
        tags = [t for t in (model.tags or []) if t != source]
        # Same auto-tag handling as rename (STUDIO-328): the model may carry
        # `source` only as an auto tag — suppress it and make sure the target
        # lands as a user tag either way.
        _suppress_auto_tag(model, source)
        if target not in tags:
            tags.append(target)
        model.tags = tags
        model.updated_at = utcnow()
    bulk_sync_model_tags(affected, db)
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
        # Auto tags resurrect from auto_tags on the next sync unless
        # suppressed (STUDIO-328) — this is what actually deletes them.
        _suppress_auto_tag(model, tag)
        model.updated_at = utcnow()
    bulk_sync_model_tags(affected, db)
    db.commit()
    return {"ok": True, "updated": len(affected)}


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
            # Removing an auto-applied tag must suppress it, not just drop it
            # from user tags — otherwise it resurrects on sync (STUDIO-328).
            for t in remove_set:
                _suppress_auto_tag(model, t)
        model.tags = current
        model.updated_at = utcnow()

    bulk_sync_model_tags(models_to_update, db)
    db.commit()
    return {"ok": True, "updated": len(models_to_update)}


@router.patch("/bulk/enrich")
def bulk_enrich_models(body: BulkEnrichUpdate, db: Session = Depends(get_db)):
    """Set creator, title, notes, source_url, and/or source_site across multiple
    models in one request. Any field omitted from the payload is left unchanged
    on each model. Grouping (character/variant_group) is not editable here
    (#678 Phase 5) — use the durable-group merge/split/patch endpoints instead."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="No model IDs provided")
    # Trim before validation: a whitespace-only creator_name is truthy but must
    # not create a blank-named Creator (#439).
    creator_name = body.creator_name.strip() if body.creator_name is not None else None
    if body.creator_name is not None and not creator_name:
        raise HTTPException(status_code=400, detail="Creator name cannot be blank")
    if not any([
        creator_name, body.title is not None, body.notes is not None,
        body.source_url is not None, body.source_site is not None,
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
        if body.source_site is not None:
            model.source_site = body.source_site.strip() or None
        model.updated_at = utcnow()
    db.commit()
    if creator_id is not None:
        # Reassigning a model's creator can leave its old one with zero
        # models — most commonly the single-pack import placeholder creator
        # (named after the pack folder) once the user sets the real name
        # here (#1108). A global sweep, same as the post-scan prune —
        # cheap, and scoping it to "creators these models used to have"
        # would need capturing old creator_ids before the loop above for no
        # real benefit.
        scanner.prune_empty_creators(db)
    return {"ok": True, "updated": len(models_to_update)}

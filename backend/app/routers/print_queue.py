"""Print-queue, print-status, rating, favorite and exclude endpoints, split out
of the models router (STUDIO-58). Paths are unchanged (prefix `/models`)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Model
from app.schemas import (
    BulkExcludeUpdate, BulkReviewUpdate, FavoriteUpdate, RatingUpdate,
    QueueReorder, PrintStatusUpdate, ExcludeUpdate,
)
from app.utils import utcnow


router = APIRouter(prefix="/models", tags=["models"])


def _clear_queue_state(model) -> None:
    """Drop a model out of the active print queue without touching print history.

    A queued/printing model reverts to 'none' and loses its queue ordering; a
    printed model keeps its 'printed' status, printed_at and print_count.
    """
    if model.print_status in ("queued", "printing"):
        model.print_status = "none"
    model.queued_at = None
    model.queue_position = None


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
            # Computed server-side in the UPDATE itself (not read-then-write in
            # Python) so two concurrent requests can't both read the same max
            # and collide on the same position (STUDIO-25).
            next_pos = (
                select(func.coalesce(func.max(Model.queue_position), 0) + 1)
                .where(Model.print_status == "queued")
                .scalar_subquery()
            )
            model.queue_position = next_pos
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

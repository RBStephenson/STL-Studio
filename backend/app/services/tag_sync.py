"""
Tag index maintenance.

model_tags is a denormalized index derived from models.tags and models.auto_tags.
Call sync_model_tags() after any write that modifies either column.
Call rebuild_all_tags() once at startup when migrating from JSON-only storage.
"""
import logging
from sqlalchemy.orm import Session

from app.models import Model, ModelTag

logger = logging.getLogger(__name__)


def _tag_map_for(model: Model) -> dict[str, bool]:
    """Map each effective tag -> is_auto for a model.

    Auto-tags the user has suppressed (removed_auto_tags) are dropped, but a
    user tag with the same name always wins and is kept (is_auto=False).
    """
    removed = {r.strip().lower() for r in (model.removed_auto_tags or []) if r.strip()}
    tag_map: dict[str, bool] = {}  # tag -> is_auto
    for raw in (model.auto_tags or []):
        t = raw.strip().lower()
        if t and t not in removed:
            tag_map[t] = True
    for raw in (model.tags or []):
        t = raw.strip().lower()
        if t:
            tag_map[t] = False  # user tag wins
    return tag_map


def _write_model_tags(model: Model, db: Session) -> int:
    """Insert ModelTag rows for one model from its effective tag map. Returns the row count."""
    rows = 0
    for tag, is_auto in _tag_map_for(model).items():
        db.add(ModelTag(model_id=model.id, tag=tag, is_auto=is_auto))
        rows += 1
    return rows


def sync_model_tags(model: Model, db: Session) -> None:
    """Rebuild model_tags rows for a single model from its JSON tag columns."""
    db.query(ModelTag).filter(ModelTag.model_id == model.id).delete(synchronize_session=False)
    _write_model_tags(model, db)


def bulk_sync_model_tags(models: list[Model], db: Session) -> None:
    """Rebuild model_tags rows for multiple models in one delete pass then one
    insert pass. Use instead of calling sync_model_tags in a loop when updating
    many models at once."""
    if not models:
        return
    ids = [m.id for m in models]
    # Load existing rows so the session tracks their deletion properly,
    # then flush before inserting to avoid unique-constraint collisions.
    old_rows = db.query(ModelTag).filter(ModelTag.model_id.in_(ids)).all()
    for row in old_rows:
        db.delete(row)
    db.flush()
    new_rows = [
        ModelTag(model_id=model.id, tag=tag, is_auto=is_auto)
        for model in models
        for tag, is_auto in _tag_map_for(model).items()
    ]
    if new_rows:
        db.add_all(new_rows)


def rebuild_all_tags(db: Session) -> int:
    """Full rebuild of model_tags from all models. Returns number of tag rows inserted."""
    logger.info("Rebuilding model_tags index…")
    db.query(ModelTag).delete(synchronize_session=False)
    db.flush()

    count = 0
    batch_size = 500
    offset = 0

    while True:
        # Ordered pagination: OFFSET over an unordered query can skip or
        # repeat rows between batches, silently dropping tag rows mid-rebuild.
        models = db.query(Model).order_by(Model.id).offset(offset).limit(batch_size).all()
        if not models:
            break
        for model in models:
            count += _write_model_tags(model, db)
        db.flush()
        offset += batch_size

    db.commit()
    logger.info(f"model_tags rebuild complete: {count} rows")
    return count

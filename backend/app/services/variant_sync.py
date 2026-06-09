"""Sync helpers across a variant group (models sharing creator_id + character)."""
from sqlalchemy.orm import Session

from app.models import Model


def propagate_source_url(db: Session, model: Model) -> int:
    """Copy model.source_url/source_site to same-group siblings lacking one.

    Variants of one character are almost always sold from a single store
    listing, so a URL set on any variant applies to its siblings. Siblings
    with an existing different URL are left alone (intentional per-variant
    overrides). Returns the number of siblings updated. The caller commits.
    """
    if not (model.source_url and model.creator_id and model.character):
        return 0
    return (
        db.query(Model)
        .filter(
            Model.creator_id == model.creator_id,
            Model.character == model.character,
            Model.id != model.id,
            # The metadata editor saves cleared fields as "" rather than NULL.
            (Model.source_url == None) | (Model.source_url == ""),  # noqa: E711
        )
        .update(
            {"source_url": model.source_url, "source_site": model.source_site},
            synchronize_session=False,
        )
    )

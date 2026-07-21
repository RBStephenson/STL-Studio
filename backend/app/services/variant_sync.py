"""Sync helpers across a variant group (models sharing variant_group_id)."""
from sqlalchemy.orm import Session

from app.models import Model


def propagate_source_url(db: Session, model: Model) -> int:
    """Copy model.source_url/source_site to same-group siblings lacking one.

    Variants of one durable group (#678) are almost always sold from a single
    store listing, so a URL set on any variant applies to its siblings.
    Siblings with an existing different URL are left alone (intentional
    per-variant overrides). Ungrouped models (variant_group_id is None)
    propagate to no one — character was the pre-#678 grouping key and two
    distinct durable groups can legitimately share a character (e.g. a bust
    split from a 75mm figure), so falling back to it here would silently
    reach models outside the group being edited (STUDIO-304). Returns the
    number of siblings updated. The caller commits.
    """
    if not (model.source_url and model.variant_group_id):
        return 0
    return (
        db.query(Model)
        .filter(
            Model.variant_group_id == model.variant_group_id,
            Model.id != model.id,
            # The metadata editor saves cleared fields as "" rather than NULL.
            (Model.source_url == None) | (Model.source_url == ""),  # noqa: E711
        )
        .update(
            {"source_url": model.source_url, "source_site": model.source_site},
            synchronize_session=False,
        )
    )

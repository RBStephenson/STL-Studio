"""Unique (paint_line_id, code) on paints (#442/#445)

Duplicate (paint_line_id, code) identities could be produced by PaintRack CSV
import (repeated SKUs) and by paint update (editing/moving a code), making
shelf lookup and CSV sync ambiguous. This adds a uniqueness barrier.

create_all (run at startup before migrations on fresh DBs) already builds the
constraint from the model's __table_args__, so this revision only matters for
already Alembic-stamped DBs. Existing duplicates would make a plain unique
index creation fail, so any are first disambiguated by suffixing the code of
the later rows — preserving every row (deleting would orphan guide swatch/mix
references).

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_INDEX = "uq_paints_line_code"


def _dedupe(bind) -> None:
    """Make any existing duplicate (paint_line_id, code) rows unique by
    suffixing the code of all but the lowest-id row in each group."""
    dupe_groups = bind.execute(sa.text(
        "SELECT paint_line_id, code FROM paints "
        "GROUP BY paint_line_id, code HAVING COUNT(*) > 1"
    )).fetchall()
    for line_id, code in dupe_groups:
        ids = [r[0] for r in bind.execute(sa.text(
            "SELECT id FROM paints WHERE paint_line_id = :l AND code = :c ORDER BY id"
        ), {"l": line_id, "c": code}).fetchall()]
        # Keep the first; suffix the rest so the unique index can build.
        for pid in ids[1:]:
            bind.execute(sa.text(
                "UPDATE paints SET code = :c WHERE id = :id"
            ), {"c": f"{code}__dup{pid}", "id": pid})


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("paints")}
    # create_all on a fresh DB already added the constraint; skip to stay
    # idempotent.
    if _INDEX in existing:
        return
    _dedupe(bind)
    op.create_index(_INDEX, "paints", ["paint_line_id", "code"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="paints")

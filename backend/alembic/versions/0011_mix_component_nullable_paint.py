"""Nullable paint_id + name on guide_mix_components (#425, Option B)

A mix component that doesn't resolve to a shelf paint (a medium, or a
back-reference to a prior step's result) is kept as a name-only row instead of
being dropped, so the mix relationship + ratio round-trip. Relaxes the NOT NULL
on paint_id (SQLite needs a table rebuild → batch mode) and adds the name column.
create_all handles fresh DBs; this brings already Alembic-stamped DBs up to date.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"]: c for c in inspector.get_columns("guide_mix_components")}
    with op.batch_alter_table("guide_mix_components") as batch:
        if "name" not in cols:
            batch.add_column(sa.Column("name", sa.String(), nullable=True))
        if cols.get("paint_id", {}).get("nullable") is False:
            batch.alter_column("paint_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("guide_mix_components") as batch:
        batch.alter_column("paint_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("name")

"""Verbatim tab-level blocks for lossless round-trip (#271)

Adds guide_tabs.raw_blocks — unmodelled tab-level blocks (e.g. wargaming
batch-stage / tier-card / trouble-grid) captured verbatim so they round-trip
without a dedicated schema. create_all handles fresh DBs; this brings
already Alembic-stamped DBs up to the same schema.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("guide_tabs")}
    if "raw_blocks" not in cols:
        op.add_column(
            "guide_tabs",
            sa.Column("raw_blocks", sa.JSON(), nullable=True, server_default="[]"),
        )


def downgrade() -> None:
    op.drop_column("guide_tabs", "raw_blocks")

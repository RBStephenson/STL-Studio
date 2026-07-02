"""Retire GroupOverride: add Model.no_group, backfill from null-character
overrides, drop group_overrides (#678 Phase 5)

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("models")}
    if "no_group" not in cols:
        with op.batch_alter_table("models") as batch:
            batch.add_column(
                sa.Column("no_group", sa.Boolean(), nullable=False, server_default="0")
            )

    if "group_overrides" in inspector.get_table_names():
        # Preserve the one surviving behavior before the table goes away:
        # character=None meant "explicitly ungrouped, sticky across rescans" —
        # migrate that onto the new column. Non-null character rows had no
        # further durable-grouping effect after #678 Phases 1-4 landed, so
        # they're dropped along with the table.
        bind.execute(
            sa.text(
                "UPDATE models SET no_group = 1 WHERE folder_path IN "
                "(SELECT path FROM group_overrides WHERE character IS NULL)"
            )
        )
        op.drop_table("group_overrides")


def downgrade() -> None:
    # Data + schema migration — no safe automatic recreation of group_overrides
    # rows (the non-null character rows were never round-trippable anyway).
    pass

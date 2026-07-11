"""Add models.locked (#978)

Shown as "Locked" in the UI. Not just a status label: while set, no
process may alter this model's STL files, categories, or part names, or
move/rename them via Reorganize. create_all handles fresh DBs; this brings
already Alembic-stamped DBs up to the same schema.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("models")}
    if "locked" not in cols:
        op.add_column(
            "models",
            sa.Column("locked", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.create_index("ix_models_locked", "models", ["locked"])


def downgrade() -> None:
    op.drop_index("ix_models_locked", table_name="models")
    op.drop_column("models", "locked")

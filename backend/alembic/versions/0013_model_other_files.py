"""Add other_files JSON column to models for non-STL, non-image pack files

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("models")}
    with op.batch_alter_table("models") as batch:
        if "other_files" not in cols:
            batch.add_column(sa.Column("other_files", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("models") as batch:
        batch.drop_column("other_files")

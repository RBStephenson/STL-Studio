"""add removed_image_paths to models

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("models")}
    if "removed_image_paths" not in cols:
        with op.batch_alter_table("models") as batch_op:
            batch_op.add_column(sa.Column("removed_image_paths", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("models")}
    if "removed_image_paths" in cols:
        with op.batch_alter_table("models") as batch_op:
            batch_op.drop_column("removed_image_paths")

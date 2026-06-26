"""Add primary_image_path to models

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("models") as batch_op:
        cols = [c["name"] for c in sa.inspect(op.get_bind()).get_columns("models")]
        if "primary_image_path" not in cols:
            batch_op.add_column(sa.Column("primary_image_path", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("models") as batch_op:
        batch_op.drop_column("primary_image_path")

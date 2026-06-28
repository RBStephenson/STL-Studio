"""Add parsed_attributes JSON column to models for scanner-detected variant attrs

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("models")}
    with op.batch_alter_table("models") as batch:
        if "parsed_attributes" not in cols:
            batch.add_column(sa.Column("parsed_attributes", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("models") as batch:
        batch.drop_column("parsed_attributes")

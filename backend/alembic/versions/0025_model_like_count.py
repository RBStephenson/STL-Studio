"""Add models.like_count (#699 1.2)

Store enrichment reports likes as `like_count`, no longer overwrites the
user-facing `rating` column with them. create_all handles fresh DBs; this
brings already Alembic-stamped DBs up to the same schema.

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("models")}
    if "like_count" not in cols:
        op.add_column("models", sa.Column("like_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("models", "like_count")

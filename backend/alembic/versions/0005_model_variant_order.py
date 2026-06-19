"""Manual variant ordering (#399)

Adds models.variant_order — the manual position of a model within its variant
group (NULL = heuristic order). create_all handles fresh DBs; this brings
already Alembic-stamped DBs up to the same schema.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("models")}
    # create_all (run at startup before migrations on fresh DBs) may have already
    # added it; skip to stay idempotent.
    if "variant_order" not in cols:
        op.add_column("models", sa.Column("variant_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("models", "variant_order")

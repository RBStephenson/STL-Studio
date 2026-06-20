"""Inbox flag for import-folder models (#428)

Adds models.is_inbox — set when a model was imported via the one-shot
import-folder flow rather than a permanent scan root. create_all handles
fresh DBs; this migration brings already-stamped DBs to the same schema.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("models")}
    if "is_inbox" not in cols:
        op.add_column(
            "models",
            sa.Column("is_inbox", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.create_index("ix_models_is_inbox", "models", ["is_inbox"])


def downgrade() -> None:
    op.drop_index("ix_models_is_inbox", table_name="models")
    op.drop_column("models", "is_inbox")

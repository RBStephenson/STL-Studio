"""add indexes for common model list filters (source_site, needs_review, source_last_fetched)

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("models")}
    if "ix_models_source_site" not in existing:
        op.create_index("ix_models_source_site", "models", ["source_site"])
    if "ix_models_needs_review" not in existing:
        op.create_index("ix_models_needs_review", "models", ["needs_review"])
    if "ix_models_source_last_fetched" not in existing:
        op.create_index("ix_models_source_last_fetched", "models", ["source_last_fetched"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("models")}
    if "ix_models_source_last_fetched" in existing:
        op.drop_index("ix_models_source_last_fetched", table_name="models")
    if "ix_models_needs_review" in existing:
        op.drop_index("ix_models_needs_review", table_name="models")
    if "ix_models_source_site" in existing:
        op.drop_index("ix_models_source_site", table_name="models")

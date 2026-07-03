"""add ai_api_configs table

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ai_api_configs" not in inspector.get_table_names():
        op.create_table(
            "ai_api_configs",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String, nullable=False),
            sa.Column("api_type", sa.String, nullable=False),
            sa.Column("url", sa.String, nullable=True),
            sa.Column("model", sa.String, nullable=False, server_default=""),
            sa.Column("effort", sa.String, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
        )


def downgrade() -> None:
    op.drop_table("ai_api_configs")

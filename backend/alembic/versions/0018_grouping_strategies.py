"""Add grouping_strategies table for per-subtree variant-grouping strategy

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "grouping_strategies" not in inspector.get_table_names():
        op.create_table(
            "grouping_strategies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("path", sa.String(), nullable=False),
            sa.Column("strategy", sa.String(), nullable=False, server_default="auto"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("path", name="uq_grouping_strategies_path"),
        )


def downgrade() -> None:
    op.drop_table("grouping_strategies")

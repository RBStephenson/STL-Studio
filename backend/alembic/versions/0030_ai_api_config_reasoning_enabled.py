"""add reasoning_enabled to ai_api_configs

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("ai_api_configs")}
    if "reasoning_enabled" not in cols:
        with op.batch_alter_table("ai_api_configs") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "reasoning_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("ai_api_configs")}
    if "reasoning_enabled" in cols:
        with op.batch_alter_table("ai_api_configs") as batch_op:
            batch_op.drop_column("reasoning_enabled")

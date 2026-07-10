"""add batch_size to ai_api_configs

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("ai_api_configs")}
    if "batch_size" not in cols:
        with op.batch_alter_table("ai_api_configs") as batch_op:
            batch_op.add_column(sa.Column("batch_size", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("ai_api_configs")}
    if "batch_size" in cols:
        with op.batch_alter_table("ai_api_configs") as batch_op:
            batch_op.drop_column("batch_size")

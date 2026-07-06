"""add request_timeout to ai_api_configs

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("ai_api_configs")}
    if "request_timeout" not in cols:
        with op.batch_alter_table("ai_api_configs") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "request_timeout",
                    sa.Integer(),
                    nullable=False,
                    server_default="10",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("ai_api_configs")}
    if "request_timeout" in cols:
        with op.batch_alter_table("ai_api_configs") as batch_op:
            batch_op.drop_column("request_timeout")

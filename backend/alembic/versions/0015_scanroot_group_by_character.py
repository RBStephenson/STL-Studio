"""Add group_by_character to scan_roots

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scan_roots") as batch_op:
        cols = [c["name"] for c in sa.inspect(op.get_bind()).get_columns("scan_roots")]
        if "group_by_character" not in cols:
            batch_op.add_column(
                sa.Column(
                    "group_by_character",
                    sa.Boolean(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("scan_roots") as batch_op:
        batch_op.drop_column("group_by_character")

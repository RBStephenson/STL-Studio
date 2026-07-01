"""Add part_name to stl_files

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = [c["name"] for c in sa.inspect(conn).get_columns("stl_files")]
    if "part_name" not in cols:
        conn.execute(sa.text("ALTER TABLE stl_files ADD COLUMN part_name TEXT"))


def downgrade() -> None:
    pass  # SQLite cannot drop columns

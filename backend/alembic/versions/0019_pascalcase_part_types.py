"""Normalise stl_files.part_type values to Pascal Case

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _to_pascal(value: str) -> str:
    return " ".join(w.capitalize() for w in value.split())


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, part_type FROM stl_files WHERE part_type IS NOT NULL AND part_type != ''")
    ).fetchall()
    for row in rows:
        pascal = _to_pascal(row.part_type)
        if pascal != row.part_type:
            conn.execute(
                sa.text("UPDATE stl_files SET part_type = :pt WHERE id = :id"),
                {"pt": pascal, "id": row.id},
            )


def downgrade() -> None:
    # Lossy — lowercase normalisation is not reversible
    pass

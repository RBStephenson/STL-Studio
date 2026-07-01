"""Add sup_of_id to stl_files; populate from filename pattern

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # SQLite supports ADD COLUMN directly; no batch_alter_table needed.
    cols = [c["name"] for c in sa.inspect(conn).get_columns("stl_files")]
    if "sup_of_id" not in cols:
        conn.execute(sa.text("ALTER TABLE stl_files ADD COLUMN sup_of_id INTEGER REFERENCES stl_files(id)"))

    # Auto-populate from Sup_X.stl / X.stl filename pairs.
    rows = conn.execute(sa.text("SELECT id, filename FROM stl_files")).fetchall()
    by_filename = {r[1]: r[0] for r in rows}
    for file_id, filename in rows:
        if filename.lower().startswith("sup_"):
            base_name = filename[4:]  # strip "Sup_"
            base_id = by_filename.get(base_name)
            if base_id is not None:
                conn.execute(
                    sa.text("UPDATE stl_files SET sup_of_id = :base WHERE id = :id"),
                    {"base": base_id, "id": file_id},
                )


def downgrade() -> None:
    pass  # SQLite cannot drop columns; acceptable for development rollback

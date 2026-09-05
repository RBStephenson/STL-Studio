"""Add scan_roots.reorganize_template — per-root destination templates (STUDIO-403)

NULL means "inherit", not "no template": the root falls back to the app-wide
`reorganize_template` setting, which itself falls back to the parser's built-in
default. That is why the column is nullable with no server_default — a default
here would silently freeze every existing root at whatever the global template
happened to be on upgrade day, which is exactly the drift this ticket exists to
avoid. create_all handles fresh DBs; this brings already Alembic-stamped DBs up
to the same schema.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("scan_roots")}
    if "reorganize_template" not in cols:
        op.add_column(
            "scan_roots",
            sa.Column("reorganize_template", sa.String(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("scan_roots", "reorganize_template")

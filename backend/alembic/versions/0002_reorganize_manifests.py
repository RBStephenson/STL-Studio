"""reorganize_manifests table (#323)

Persists library-reorganize preview manifests as identified, immutable
artifacts so Phase 2 (#324) can execute the approved plan and verify
non-drift. create_all handles fresh DBs; this migration brings already
Alembic-stamped DBs up to the same schema.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reorganize_manifests" in inspector.get_table_names():
        # create_all (run at startup before migrations on fresh DBs) may have
        # already created it; nothing to do.
        return
    op.create_table(
        "reorganize_manifests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("template", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("reorganize_manifests")

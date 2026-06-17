"""models.is_group_rep — user-chosen variant-group display thumbnail (#193)

Adds a boolean flag marking which member represents a variant group on the
library grid. create_all handles fresh DBs; this migration brings already
Alembic-stamped DBs up to the same schema.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("models")}
    if "is_group_rep" in columns:
        # create_all (run at startup before migrations on fresh DBs) may have
        # already added it; nothing to do.
        return
    op.add_column(
        "models",
        sa.Column(
            "is_group_rep",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("models", "is_group_rep")

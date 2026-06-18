"""Library list-path indexes (#394)

Adds (creator_id, character) for the variant-collapse window and creator sort,
(character, name) for the default grid sort, and created_at for the `sort=added`
view. create_all handles fresh DBs; this brings already Alembic-stamped DBs up
to the same schema.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


_INDEXES = (
    ("ix_models_creator_character", ["creator_id", "character"]),
    ("ix_models_character_name", ["character", "name"]),
    ("ix_models_created_at", ["created_at"]),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("models")}
    for name, cols in _INDEXES:
        # create_all (run at startup before migrations on fresh DBs) may have
        # already created it; skip to stay idempotent.
        if name not in existing:
            op.create_index(name, "models", cols)


def downgrade() -> None:
    for name, _ in _INDEXES:
        op.drop_index(name, table_name="models")

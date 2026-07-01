"""Backfill durable manual variant groups from user GroupOverride rows (#678 Phase 1)

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-01
"""
from alembic import op
from sqlalchemy.orm import Session

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.services.grouping import backfill_manual_groups_from_overrides

    db = Session(bind=op.get_bind())
    try:
        backfill_manual_groups_from_overrides(db)
        db.commit()
    finally:
        db.close()


def downgrade() -> None:
    # Data migration — no safe automatic un-merge (would require distinguishing
    # groups this migration created from ones a user has since edited).
    pass

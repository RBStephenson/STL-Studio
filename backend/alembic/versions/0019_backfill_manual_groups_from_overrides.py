"""Backfill durable manual variant groups from user GroupOverride rows (#678 Phase 1)

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-01
"""
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # group_overrides is dropped in #678 Phase 5 (migration 0024) — a re-run of
    # the full migration chain on a fresh DB reaches this step before that drop,
    # but an already-upgraded DB replaying history from here won't have the
    # table at all. Either way this step's job is done; skip.
    if "group_overrides" not in inspector.get_table_names():
        return
    _backfill(bind)


def _backfill(bind) -> None:
    """Turn user GroupOverride rows with a non-null character into durable manual
    variant groups. Only rows with a non-null character (an explicit user
    grouping decision) and only models with no variant_group_id yet are
    touched — already-grouped models and character=None (explicit-ungroup,
    #678 Phase 5's concern) are left alone."""
    override_rows = bind.execute(
        sa.text("SELECT path, character FROM group_overrides WHERE character IS NOT NULL")
    ).fetchall()
    overrides = {r.path: r.character for r in override_rows}
    if not overrides:
        return

    placeholders = ",".join(f":p{i}" for i in range(len(overrides)))
    params = {f"p{i}": p for i, p in enumerate(overrides.keys())}
    candidates = bind.execute(
        sa.text(
            "SELECT id, creator_id, folder_path, COALESCE(is_group_rep, 0) AS is_rep "
            "FROM models "
            f"WHERE excluded = 0 AND variant_group_id IS NULL AND folder_path IN ({placeholders})"
        ),
        params,
    ).fetchall()

    buckets: dict[tuple[int, str], list] = defaultdict(list)
    for m in candidates:
        buckets[(m.creator_id, overrides[m.folder_path])].append(m)

    for (creator_id, character), members in buckets.items():
        if len(members) < 2:
            continue
        rep = next((m.id for m in members if m.is_rep), members[0].id)
        result = bind.execute(
            sa.text(
                "INSERT INTO variant_groups (creator_id, label, rep_model_id, source, reason, confidence, created_at) "
                "VALUES (:creator_id, :label, :rep, 'manual', 'manual', 1.0, CURRENT_TIMESTAMP)"
            ),
            {"creator_id": creator_id, "label": character, "rep": rep},
        )
        group_id = result.lastrowid
        ids = [m.id for m in members]
        bind.execute(
            sa.text(
                "UPDATE models SET variant_group_id = :gid "
                "WHERE id IN (" + ",".join(str(i) for i in ids) + ")"
            ),
            {"gid": group_id},
        )


def downgrade() -> None:
    # Data migration — no safe automatic un-merge (would require distinguishing
    # groups this migration created from ones a user has since edited).
    pass

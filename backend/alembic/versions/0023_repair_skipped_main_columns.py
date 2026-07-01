"""Repair columns skipped when main's 0015-0017 were shadowed by branch 0017

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-01

When this branch originally used revision numbers 0015-0017 that clashed with
main's 0015-0018, the production DB was stamped to "0017" (by our old
stl_file_part_name migration) before main's 0015-0017 ran.  After the
branch-migrations were renumbered to 0019-0021 and the image rebuilt, alembic
applied 0018-0021 but skipped main's 0015-0017 entirely, leaving three
columns unset on the live database.
"""
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # ── 0015: scan_roots.group_by_character ──────────────────────────────────
    sr_cols = {c["name"] for c in insp.get_columns("scan_roots")}
    if "group_by_character" not in sr_cols:
        conn.execute(
            sa.text(
                "ALTER TABLE scan_roots ADD COLUMN group_by_character BOOLEAN NOT NULL DEFAULT 0"
            )
        )

    # ── 0016: models.parsed_attributes ───────────────────────────────────────
    m_cols = {c["name"] for c in insp.get_columns("models")}
    if "parsed_attributes" not in m_cols:
        conn.execute(sa.text("ALTER TABLE models ADD COLUMN parsed_attributes JSON"))

    # ── 0017: models.variant_group_id + backfill ─────────────────────────────
    m_cols = {c["name"] for c in sa.inspect(conn).get_columns("models")}
    if "variant_group_id" not in m_cols:
        conn.execute(sa.text("ALTER TABLE models ADD COLUMN variant_group_id INTEGER"))
        existing_indexes = {idx["name"] for idx in insp.get_indexes("models")}
        if "ix_models_variant_group_id" not in existing_indexes:
            conn.execute(
                sa.text("CREATE INDEX ix_models_variant_group_id ON models (variant_group_id)")
            )
        _backfill_variant_groups(conn)


def _backfill_variant_groups(conn) -> None:
    rows = conn.execute(
        sa.text(
            "SELECT id, creator_id, character, COALESCE(is_group_rep, 0) AS is_rep "
            "FROM models "
            "WHERE excluded = 0 AND creator_id IS NOT NULL "
            "AND character IS NOT NULL AND character != ''"
        )
    ).fetchall()

    members: dict[tuple[int, str], list] = defaultdict(list)
    for r in rows:
        members[(r.creator_id, r.character)].append(r)

    for (creator_id, character), grp in members.items():
        if len(grp) < 2:
            continue
        rep = next((m.id for m in grp if m.is_rep), grp[0].id)
        result = conn.execute(
            sa.text(
                "INSERT INTO variant_groups (creator_id, label, rep_model_id, source, created_at) "
                "VALUES (:creator_id, :label, :rep, 'auto', CURRENT_TIMESTAMP)"
            ),
            {"creator_id": creator_id, "label": character, "rep": rep},
        )
        group_id = result.lastrowid
        ids = [m.id for m in grp]
        conn.execute(
            sa.text(
                "UPDATE models SET variant_group_id = :gid "
                "WHERE id IN (" + ",".join(str(i) for i in ids) + ")"
            ),
            {"gid": group_id},
        )


def downgrade() -> None:
    pass  # SQLite cannot drop columns; columns are nullable/defaulted so no harm leaving them

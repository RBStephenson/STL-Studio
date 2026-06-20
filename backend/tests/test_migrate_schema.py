"""Regression tests for _migrate_schema() — the legacy column-add bridge.

Verifies that columns introduced via Alembic are also covered by _migrate_schema
so that pre-Alembic databases (stamped at the current head without running
individual migrations) end up with the correct schema.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.main as main_mod


def _col_names(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}


def _drop_column(engine, table: str, column: str) -> None:
    """Remove a column from an existing SQLite table via rename-recreate."""
    with engine.connect() as conn:
        info = list(conn.execute(text(f"PRAGMA table_info({table})")))
        kept = [(r[1], r[2]) for r in info if r[1] != column]
        cols_csv = ", ".join(n for n, _ in kept)
        defs_csv = ", ".join(f"{n} {d}" for n, d in kept)
        conn.execute(text(f"ALTER TABLE {table} RENAME TO _{table}_old"))
        conn.execute(text(f"CREATE TABLE {table} ({defs_csv})"))
        conn.execute(text(
            f"INSERT INTO {table} ({cols_csv}) SELECT {cols_csv} FROM _{table}_old"
        ))
        conn.execute(text(f"DROP TABLE _{table}_old"))
        conn.commit()


class TestMigrateSchemaIsInbox:
    def test_is_inbox_added_to_pre_alembic_db(self):
        """_migrate_schema must add models.is_inbox to a DB that lacks it."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        _drop_column(engine, "models", "is_inbox")

        with engine.connect() as conn:
            assert "is_inbox" not in _col_names(conn, "models"), \
                "precondition: column should be absent before migration"

        real_engine = main_mod.engine
        try:
            main_mod.engine = engine
            main_mod._migrate_schema()
        finally:
            main_mod.engine = real_engine

        with engine.connect() as conn:
            assert "is_inbox" in _col_names(conn, "models"), \
                "_migrate_schema must add models.is_inbox"

        engine.dispose()

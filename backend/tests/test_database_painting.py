"""
Backup/restore/reset smoke tests for the painting tables (#182, M0 exit).

The database router operates on the on-disk SQLite file resolved from
settings.database_url and uses module-level engine references, so these tests
run against a real file DB under tmp_path instead of the shared in-memory
fixture. Every module that imported `engine` at import time gets patched —
patching app.database alone would leave stale bindings (same caveat as the
conftest `db` fixture).
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import settings
from app.database import Base
from app.main import app
from tests.test_painting_module import PAINTING_TABLES


def _sqlite_tables(path) -> set[str]:
    conn = sqlite3.connect(str(path))
    try:
        return {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


@pytest.fixture()
def file_db_client(tmp_path, monkeypatch):
    """TestClient wired to a file-backed SQLite DB with the full schema."""
    db_path = tmp_path / "stl_inventory.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")

    import app.database as db_module
    import app.main as main_module
    import app.routers.database as database_router

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(database_router, "engine", engine)

    with TestClient(app, base_url="http://localhost") as c:
        yield c, db_path
    engine.dispose()


def test_backup_includes_painting_tables(file_db_client, tmp_path):
    client, _ = file_db_client
    resp = client.get("/database/backup")
    assert resp.status_code == 200

    backup_path = tmp_path / "backup.db"
    backup_path.write_bytes(resp.content)
    missing = PAINTING_TABLES - _sqlite_tables(backup_path)
    assert not missing, f"painting tables missing from backup: {sorted(missing)}"


# The columns M2 #268 added to guide tables that M0/#258 had already created.
# A DB built before #268 is missing these and create_all won't add them, so
# _migrate_schema must (regression for the guides list/reader 500).
PRE268_GUIDE_COLUMNS = [
    ("guides", "title_lead"), ("guides", "subtitle"), ("guides", "category_label"),
    ("guides", "quote"), ("guides", "head_style"),
    ("guide_tabs", "dom_id"), ("guide_tabs", "subtabs"), ("guide_tabs", "method_block"),
    ("guide_phases", "subtab_key"), ("guide_steps", "technique_label"),
]


def _columns(path, table) -> set[str]:
    conn = sqlite3.connect(str(path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_migrate_schema_backfills_pre268_guide_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "stl_inventory.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Simulate a pre-#268 DB by dropping the columns those migrations add.
    conn = sqlite3.connect(str(db_path))
    try:
        for table, col in PRE268_GUIDE_COLUMNS:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
        conn.commit()
    finally:
        conn.close()
    for table, col in PRE268_GUIDE_COLUMNS:
        assert col not in _columns(db_path, table)

    import app.main as main_module
    monkeypatch.setattr(main_module, "engine", engine)
    main_module._migrate_schema()  # idempotent; the live app runs this at startup

    for table, col in PRE268_GUIDE_COLUMNS:
        assert col in _columns(db_path, table), f"{table}.{col} was not re-added"
    engine.dispose()


def test_restore_of_pre_painting_backup_creates_painting_tables(file_db_client, tmp_path):
    """Restoring a backup from before the painting module must come back up
    with the painting schema — restore runs create_all + migrations."""
    client, db_path = file_db_client

    old_backup = tmp_path / "old_backup.db"
    conn = sqlite3.connect(str(old_backup))
    try:
        # Minimal pre-painting DB: just enough to pass restore validation.
        conn.execute("CREATE TABLE models (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
    finally:
        conn.close()

    with old_backup.open("rb") as f:
        resp = client.post(
            "/database/restore",
            files={"file": ("old_backup.db", f, "application/octet-stream")},
        )
    assert resp.status_code == 200, resp.text

    missing = PAINTING_TABLES - _sqlite_tables(db_path)
    assert not missing, f"painting tables missing after restore: {sorted(missing)}"


def test_backup_restore_round_trip_preserves_painting_tables(file_db_client, tmp_path):
    client, db_path = file_db_client

    resp = client.get("/database/backup")
    assert resp.status_code == 200
    backup_path = tmp_path / "roundtrip.db"
    backup_path.write_bytes(resp.content)

    with backup_path.open("rb") as f:
        resp = client.post(
            "/database/restore",
            files={"file": ("roundtrip.db", f, "application/octet-stream")},
        )
    assert resp.status_code == 200, resp.text

    missing = PAINTING_TABLES - _sqlite_tables(db_path)
    assert not missing, f"painting tables missing after round trip: {sorted(missing)}"


def test_reset_recreates_painting_tables(file_db_client):
    client, db_path = file_db_client
    resp = client.post("/database/reset")
    assert resp.status_code == 200

    missing = PAINTING_TABLES - _sqlite_tables(db_path)
    assert not missing, f"painting tables missing after reset: {sorted(missing)}"
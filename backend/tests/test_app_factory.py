"""
Tests for the app factory (issue #212).

The standalone binary builds its app via create_app(api_prefix="/api") instead
of duplicating routers/migrations, so the two deployments cannot drift. These
tests pin that guarantee: identical route sets (modulo prefix) and a startup
migration that brings an old-schema DB fully up to date.
"""
from fastapi.routing import APIRoute
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.main import app, create_app


def _api_routes(app_) -> set[tuple[str, frozenset]]:
    return {
        (r.path, frozenset(r.methods))
        for r in app_.routes
        if isinstance(r, APIRoute)
    }


def test_standalone_routes_match_main_app():
    standalone = create_app(api_prefix="/api")
    expected = {(f"/api{path}", methods) for path, methods in _api_routes(app)}
    assert _api_routes(standalone) == expected


def test_main_app_has_no_prefix():
    paths = {path for path, _ in _api_routes(app)}
    assert "/health" in paths
    assert not any(p.startswith("/api/") for p in paths)


def test_prefixed_app_includes_painting_routes():
    paths = {path for path, _ in _api_routes(create_app(api_prefix="/api"))}
    assert "/api/painting/health" in paths


def test_migrate_schema_upgrades_old_db(monkeypatch):
    """A v0.4-era DB (no favorites/queue/excluded columns) gains every column."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Minimal old-schema tables: only the columns that predate _migrate_schema.
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE models (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text("CREATE TABLE stl_files (id INTEGER PRIMARY KEY, path VARCHAR)"))
        conn.execute(text("CREATE TABLE scan_roots (id INTEGER PRIMARY KEY, path VARCHAR)"))
        conn.execute(text("CREATE TABLE collections (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text(
            "CREATE TABLE collection_models "
            "(id INTEGER PRIMARY KEY, collection_id INTEGER, model_id INTEGER)"
        ))
        conn.commit()

    monkeypatch.setattr(main_module, "engine", engine)
    main_module._migrate_schema()

    with engine.connect() as conn:
        model_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(models)"))}
        file_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(stl_files)"))}
        root_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(scan_roots)"))}

    assert {
        "is_favorite", "queued_at", "printed_at",
        "queue_position", "excluded", "print_status", "print_count",
    } <= model_cols
    assert "part_type" in file_cols
    assert "layout" in root_cols
    engine.dispose()


def test_migrate_schema_backfills_print_status_from_legacy_flags(monkeypatch):
    """A DB tracked under the old in_queue/printed_at flags gets print_status
    derived once, with queued winning over printed and the run guarded so it
    can't re-fire and resurrect stale state."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TABLE models ("
            "id INTEGER PRIMARY KEY, name VARCHAR, in_queue BOOLEAN DEFAULT 0, "
            "printed_at DATETIME, print_status VARCHAR NOT NULL DEFAULT 'none', "
            "print_count INTEGER NOT NULL DEFAULT 0)"
        ))
        conn.execute(text("CREATE TABLE app_settings (key VARCHAR PRIMARY KEY, value JSON NOT NULL)"))
        # The unconditional orphan-cleanup step needs these tables to exist.
        conn.execute(text("CREATE TABLE collections (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text(
            "CREATE TABLE collection_models "
            "(id INTEGER PRIMARY KEY, collection_id INTEGER, model_id INTEGER)"
        ))
        # 1: queued-only, 2: printed-only, 3: both (queued wins), 4: untouched.
        conn.execute(text(
            "INSERT INTO models (id, name, in_queue, printed_at) VALUES "
            "(1, 'queued', 1, NULL), "
            "(2, 'printed', 0, '2026-01-01'), "
            "(3, 'both', 1, '2026-01-01'), "
            "(4, 'idle', 0, NULL)"
        ))
        conn.commit()

    monkeypatch.setattr(main_module, "engine", engine)
    main_module._migrate_schema()

    with engine.connect() as conn:
        status = dict(conn.execute(text("SELECT id, print_status FROM models")).fetchall())
        printed_count = conn.execute(text(
            "SELECT print_count FROM models WHERE id = 2"
        )).scalar()
        flag = conn.execute(text(
            "SELECT value FROM app_settings WHERE key = 'print_status_backfilled'"
        )).scalar()
    assert status == {1: "queued", 2: "printed", 3: "queued", 4: "none"}
    assert printed_count == 1
    assert flag is not None

    # Second run must be a no-op even if a legacy flag still lingers: flip model 4's
    # in_queue on and confirm the guard keeps print_status untouched.
    with engine.connect() as conn:
        conn.execute(text("UPDATE models SET in_queue = 1 WHERE id = 4"))
        conn.commit()
    main_module._migrate_schema()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT print_status FROM models WHERE id = 4")).scalar() == "none"
    engine.dispose()


def test_alembic_chain_adds_is_group_rep(monkeypatch, tmp_path):
    """The 0003 revision adds models.is_group_rep on an already-stamped DB (#193).

    Guards the Alembic path: create_all is skipped for existing tables, so an
    Alembic-managed DB only gets the column from a real migration revision.
    """
    from pathlib import Path
    from alembic.config import Config
    from alembic import command

    db_url = f"sqlite:///{tmp_path / 'mig.db'}"
    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE models (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0002')"))
        conn.commit()

    # env.py binds to app.database.engine, so point the whole app at this DB.
    monkeypatch.setattr("app.database.engine", engine)
    cfg = Config(str(Path(main_module.__file__).parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(models)"))}
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert "is_group_rep" in cols
    assert version == "0003"
    engine.dispose()


def test_run_migrations_stamps_legacy_db(monkeypatch):
    """A DB without alembic_version gets _migrate_schema() then stamped at head."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE models (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text("CREATE TABLE stl_files (id INTEGER PRIMARY KEY, path VARCHAR)"))
        conn.execute(text("CREATE TABLE scan_roots (id INTEGER PRIMARY KEY, path VARCHAR)"))
        conn.execute(text("CREATE TABLE collections (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text(
            "CREATE TABLE collection_models "
            "(id INTEGER PRIMARY KEY, collection_id INTEGER, model_id INTEGER)"
        ))
        conn.commit()

    monkeypatch.setattr(main_module, "engine", engine)

    stamped: list[str] = []
    upgraded: list[str] = []

    def fake_stamp(cfg, rev):
        stamped.append(rev)

    def fake_upgrade(cfg, rev):
        upgraded.append(rev)

    monkeypatch.setattr("alembic.command.stamp", fake_stamp)
    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)

    main_module._run_migrations()

    assert stamped == ["head"]
    assert upgraded == []
    engine.dispose()


def test_run_migrations_upgrades_alembic_db(monkeypatch):
    """A DB that already has alembic_version calls upgrade head, not stamp."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        ))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0001')"))
        conn.commit()

    monkeypatch.setattr(main_module, "engine", engine)

    stamped: list[str] = []
    upgraded: list[str] = []

    def fake_stamp(cfg, rev):
        stamped.append(rev)

    def fake_upgrade(cfg, rev):
        upgraded.append(rev)

    monkeypatch.setattr("alembic.command.stamp", fake_stamp)
    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)

    main_module._run_migrations()

    assert upgraded == ["head"]
    assert stamped == []
    engine.dispose()


def test_migrate_schema_prunes_orphaned_collection_models(monkeypatch):
    """Link rows orphaned by pre-#214 collection deletes are cleaned up."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE models (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text("CREATE TABLE stl_files (id INTEGER PRIMARY KEY, path VARCHAR)"))
        conn.execute(text("CREATE TABLE scan_roots (id INTEGER PRIMARY KEY, path VARCHAR)"))
        conn.execute(text("CREATE TABLE collections (id INTEGER PRIMARY KEY, name VARCHAR)"))
        conn.execute(text(
            "CREATE TABLE collection_models "
            "(id INTEGER PRIMARY KEY, collection_id INTEGER, model_id INTEGER)"
        ))
        conn.execute(text("INSERT INTO models (id, name) VALUES (1, 'm1')"))
        conn.execute(text("INSERT INTO collections (id, name) VALUES (1, 'kept')"))
        # Row 1 is valid; row 2 points at a deleted collection; row 3 at a deleted model.
        conn.execute(text("INSERT INTO collection_models VALUES (1, 1, 1), (2, 99, 1), (3, 1, 99)"))
        conn.commit()

    monkeypatch.setattr(main_module, "engine", engine)
    main_module._migrate_schema()

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id FROM collection_models")).fetchall()
    assert [r[0] for r in rows] == [1]
    engine.dispose()

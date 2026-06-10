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
        conn.commit()

    monkeypatch.setattr(main_module, "engine", engine)
    main_module._migrate_schema()

    with engine.connect() as conn:
        model_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(models)"))}
        file_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(stl_files)"))}
        root_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(scan_roots)"))}

    assert {
        "is_favorite", "in_queue", "queued_at", "printed_at",
        "queue_position", "excluded",
    } <= model_cols
    assert "part_type" in file_cols
    assert "layout" in root_cols
    engine.dispose()

"""Qualify upgrades from released STL Studio database schemas to head.

The binary fixtures were created with each tag's own SQLAlchemy metadata. This
is necessary because Alembic revision 0001 is a no-op baseline for databases
originally created by ``Base.metadata.create_all``.
"""

import json
import shutil
import sqlite3
from pathlib import Path

from alembic import command as alembic_command
import pytest
from sqlalchemy import create_engine, inspect, text

import app.database as database_module
import app.main as main_module
from app.services import database_upgrade


FIXTURES = Path(__file__).parent / "fixtures" / "upgrade"
RELEASES = (("v0.18.0", "0027"), ("v0.19.0", "0028"), ("v0.20.0", "0032"))


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _insert(conn: sqlite3.Connection, table: str, values: dict) -> None:
    names = list(values)
    placeholders = ", ".join("?" for _ in names)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})",
        tuple(values[name] for name in names),
    )


def _seed_representative_data(path: Path, revision: str) -> None:
    """Populate relationships and user-authored data that must survive."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        _insert(conn, "scan_roots", {
            "id": 1,
            "path": "/library",
            "enabled": 1,
            "name": "Fixture Library",
            "is_writable": 1,
            "layout": "{creator}/{character}",
            "group_by_character": 1,
        })
        _insert(conn, "import_source_mappings", {
            "id": 1,
            "source_path": "/imports",
            "library_id": 1,
        })
        _insert(conn, "creators", {"id": 1, "name": "Fixture Creator"})
        _insert(conn, "variant_groups", {
            "id": 1, "creator_id": 1, "label": "Fixture Group", "source": "manual",
        })

        model = {
            "id": 1,
            "name": "Fixture Model",
            "folder_path": "/library/Fixture Creator/Fixture Model",
            "creator_id": 1,
            "character": "Fixture Character",
            "variant_group_id": 1,
            "title": "Curated title",
            "description": "Must survive the upgrade",
            "tags": json.dumps(["hero", "painted"]),
            "auto_tags": json.dumps(["32mm"]),
            "is_favorite": 1,
            "print_status": "printed",
            "print_count": 2,
            "is_inbox": 0,
        }
        if "locked" in _columns(conn, "models"):
            model["locked"] = 1
        _insert(conn, "models", model)
        conn.execute("UPDATE variant_groups SET rep_model_id = 1 WHERE id = 1")
        _insert(conn, "stl_files", {
            "id": 1,
            "model_id": 1,
            "path": "/library/Fixture Creator/Fixture Model/body.stl",
            "filename": "body.stl",
            "size_bytes": 12345,
            "part_type": "Body",
        })
        _insert(conn, "collections", {
            "id": 1,
            "name": "Release candidates",
            "description": "Upgrade fixture collection",
        })
        _insert(conn, "collection_models", {"id": 1, "collection_id": 1, "model_id": 1})
        _insert(conn, "app_settings", {
            "key": "reorganize_template",
            "value": json.dumps("{creator}/{character}/{title}"),
        })
        _insert(conn, "app_settings", {
            "key": "ai_api_key_enc",
            "value": json.dumps("fixture-ciphertext-not-plaintext"),
        })

        ai_config = {
            "id": 1,
            "name": "Fixture API",
            "api_type": "openai",
            "url": "http://fixture.invalid/v1",
            "model": "fixture-model",
            "effort": "medium",
        }
        ai_columns = _columns(conn, "ai_api_configs")
        if "request_timeout" in ai_columns:
            ai_config["request_timeout"] = 45
        if "batch_size" in ai_columns:
            ai_config["batch_size"] = 7
        if "reasoning_enabled" in ai_columns:
            ai_config["reasoning_enabled"] = 1
        _insert(conn, "ai_api_configs", ai_config)

        _insert(conn, "paint_brands", {"id": 1, "name": "Fixture Paints"})
        _insert(conn, "paint_lines", {
            "id": 1,
            "brand_id": 1,
            "name": "Fixture Line",
            "code_pattern": "^FX-[0-9]+$",
        })
        _insert(conn, "paints", {
            "id": 1,
            "paint_line_id": 1,
            "code": "FX-1",
            "name": "Fixture Red",
            "hex": "#AA1122",
            "finish": "matte",
            "owned": 1,
        })
        _insert(conn, "guide_categories", {
            "id": 1, "slug": "fixture", "display_name": "Fixture Guides",
        })
        _insert(conn, "guides", {
            "id": 1,
            "slug": "fixture-guide",
            "title": "Fixture Guide",
            "category_id": 1,
            "model_id": 1,
            "status": "published",
        })
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize(("release", "revision"), RELEASES)
def test_released_database_upgrades_to_head_without_data_loss(
    release: str, revision: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / f"{release}.db"
    shutil.copy2(FIXTURES / f"{release}.db", db_path)
    _seed_representative_data(db_path, revision)

    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(main_module, "engine", engine)

    main_module._run_migrations()
    main_module._run_migrations()  # startup is repeatable; upgrades must be idempotent

    inspector = inspect(engine)
    assert "locked" in {column["name"] for column in inspector.get_columns("models")}
    assert {"request_timeout", "batch_size", "reasoning_enabled"}.issubset(
        {column["name"] for column in inspector.get_columns("ai_api_configs")}
    )
    assert {
        "ix_models_source_site",
        "ix_models_needs_review",
        "ix_models_source_last_fetched",
        "ix_models_locked",
    }.issubset({index["name"] for index in inspector.get_indexes("models")})

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0032"
        model = conn.execute(text(
            "SELECT name, title, description, tags, print_status, print_count, locked "
            "FROM models WHERE id = 1"
        )).one()
        assert model[:6] == (
            "Fixture Model",
            "Curated title",
            "Must survive the upgrade",
            '["hero", "painted"]',
            "printed",
            2,
        )
        assert model.locked == (1 if release == "v0.20.0" else 0)
        assert conn.execute(text(
            "SELECT vg.label FROM variant_groups vg JOIN models m "
            "ON m.variant_group_id = vg.id WHERE m.id = 1"
        )).scalar_one() == "Fixture Group"
        assert conn.execute(text(
            "SELECT c.name FROM collections c JOIN collection_models cm "
            "ON cm.collection_id = c.id WHERE cm.model_id = 1"
        )).scalar_one() == "Release candidates"
        assert conn.execute(text(
            "SELECT filename FROM stl_files WHERE model_id = 1"
        )).scalar_one() == "body.stl"
        library = conn.execute(text(
            "SELECT path, name, is_writable, layout, group_by_character "
            "FROM scan_roots WHERE id = 1"
        )).one()
        assert library == (
            "/library",
            "Fixture Library",
            1,
            "{creator}/{character}",
            1,
        )
        assert conn.execute(text(
            "SELECT source_path FROM import_source_mappings WHERE library_id = 1"
        )).scalar_one() == "/imports"
        encrypted_setting = conn.execute(text(
            "SELECT value FROM app_settings WHERE key = 'ai_api_key_enc'"
        )).scalar_one()
        assert json.loads(encrypted_setting) == "fixture-ciphertext-not-plaintext"
        assert conn.execute(text("SELECT name FROM paints WHERE id = 1")).scalar_one() == "Fixture Red"
        assert conn.execute(text("SELECT title FROM guides WHERE model_id = 1")).scalar_one() == "Fixture Guide"
        ai = conn.execute(text(
            "SELECT request_timeout, batch_size, reasoning_enabled "
            "FROM ai_api_configs WHERE id = 1"
        )).one()
        assert ai == (
            10 if release == "v0.18.0" else 45,
            7 if release == "v0.20.0" else None,
            1 if release == "v0.20.0" else 0,
        )

    engine.dispose()


def test_failed_upgrade_restores_exact_pre_upgrade_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "failed-upgrade.db"
    shutil.copy2(FIXTURES / "v0.18.0.db", db_path)
    _seed_representative_data(db_path, "0027")
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(main_module, "engine", engine)

    def fail_upgrade(*_args, **_kwargs) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE models SET title = 'partially migrated' WHERE id = 1")
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(alembic_command, "upgrade", fail_upgrade)

    with pytest.raises(RuntimeError, match="simulated migration failure"):
        main_module._run_migrations()

    snapshots = list((tmp_path / "backups").glob("pre_upgrade_*.db"))
    assert len(snapshots) == 1
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0027"
        assert conn.execute("SELECT title FROM models WHERE id = 1").fetchone()[0] == "Curated title"
    engine.dispose()


def test_current_schema_does_not_create_redundant_upgrade_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "current.db"
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(main_module, "engine", engine)

    main_module._run_migrations()
    main_module._run_migrations()

    assert not (tmp_path / "backups").exists()
    engine.dispose()


def test_upgrade_snapshot_retention_is_bounded(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    shutil.copy2(FIXTURES / "v0.18.0.db", db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    for _ in range(database_upgrade.UPGRADE_SNAPSHOT_KEEP + 1):
        database_upgrade.create_upgrade_snapshot(engine, "0032")

    snapshots = list((tmp_path / "backups").glob("pre_upgrade_*.db"))
    assert len(snapshots) == database_upgrade.UPGRADE_SNAPSHOT_KEEP
    engine.dispose()

"""Deterministic adverse storage qualification for STUDIO-204."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import AppSetting, Creator
from app.routers import database as database_router
from app.services import database_upgrade


class _BackupFailureConnection:
    """Delegate a SQLite connection except for the online backup boundary."""

    def __init__(self, connection: sqlite3.Connection, message: str):
        self._connection = connection
        self._message = message

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def backup(self, _destination):
        raise sqlite3.OperationalError(self._message)


def _connect_with_source_backup_failure(real_connect, message: str):
    calls = 0

    def connect(path, *args, **kwargs):
        nonlocal calls
        connection = real_connect(path, *args, **kwargs)
        calls += 1
        if calls == 1:
            return _BackupFailureConnection(connection, message)
        return connection

    return connect


def _create_catalog(path: Path) -> bytes:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Creator(name="Adverse Failure Sentinel"))
        db.commit()
    engine.dispose()
    return path.read_bytes()


def test_disk_full_during_upgrade_snapshot_keeps_catalog_and_removes_partial_snapshot(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "catalog.db"
    original = _create_catalog(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        database_upgrade.sqlite3,
        "connect",
        _connect_with_source_backup_failure(real_connect, "database or disk is full"),
    )

    with pytest.raises(sqlite3.OperationalError, match="disk is full"):
        database_upgrade.create_upgrade_snapshot(engine, "future-revision")

    assert db_path.read_bytes() == original
    assert not list((tmp_path / "backups").glob("pre_upgrade_*.db"))
    engine.dispose()


def test_disk_full_during_download_backup_keeps_catalog_and_removes_partial_export(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "catalog.db"
    original = _create_catalog(db_path)
    monkeypatch.setattr(database_router.settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(database_router.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(database_router, "_stamp", lambda: "qualification")
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        database_router.sqlite3,
        "connect",
        _connect_with_source_backup_failure(real_connect, "database or disk is full"),
    )

    with pytest.raises(sqlite3.OperationalError, match="disk is full"):
        database_router.backup_database(object())

    assert db_path.read_bytes() == original
    assert not (tmp_path / "stl_inventory_backup_qualification.db").exists()


def test_locked_database_rejects_setting_write_without_partial_commit(tmp_path):
    db_path = tmp_path / "locked.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"timeout": 0.05}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AppSetting(key="models_per_page", value=24))
        db.commit()

    lock = sqlite3.connect(db_path)
    lock.execute("BEGIN EXCLUSIVE")
    try:
        with Session(engine) as db, pytest.raises(OperationalError, match="locked"):
            db.add(AppSetting(key="theme", value="dark"))
            existing = db.get(AppSetting, "models_per_page")
            existing.value = 96
            db.commit()
    finally:
        lock.rollback()
        lock.close()

    with Session(engine) as db:
        assert db.get(AppSetting, "models_per_page").value == 24
        assert db.get(AppSetting, "theme") is None
    engine.dispose()

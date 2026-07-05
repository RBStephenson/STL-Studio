"""
Tests for the auto-snapshot taken before /database/restore and /database/reset (#222).

Like test_database_painting, these run against a real file-backed SQLite DB under
tmp_path (the snapshot logic resolves the data dir from the live DB file and uses
the on-disk sqlite3 backup API), not the shared in-memory fixture.
"""
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import settings
from app.database import Base
from app.main import app
import app.routers.database as database_router


@pytest.fixture()
def file_db_client(tmp_path, monkeypatch):
    """TestClient wired to a file-backed SQLite DB with the full schema."""
    db_path = tmp_path / "stl_inventory.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")

    import app.database as db_module
    import app.main as main_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(database_router, "engine", engine)

    with TestClient(app, base_url="http://localhost") as c:
        yield c, db_path
    engine.dispose()


def _backups_dir(db_path):
    return db_path.parent / "backups"


def _make_backup_upload(client):
    """A valid backup the restore endpoint will accept: the current DB's bytes."""
    resp = client.get("/database/backup")
    assert resp.status_code == 200
    return resp.content


# ---------------------------------------------------------------------------
# Snapshot is taken before the destructive op
# ---------------------------------------------------------------------------

def test_reset_snapshots_before_wiping(file_db_client):
    client, db_path = file_db_client
    resp = client.post("/database/reset")
    assert resp.status_code == 200

    snapshot = resp.json()["snapshot"]
    assert snapshot is not None
    assert "pre_reset_" in snapshot
    assert (db_path.parent / "backups").exists()
    snaps = list(_backups_dir(db_path).glob("pre_reset_*.db"))
    assert len(snaps) == 1
    # The snapshot is a readable SQLite DB that looks like ours.
    tables = {
        r[0] for r in sqlite3.connect(snaps[0]).execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "models" in tables


def test_restore_snapshots_before_swapping(file_db_client):
    client, db_path = file_db_client
    backup_bytes = _make_backup_upload(client)

    resp = client.post(
        "/database/restore",
        files={"file": ("backup.db", io.BytesIO(backup_bytes), "application/octet-stream")},
    )
    assert resp.status_code == 200

    snapshot = resp.json()["snapshot"]
    assert snapshot is not None
    assert "pre_restore_" in snapshot
    snaps = list(_backups_dir(db_path).glob("pre_restore_*.db"))
    assert len(snaps) == 1


def test_invalid_restore_takes_no_snapshot(file_db_client):
    """A restore rejected at validation must not leave a snapshot behind."""
    client, db_path = file_db_client
    resp = client.post(
        "/database/restore",
        files={"file": ("garbage.db", io.BytesIO(b"not a database"), "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert not _backups_dir(db_path).exists() or not list(
        _backups_dir(db_path).glob("pre_restore_*.db")
    )


# ---------------------------------------------------------------------------
# Pruning keeps only the newest N per reason
# ---------------------------------------------------------------------------

def test_reset_prunes_to_keep_limit(file_db_client):
    client, db_path = file_db_client
    backups = _backups_dir(db_path)
    backups.mkdir(parents=True, exist_ok=True)

    # Seed older snapshots (lexically/chronologically before today's stamp).
    for stamp in ("20200101_000001", "20200101_000002", "20200101_000003"):
        (backups / f"pre_reset_{stamp}.db").write_bytes(b"old")

    resp = client.post("/database/reset")
    assert resp.status_code == 200

    snaps = sorted(p.name for p in backups.glob("pre_reset_*.db"))
    assert len(snaps) == database_router.SNAPSHOT_KEEP
    # The brand-new snapshot survived; the oldest seed was pruned.
    assert "pre_reset_20200101_000001.db" not in snaps


def test_snapshot_is_skipped_for_in_memory_db(monkeypatch):
    """A snapshot can't be taken of a non-file DB; _snapshot_db returns None
    rather than raising, so the destructive op it guards is never blocked."""
    monkeypatch.setattr(settings, "database_url", "sqlite:///:memory:")
    assert database_router._snapshot_db("reset") is None


def test_reset_and_restore_snapshots_are_pruned_independently(file_db_client):
    """Reset and restore snapshots use distinct prefixes, so one reason's churn
    never evicts the other's history."""
    client, db_path = file_db_client
    backups = _backups_dir(db_path)
    backups.mkdir(parents=True, exist_ok=True)
    (backups / "pre_restore_20200101_000001.db").write_bytes(b"old")

    client.post("/database/reset")

    # The restore snapshot is untouched by a reset.
    assert (backups / "pre_restore_20200101_000001.db").exists()


# ---------------------------------------------------------------------------
# Restore/reset honor the library write lock (STUDIO-82)
# ---------------------------------------------------------------------------

def test_reset_returns_409_when_library_busy(file_db_client):
    """A reset must not wipe the DB while a reorganize apply/undo holds the write
    lock — it returns 409 instead."""
    from app.services import write_lock

    client, db_path = file_db_client
    with write_lock.library_write("apply"):
        resp = client.post("/database/reset")
    assert resp.status_code == 409
    # Nothing was snapshotted or wiped.
    assert not _backups_dir(db_path).exists() or not list(
        _backups_dir(db_path).glob("pre_reset_*.db")
    )


def test_restore_returns_409_when_library_busy(file_db_client):
    """A restore must not swap the DB file while the write lock is held; it is
    rejected before taking a snapshot or touching the live file."""
    from app.services import write_lock

    client, db_path = file_db_client
    backup_bytes = _make_backup_upload(client)  # backup is not gated

    with write_lock.library_write("apply"):
        resp = client.post(
            "/database/restore",
            files={"file": ("backup.db", io.BytesIO(backup_bytes), "application/octet-stream")},
        )
    assert resp.status_code == 409
    assert not _backups_dir(db_path).exists() or not list(
        _backups_dir(db_path).glob("pre_restore_*.db")
    )

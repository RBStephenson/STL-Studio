"""Safety snapshots for startup database schema upgrades."""

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine


UPGRADE_SNAPSHOT_KEEP = 3


def _database_path(engine: Engine) -> Path | None:
    if engine.url.get_backend_name() != "sqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database)


def create_upgrade_snapshot(engine: Engine, head_revision: str) -> Path | None:
    """Snapshot an existing SQLite DB when its schema is not at Alembic head."""
    db_path = _database_path(engine)
    if db_path is None or not db_path.exists() or db_path.stat().st_size == 0:
        return None

    source = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        current_revision = None
        if "alembic_version" in tables:
            row = source.execute("SELECT version_num FROM alembic_version").fetchone()
            current_revision = row[0] if row else None
        if current_revision == head_revision:
            return None

        backups = db_path.parent / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot = backups / f"pre_upgrade_{stamp}.db"
        sequence = 2
        while snapshot.exists():
            snapshot = backups / f"pre_upgrade_{stamp}_{sequence}.db"
            sequence += 1

        destination = sqlite3.connect(str(snapshot))
        try:
            with destination:
                source.backup(destination)
        finally:
            destination.close()

        snapshots = sorted(backups.glob("pre_upgrade_*.db"))
        for old_snapshot in snapshots[:-UPGRADE_SNAPSHOT_KEEP]:
            old_snapshot.unlink(missing_ok=True)
        return snapshot
    finally:
        source.close()


def restore_upgrade_snapshot(engine: Engine, snapshot: Path) -> None:
    """Restore the exact pre-upgrade DB after a startup migration failure."""
    db_path = _database_path(engine)
    if db_path is None:
        raise RuntimeError("Database upgrade recovery requires a file-backed SQLite DB")

    engine.dispose()
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    db_path.unlink(missing_ok=True)

    source = sqlite3.connect(str(snapshot))
    destination = sqlite3.connect(str(db_path))
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()

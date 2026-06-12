"""Database management: backup, restore, and reset.

These operate directly on the SQLite database file. Backup uses SQLite's online
backup API to capture a consistent snapshot (folding in any WAL contents);
restore swaps a validated upload in for the live file; reset wipes all data and
recreates an empty schema. Restore and reset are refused while a scan is running
to avoid corrupting an in-flight write.
"""
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.database import Base, engine
from app.config import settings
from app.services import scanner

router = APIRouter(prefix="/database", tags=["database"])

# How many pre-restore / pre-reset snapshots to keep per reason before the oldest
# are pruned. Bounds disk use while still giving a few levels of undo (#222).
SNAPSHOT_KEEP = 3


def _db_path() -> Path:
    """Resolve the on-disk path of the SQLite database from its URL."""
    url = settings.database_url
    if not url.startswith("sqlite"):
        raise HTTPException(500, "Database management is only supported for SQLite")
    # sqlite:///relative.db  or  sqlite:////absolute/path.db
    if "sqlite:///" in url:
        raw = url.split("sqlite:///", 1)[1]
    else:
        raw = url.split("sqlite://", 1)[1]
    if not raw or raw == ":memory:":
        raise HTTPException(500, "In-memory database cannot be backed up or restored")
    return Path(raw)


def _require_idle():
    if scanner.get_status()["running"]:
        raise HTTPException(409, "A scan is currently running — wait for it to finish or cancel it first")


def _snapshot_db(reason: str) -> Path | None:
    """Snapshot the live DB to <data_dir>/backups/pre_<reason>_<stamp>.db before a
    destructive operation, so even a mis-clicked restore/reset is one file-copy
    away from recovery (#222). Uses the same online-backup API as /backup (folds in
    WAL). Keeps the newest SNAPSHOT_KEEP snapshots per reason, prunes older ones.

    Returns the snapshot path, or None if the DB can't be snapshotted (no file yet
    on a fresh install, or a non-file/in-memory DB). A snapshot is a best-effort
    safety net — its absence must not block the destructive op the caller is about
    to perform.
    """
    try:
        db_path = _db_path()
    except HTTPException:
        return None
    if not db_path.exists():
        return None

    backups = db_path.parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backups / f"pre_{reason}_{stamp}.db"
    # Guard against two snapshots landing in the same wall-clock second.
    n = 2
    while dest.exists():
        dest = backups / f"pre_{reason}_{stamp}_{n}.db"
        n += 1

    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(dest))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    # Prune older snapshots for this reason, keeping the newest SNAPSHOT_KEEP.
    # Timestamped names sort chronologically, so lexical order is age order.
    snaps = sorted(backups.glob(f"pre_{reason}_*.db"))
    for old in snaps[:-SNAPSHOT_KEEP]:
        _safe_unlink(old)

    return dest


@router.get("/backup")
def backup_database(background_tasks: BackgroundTasks):
    """Stream a consistent snapshot of the database as a downloadable .db file."""
    db_path = _db_path()
    if not db_path.exists():
        raise HTTPException(404, "Database file not found")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp = Path(tempfile.gettempdir()) / f"stl_inventory_backup_{stamp}.db"

    # Online backup API gives a transactionally-consistent copy that includes
    # any data still sitting in the WAL — a plain file copy would not.
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(tmp))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    background_tasks.add_task(_safe_unlink, tmp)
    return FileResponse(
        tmp,
        filename=f"stl_inventory_backup_{stamp}.db",
        media_type="application/octet-stream",
    )


@router.post("/restore")
async def restore_database(file: UploadFile = File(...)):
    """Replace the live database with an uploaded backup, after validating it."""
    _require_idle()
    db_path = _db_path()

    tmp = Path(tempfile.gettempdir()) / f"stl_restore_{os.getpid()}.db"
    tmp.write_bytes(await file.read())

    # Validate before we touch the live file: must be a sound SQLite DB that
    # actually looks like an STL Library database.
    try:
        conn = sqlite3.connect(str(tmp))
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("integrity check failed")
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            conn.close()
        if "models" not in tables:
            raise ValueError("this file is not an STL Library database")
    except Exception as e:
        _safe_unlink(tmp)
        raise HTTPException(400, f"Invalid backup file: {e}")

    # Snapshot the current library before we overwrite it, so a wrong-file restore
    # is recoverable (#222). Done after validation passes (no point snapshotting
    # for a restore we're about to reject).
    snapshot = _snapshot_db("restore")

    # Drop pooled connections so the file isn't held open, then swap it in and
    # clear the stale WAL/SHM sidecars that belonged to the old database.
    engine.dispose()
    for suffix in ("-wal", "-shm"):
        _safe_unlink(Path(str(db_path) + suffix))
    shutil.move(str(tmp), str(db_path))

    # Bring a possibly-older backup's schema up to date.
    Base.metadata.create_all(bind=engine)
    from app.main import _migrate_schema
    _migrate_schema()
    return {"ok": True, "snapshot": str(snapshot) if snapshot else None}


@router.post("/reset")
def reset_database():
    """Delete all data and recreate an empty schema."""
    _require_idle()
    # Snapshot before wiping so a mis-clicked reset is recoverable (#222).
    snapshot = _snapshot_db("reset")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.main import _migrate_schema
    _migrate_schema()
    return {"ok": True, "snapshot": str(snapshot) if snapshot else None}


def _safe_unlink(path: Path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

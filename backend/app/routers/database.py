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
    # actually looks like an STL Inventory database.
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
            raise ValueError("this file is not an STL Inventory database")
    except Exception as e:
        _safe_unlink(tmp)
        raise HTTPException(400, f"Invalid backup file: {e}")

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
    return {"ok": True}


@router.post("/reset")
def reset_database():
    """Delete all data and recreate an empty schema."""
    _require_idle()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.main import _migrate_schema
    _migrate_schema()
    return {"ok": True}


def _safe_unlink(path: Path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

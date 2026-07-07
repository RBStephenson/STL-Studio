"""Database management: backup, restore, health checks, repair, and reset.

These operate directly on the SQLite database file. Backup uses SQLite's online
backup API to capture a consistent snapshot (folding in any WAL contents);
restore swaps a validated upload in for the live file; reset wipes all data and
recreates an empty schema. Restore and reset run under the library write lock and
are refused (409) while a scan, reorganize apply, or undo is in progress, to avoid
corrupting an in-flight write or leaving on-disk files and DB rows diverged.
"""
import os
import logging
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
from app.services.write_lock import LibraryBusy, library_write

router = APIRouter(prefix="/database", tags=["database"])
log = logging.getLogger(__name__)

# How many pre-restore / pre-reset snapshots to keep per reason before the oldest
# are pruned. Bounds disk use while still giving a few levels of undo (#222).
SNAPSHOT_KEEP = 3


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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


def _integrity_check(path: Path) -> str:
    """Return SQLite's integrity_check result for a database file."""
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def _copy_db_files(reason: str) -> Path:
    """Copy the DB and any WAL/SHM sidecars before an in-place maintenance op."""
    db_path = _db_path()
    if not db_path.exists():
        raise HTTPException(404, "Database file not found")

    backups = db_path.parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    dest = backups / f"pre_{reason}_{stamp}"
    n = 2
    while dest.exists():
        dest = backups / f"pre_{reason}_{stamp}_{n}"
        n += 1
    dest.mkdir()

    shutil.copy2(db_path, dest / db_path.name)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, dest / sidecar.name)
    return dest


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
    stamp = _stamp()
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


def _try_snapshot_db(reason: str) -> tuple[Path | None, str | None]:
    """Best-effort snapshot wrapper for operations that can proceed without one."""
    try:
        return _snapshot_db(reason), None
    except Exception as e:
        log.warning("Database %s snapshot failed; continuing without snapshot: %s", reason, e)
        return None, f"Pre-{reason} snapshot failed"


@router.get("/backup")
def backup_database(background_tasks: BackgroundTasks):
    """Stream a consistent snapshot of the database as a downloadable .db file."""
    db_path = _db_path()
    if not db_path.exists():
        raise HTTPException(404, "Database file not found")

    stamp = _stamp()
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


@router.get("/health")
def database_health():
    """Run a read-only SQLite integrity check against the live database."""
    db_path = _db_path()
    if not db_path.exists():
        raise HTTPException(404, "Database file not found")

    try:
        detail = _integrity_check(db_path)
    except sqlite3.Error as e:
        raise HTTPException(500, f"Database health check failed: {e}")
    healthy = detail == "ok"
    return {
        "ok": healthy,
        "status": "healthy" if healthy else "corrupt",
        "detail": detail,
    }


@router.post("/repair")
def repair_database():
    """Attempt a conservative in-place repair for index-only SQLite corruption."""
    _require_idle()

    try:
        with library_write("database_repair"):
            db_path = _db_path()
            if not db_path.exists():
                raise HTTPException(404, "Database file not found")

            engine.dispose()
            snapshot = _copy_db_files("repair")
            before = _integrity_check(db_path)
            if before == "ok":
                return {
                    "ok": True,
                    "status": "healthy",
                    "detail": before,
                    "before": before,
                    "repaired": False,
                    "snapshot": str(snapshot),
                }

            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute("REINDEX")
                conn.commit()
            finally:
                conn.close()

            after = _integrity_check(db_path)
    except LibraryBusy:
        raise HTTPException(409, "Library is busy â€” a scan, apply, or undo is in progress")
    except sqlite3.Error as e:
        raise HTTPException(500, f"Database repair failed: {e}")

    repaired = after == "ok"
    return {
        "ok": repaired,
        "status": "healthy" if repaired else "corrupt",
        "detail": after,
        "before": before,
        "repaired": repaired,
        "snapshot": str(snapshot),
    }


@router.post("/restore")
async def restore_database(file: UploadFile = File(...)):
    """Replace the live database with an uploaded backup, after validating it."""
    _require_idle()
    db_path = _db_path()

    tmp = Path(tempfile.gettempdir()) / f"stl_restore_{os.getpid()}.db"
    tmp.write_bytes(await file.read())

    # Validate before we touch the live file: must be a sound SQLite DB that
    # actually looks like an STL Studio database.
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
            raise ValueError("this file is not an STL Studio database")
    except Exception as e:
        _safe_unlink(tmp)
        raise HTTPException(400, f"Invalid backup file: {e}")

    # The destructive swap runs under the library write lock (the same one
    # reorganize apply/undo take), so we never replace the DB out from under an
    # in-flight file-moving op — that would leave on-disk paths and DB rows
    # diverged (STUDIO-82). Validation + the upload read above are lock-free
    # (read-only, and the async read must not block while holding the lock).
    try:
        with library_write("database_restore"):
            # Snapshot the current library before we overwrite it, so a
            # wrong-file restore is recoverable (#222).
            snapshot, warning = _try_snapshot_db("restore")

            # Drop pooled connections so the file isn't held open, then swap it in
            # and clear the stale WAL/SHM sidecars that belonged to the old DB.
            engine.dispose()
            for suffix in ("-wal", "-shm"):
                _safe_unlink(Path(str(db_path) + suffix))
            shutil.move(str(tmp), str(db_path))

            # Bring a possibly-older backup's schema up to date.
            Base.metadata.create_all(bind=engine)
            from app.main import _migrate_schema
            _migrate_schema()
    except LibraryBusy:
        _safe_unlink(tmp)
        raise HTTPException(409, "Library is busy — a scan, apply, or undo is in progress")
    return {"ok": True, "snapshot": str(snapshot) if snapshot else None, "warning": warning}


@router.post("/reset")
def reset_database():
    """Delete all data and recreate an empty schema."""
    _require_idle()
    # Under the library write lock so a reset can't wipe the DB while a
    # reorganize apply/undo is mid-move (STUDIO-82).
    try:
        with library_write("database_reset"):
            # Snapshot before wiping so a mis-clicked reset is recoverable (#222).
            snapshot = _snapshot_db("reset")
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            from app.main import _migrate_schema
            _migrate_schema()
    except LibraryBusy:
        raise HTTPException(409, "Library is busy — a scan, apply, or undo is in progress")
    return {"ok": True, "snapshot": str(snapshot) if snapshot else None}


def _safe_unlink(path: Path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

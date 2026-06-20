"""
App-wide library write lock (#324, Phase 2a).

The reorganize *apply* step is the first thing in the app that moves user files on
disk. It must never run concurrently with a scan (which prunes/inserts rows and
holds the `unique=True` constraints on ``Model.folder_path`` / ``STLFile.path``)
or with another apply/undo. The existing ``scanner._scan_lock`` is a non-blocking
in-process lock that only the scanner respects — nothing else honors it.

This module introduces a single process-wide mutex that scan, apply, and undo all
acquire, plus a **persisted marker file** for the file-mutating ops (apply/undo)
so a crash mid-batch is still detectable after restart — an in-memory lock alone
would silently reset to "idle" on the next boot.

Lock ordering: the library write lock is the **outermost** lock. Code holding it
may then take ``scanner._db_lock``; never the reverse. Held only around whole
operations, never around a single SQLite statement, so it can't deadlock the
per-statement DB lock.
"""
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from app.config import settings
from app.utils import utcnow

# The one mutex. A plain (non-reentrant) Lock: scan/apply/undo are mutually
# exclusive whole operations, none nests inside another.
_LOCK = threading.Lock()

# Marker filename, written beside the DB while an apply/undo is in flight.
_MARKER_NAME = "reorg.lock"


class LibraryBusy(Exception):
    """Raised when the library write lock can't be acquired (another scan/apply/
    undo holds it)."""


def data_dir() -> Path:
    """Directory the SQLite DB lives in — where the marker and undo log belong.

    Deliberately *not* under any scan root: a move (or an unplugged drive) could
    make the library root disappear, taking a crash-recovery marker with it. The
    DB dir is the one location guaranteed to be local and present. Falls back to
    the current working directory for in-memory/non-file DBs (tests).
    """
    url = settings.database_url
    if url.startswith("sqlite"):
        if "sqlite:///" in url:
            raw = url.split("sqlite:///", 1)[1]
        else:
            raw = url.split("sqlite://", 1)[1]
        if raw and raw != ":memory:":
            return Path(raw).parent
    return Path.cwd()


def _marker_path() -> Path:
    return data_dir() / _MARKER_NAME


def current_operation() -> dict | None:
    """Return the persisted marker's contents, or None if no apply/undo is in
    flight. A marker present when the lock is *not* held means a prior op crashed
    (stale marker) — surfaced so the caller can warn / recover."""
    try:
        return json.loads(_marker_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_marker(operation: str) -> None:
    marker = {"operation": operation, "pid": os.getpid(), "started_at": utcnow().isoformat()}
    path = _marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Flush + fsync so the marker survives a hard kill right after we start moving.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(marker))
        fh.flush()
        os.fsync(fh.fileno())


def _clear_marker() -> None:
    try:
        _marker_path().unlink()
    except OSError:
        pass


def try_acquire_for_scan() -> bool:
    """Non-blocking acquire for the scanner. Returns False if a scan/apply/undo is
    already running (caller skips, mirroring the old ``_scan_lock`` behavior).
    Scans do not write a persisted marker — a crashed scan is repaired by the
    normal prune passes, not by recovery."""
    return _LOCK.acquire(blocking=False)


def release_scan() -> None:
    """Release a lock taken via :func:`try_acquire_for_scan`."""
    try:
        _LOCK.release()
    except RuntimeError:
        # Releasing an unheld lock — defensive; never crash the scan teardown.
        pass


@contextmanager
def library_write(operation: str, *, timeout: float = 0.0):
    """Acquire the write lock for a file-mutating op (apply/undo) and persist a
    crash-visible marker for its duration.

    ``timeout`` 0 means non-blocking (raise immediately if busy). A positive value
    waits up to that many seconds. Raises :class:`LibraryBusy` if the lock can't be
    taken — the caller maps that to a 409.
    """
    acquired = _LOCK.acquire(timeout=timeout) if timeout > 0 else _LOCK.acquire(blocking=False)
    if not acquired:
        raise LibraryBusy("Another scan, apply, or undo is in progress")
    try:
        _write_marker(operation)
        yield
    finally:
        _clear_marker()
        _LOCK.release()

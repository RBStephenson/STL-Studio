"""
Tests for the app-wide library write lock (#324, Phase 2a).

Covers the safety properties Phase 2 apply depends on: mutual exclusion between
scan and apply/undo, the crash-visible persisted marker, and LibraryBusy on
contention.
"""
import json

import pytest

from app.config import settings
from app.services import write_lock
from app.services.write_lock import LibraryBusy


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point the lock's data dir at a temp file-backed DB url so marker writes
    land somewhere inspectable (the test DB is in-memory otherwise)."""
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/stl.db")
    return tmp_path


def test_marker_written_while_held_and_cleared_after(data_dir):
    marker = data_dir / "reorg.lock"
    assert not marker.exists()
    with write_lock.library_write("apply"):
        assert marker.exists()
        body = json.loads(marker.read_text())
        assert body["operation"] == "apply"
        assert "started_at" in body and "pid" in body
    # Released → marker gone, no stale recovery state.
    assert not marker.exists()
    assert write_lock.current_operation() is None


def test_scan_lock_blocks_apply(data_dir):
    assert write_lock.try_acquire_for_scan() is True
    try:
        # A scan holds the lock — apply must refuse rather than race it.
        with pytest.raises(LibraryBusy):
            with write_lock.library_write("apply"):
                pass
    finally:
        write_lock.release_scan()
    # Once the scan releases, apply can proceed.
    with write_lock.library_write("apply"):
        pass


def test_apply_blocks_scan(data_dir):
    with write_lock.library_write("apply"):
        assert write_lock.try_acquire_for_scan() is False
    # Lock freed after the apply block.
    assert write_lock.try_acquire_for_scan() is True
    write_lock.release_scan()


def test_stale_marker_detected_after_crash(data_dir):
    """A marker present while the lock is NOT held models a crashed apply — the
    persisted file outlives the in-memory lock, so recovery can detect it."""
    marker = data_dir / "reorg.lock"
    marker.write_text(json.dumps({"operation": "apply", "pid": 999, "started_at": "x"}))
    op = write_lock.current_operation()
    assert op is not None and op["operation"] == "apply"


def test_lock_released_on_exception(data_dir):
    with pytest.raises(ValueError):
        with write_lock.library_write("apply"):
            raise ValueError("boom")
    # Marker cleared and lock free despite the error.
    assert write_lock.current_operation() is None
    assert write_lock.try_acquire_for_scan() is True
    write_lock.release_scan()

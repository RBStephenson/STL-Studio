"""Cross-device-safe verified copy primitive (STUDIO-385).

Extracted from reorganize_apply's EXDEV branch — reorganize_apply's own
TestSafeMovePrimitive tests still cover it end-to-end through _safe_move
(monkeypatching os.rename to force the EXDEV path); these test the primitive
directly, without needing to fake a rename failure first.
"""
from __future__ import annotations

import builtins
import os

import pytest

from app.services.safe_copy import copy_verified


def test_copies_content_and_preserves_mtime(tmp_path):
    src = tmp_path / "a" / "head.stl"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"payload")
    dst = tmp_path / "b" / "head.stl"

    src_mtime_ns = src.stat().st_mtime_ns
    copy_verified(str(src), str(dst))

    assert dst.read_bytes() == b"payload"
    # STUDIO-312: dst must carry src's mtime, not a fresh copy-time one, or a
    # caller comparing against a pre-copy fingerprint sees false drift.
    assert dst.stat().st_mtime_ns == src_mtime_ns


def test_does_not_touch_source(tmp_path):
    """Unlike a move, copy_verified never removes src — that decision belongs
    to the caller (reorganize_apply unlinks it to complete a move; the STL
    Installer's default copy-and-keep-source behavior does not)."""
    src = tmp_path / "a" / "head.stl"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"payload")
    dst = tmp_path / "b" / "head.stl"

    copy_verified(str(src), str(dst))

    assert src.exists()
    assert src.read_bytes() == b"payload"


def test_creates_destination_parent_directory(tmp_path):
    src = tmp_path / "head.stl"
    src.write_bytes(b"payload")
    dst = tmp_path / "does" / "not" / "exist" / "head.stl"

    copy_verified(str(src), str(dst))

    assert dst.read_bytes() == b"payload"


def test_clears_stale_tmp_debris_before_staging(tmp_path):
    """STUDIO-314: a prior crashed copy can leave dst.safecopytmp behind; the
    next attempt must clear it rather than fail on it."""
    src = tmp_path / "a" / "head.stl"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"payload")
    dst = tmp_path / "b" / "head.stl"
    dst.parent.mkdir(parents=True)
    stale_tmp = tmp_path / "b" / "head.stl.safecopytmp"
    stale_tmp.write_bytes(b"leftover from a crashed run")

    copy_verified(str(src), str(dst))

    assert dst.read_bytes() == b"payload"
    assert not stale_tmp.exists()


def test_staged_tmp_is_opened_writable_before_fsync(tmp_path, monkeypatch):
    """The staged temp file must be opened for WRITING before it is fsynced.

    STUDIO-408: ``os.fsync`` on a read-only descriptor is legal on POSIX and
    raises ``EBADF`` on Windows, so opening the temp file ``"rb"`` broke every
    folder install and every cross-device move there — while CI, which runs
    Linux only, stayed green throughout.

    This asserts the *precondition* rather than the behaviour, which is a
    deliberate exception to the usual behaviour-first rule: on the only
    platform CI runs, reverting to ``"rb"`` fails nothing at all, so a
    behavioural test cannot guard this. Checking the open mode is portable and
    fails on both platforms, which is the closest available thing to a real
    guard until a Windows CI job exists.
    """
    src = tmp_path / "head.stl"
    src.write_bytes(b"payload")
    dst = tmp_path / "b" / "head.stl"

    modes: list[str] = []
    real_open = builtins.open

    def spy_open(file, mode="r", *args, **kwargs):
        if str(file).endswith(".safecopytmp"):
            modes.append(mode)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    copy_verified(str(src), str(dst))

    assert modes, "expected copy_verified to open the staged temp file"
    read_only = [m for m in modes if not any(c in m for c in "+wa")]
    assert not read_only, (
        f"staged temp file opened read-only {read_only} — os.fsync on that "
        "descriptor raises EBADF on Windows (STUDIO-408)"
    )


def test_size_mismatch_after_copy_raises_and_cleans_up_tmp(tmp_path, monkeypatch):
    src = tmp_path / "head.stl"
    src.write_bytes(b"payload")
    dst = tmp_path / "b" / "head.stl"

    real_getsize = os.path.getsize

    def fake_getsize(path):
        # Report a mismatched size only for the tmp file, so the real
        # post-copy check trips without needing to actually corrupt the copy.
        if str(path).endswith(".safecopytmp"):
            return real_getsize(str(path)) + 1
        return real_getsize(path)

    monkeypatch.setattr(os.path, "getsize", fake_getsize)

    with pytest.raises(OSError, match="size mismatch"):
        copy_verified(str(src), str(dst))

    assert not dst.exists()
    assert not (tmp_path / "b" / "head.stl.safecopytmp").exists()

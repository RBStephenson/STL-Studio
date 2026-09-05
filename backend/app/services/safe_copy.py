"""Cross-device-safe verified file copy (STUDIO-385).

Extracted from ``reorganize_apply._safe_move``'s EXDEV branch: this is the
copy -> fsync -> verify-size -> atomic ``os.replace`` primitive that made that
branch safe, factored out so it isn't duplicated by the STL Installer
(STUDIO-101/386), which needs the same verified-copy guarantee but different
move-vs-copy semantics (the installer defaults to leaving the source in
place; reorganize always removes it to complete a move).

This module never touches ``src`` and never decides whether to remove it —
that decision (move = copy + unlink, copy = just copy) belongs to the caller.
``reorganize_apply._safe_move`` unlinks src itself right after calling this to
complete its move contract; a copy-only caller simply doesn't.
"""
from __future__ import annotations

import os
import shutil


def copy_verified(src: str, dst: str) -> None:
    """Copy src to dst, verified: fsync + size check + atomic replace.

    Creates dst's parent directory if needed. A stale ``dst + ".safecopytmp"``
    left behind by a prior crashed copy is cleared before staging rather than
    treated as a real collision (same STUDIO-314 reasoning reorganize's
    case-only-rename staging already relies on).

    Preserves src's mtime onto dst via ``shutil.copystat`` — callers that
    track a pre-copy (size, mtime_ns) fingerprint (reorganize's undo log does)
    need dst to carry it, not a fresh copy-time mtime, or every cross-device
    move looks "drifted" even though nothing actually changed (STUDIO-312).

    Raises OSError on a post-copy size mismatch, after cleaning up the temp
    file — never leaves debris behind on failure.
    """
    tmp = dst + ".safecopytmp"
    if os.path.exists(tmp):
        os.unlink(tmp)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copyfile(src, tmp)
    shutil.copystat(src, tmp)
    # "rb+", not "rb" (STUDIO-408): os.fsync on a READ-ONLY descriptor is legal
    # on POSIX but raises EBADF on Windows, where it routes to _commit(). With
    # "rb" this function therefore raised on every call on Windows, taking out
    # every cross-device reorganize move and every folder install — on the one
    # platform both features actually ship to. Linux-only CI never saw it.
    # "rb+" neither truncates nor writes, so POSIX behaviour is unchanged; the
    # file already exists because copyfile just created it.
    with open(tmp, "rb+") as fh:
        os.fsync(fh.fileno())
    if os.path.getsize(tmp) != os.path.getsize(src):
        os.unlink(tmp)
        raise OSError(f"size mismatch after copy of {src}")
    os.replace(tmp, dst)

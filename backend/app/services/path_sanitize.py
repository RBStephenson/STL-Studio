"""
OS-aware path-segment sanitization for library reorganize (#323).

A reorganize destination is built from user/model metadata (creator, character,
title) that can contain anything — slashes, reserved device names, trailing
dots, control chars, or be absurdly long. Phase 2 turns these into real
directories, so the rules here are the contract that keeps a move from
producing an un-createable or dangerous path.

Over-length is reported, never silently truncated: the caller marks the entry
ineligible so the user resolves it rather than getting a quietly mangled path.
"""
import re
import unicodedata
from dataclasses import dataclass

# Characters forbidden in a path component on Windows (superset of POSIX needs,
# applied everywhere so a library stays portable across the two deployments).
_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Windows reserved device names (case-insensitive, with or without extension).
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Conservative limits: 255 is the common per-component filesystem cap; 260 is
# the classic Windows MAX_PATH for the full path.
MAX_COMPONENT_LEN = 255
MAX_PATH_LEN = 260

_REPLACEMENT = "_"


@dataclass(frozen=True)
class SanitizedSegment:
    value: str            # cleaned segment safe to use as a directory name
    reserved_name: bool   # original collided with a Windows reserved device name
    over_length: bool     # cleaned value still exceeds MAX_COMPONENT_LEN


def sanitize_segment(name: str) -> SanitizedSegment:
    """Clean a single path component and report reserved-name / over-length flags.

    Steps: NFC-normalize, replace forbidden chars, strip trailing dots/spaces,
    fall back to ``_`` for an empty result, flag reserved device names and
    components that remain over the length cap (not truncated here).
    """
    s = unicodedata.normalize("NFC", name or "")
    s = _FORBIDDEN_RE.sub(_REPLACEMENT, s)
    # Trailing dots/spaces are stripped by Windows on creation — normalize now
    # so the stored path matches what the filesystem would actually produce.
    s = s.rstrip(". ")
    if not s:
        s = _REPLACEMENT

    stem = s.split(".", 1)[0].upper()
    reserved = stem in _RESERVED_NAMES
    if reserved:
        # Prefix so the name no longer matches the reserved device.
        s = f"{_REPLACEMENT}{s}"

    over_length = len(s) > MAX_COMPONENT_LEN
    return SanitizedSegment(value=s, reserved_name=reserved, over_length=over_length)


def path_over_length(full_path: str) -> bool:
    """True if the assembled destination path exceeds the Windows MAX_PATH cap."""
    return len(full_path) > MAX_PATH_LEN

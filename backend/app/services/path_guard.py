"""Centralized path-traversal sanitizer.

Named barrier functions that CodeQL can model as sanitizers for
"path dependence on user-provided values" queries. All realpath + commonpath
containment checks should flow through these functions rather than being
inlined at each call site.
"""
import os
from pathlib import Path


def assert_within_roots(path: str | Path, roots: list[str | Path]) -> str:
    """Resolve *path* and assert it falls within at least one of *roots*.

    Returns the resolved absolute path string. Raises ValueError when the
    resolved path escapes every root (caller converts this to an HTTP 403 or
    a domain-level error as appropriate).
    """
    real = os.path.realpath(str(path))
    for root in roots:
        rs = os.path.realpath(str(root))
        try:
            if os.path.commonpath([real, rs]) == rs:
                return real
        except ValueError:
            continue
    raise ValueError(f"Path escapes allowed roots: {path!r}")


def is_within_roots(path: str | Path, roots: list[str | Path]) -> bool:
    """Return True if *path* resolves within at least one of *roots*."""
    try:
        assert_within_roots(path, roots)
        return True
    except ValueError:
        return False

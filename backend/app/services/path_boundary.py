"""Normalized filesystem boundaries for scan-root membership (STUDIO-229).

The destructive prune helpers in ``services/scanner.py`` each need to answer one
of two questions about a stored path:

* "is this path at or under one of the scan roots we confirmed online this run?"
  — gates every destructive prune, so a wrong answer either deletes live data or
  silently keeps stale rows forever.
* "is this path itself a scan root?" — the stop condition for the ignore-rule
  walk-up, which climbs leaf → root testing ancestors.

Both were implemented as local closures, duplicated across four call sites. This
module holds the single definition so the safety-critical comparison can't drift
between them.

**Why not `services/path_guard.py`.** That module answers a superficially similar
question and is the wrong tool here. ``assert_within_roots()`` uses
``os.path.realpath`` + ``os.path.commonpath``: it resolves symlinks and touches
the filesystem, which is correct for its job (sanitizing user-supplied paths
against traversal, in a form CodeQL can model). Prune membership must instead be
a PURE STRING comparison against what is stored in the database — a model whose
folder was deleted, or whose mount has detached, has to compare identically to a
live one. Routing prune membership through ``path_guard`` would make an offline
root's contents stop matching, which is precisely the mount-detach data-loss
scenario the prune gates exist to prevent. Keep the two separate.

Casing follows the HOST filesystem via ``os.path.normcase`` — case-insensitive on
Windows, case-sensitive on POSIX. That is deliberate here: this answers "does this
path refer to the same directory on this machine", which is a host-dependent
question. It is also why a database is not portable between the Docker and Windows
deployments; making STORED identity host-independent is separate work tracked
under STUDIO-357/STUDIO-359 and must not be conflated with this.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def normalize(path: str | Path) -> str:
    """Fold *path* to its comparison form: separators normalized, case folded per
    host filesystem semantics.

    Pure string manipulation — never touches the filesystem, so a path that no
    longer exists normalizes exactly as it did when it was stored.
    """
    return os.path.normcase(os.path.normpath(str(path)))


@dataclass(frozen=True)
class PathBoundary:
    """An immutable set of normalized roots, answering membership questions.

    Frozen and dependency-free (no SQLAlchemy, no scanner imports) so it is safe
    to build once per run and share read-only across the parallel creator workers.

    An EMPTY boundary matches nothing: both :meth:`contains` and :meth:`is_root`
    return False. Callers must keep treating "no roots" as "prune nothing" — an
    empty boundary is not permission to delete, and this class deliberately cannot
    express "everything".
    """

    roots: tuple[str, ...] = ()

    @classmethod
    def from_paths(cls, paths) -> "PathBoundary":
        """Build from any iterable of paths, normalizing and de-duplicating.

        Blank and None entries are dropped rather than normalized: ``normpath("")``
        returns ``"."``, which would otherwise become a root matching every
        relative path.
        """
        seen: dict[str, None] = {}
        for p in paths or ():
            if not p:
                continue
            seen.setdefault(normalize(p), None)
        return cls(roots=tuple(seen))

    def contains(self, path: str | Path | None) -> bool:
        """True if *path* is one of the roots, or lies beneath one.

        Descendant matching is anchored on a separator so a sibling whose name
        merely starts with a root's name never matches: with root ``/lib/STL``,
        ``/lib/STLBackup`` is NOT contained, while ``/lib/STL/Creator`` is.

        Missing or blank paths return False — the safe direction for every current
        caller, where "not under a root" means "do not prune".
        """
        if not path or not self.roots:
            return False
        n = normalize(path)
        return any(n == r or n.startswith(r + os.sep) for r in self.roots)

    def is_root(self, path: str | Path | None) -> bool:
        """True if *path* is exactly one of the roots (descendants do NOT match).

        Distinct from :meth:`contains` on purpose. The ignore-rule prune climbs
        from a model's folder toward the filesystem root and stops when it steps
        ONTO a scan root, so that a bare-name pattern like ``wip`` still matches
        nested folders while never testing the root itself. Using ``contains``
        there would halt the climb at the first descendant — i.e. immediately —
        and silently stop ignoring anything nested.
        """
        if not path or not self.roots:
            return False
        return normalize(path) in self.roots

    def __bool__(self) -> bool:
        """False when there are no roots, so ``if not boundary:`` reads naturally
        at the early-return guards the prune helpers already use."""
        return bool(self.roots)

    def __len__(self) -> int:
        return len(self.roots)

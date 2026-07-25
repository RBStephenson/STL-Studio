"""Per-subtree grouping-strategy policy (#618, STUDIO-240).

A user can mark any folder subtree as `off` to keep its models out of automatic
variant grouping, or `auto` to hand them back to the proposal engine. The
effective strategy for a model is its nearest configured ancestor's, defaulting
to `auto` when nothing above it is configured.

This module is the public contract for that policy: the accepted values, path
normalisation, and nearest-ancestor resolution. It is deliberately free of
SQLAlchemy, ORM models and the proposal engine, so both the API layer and the
grouping engine can share one implementation without the router importing the
whole engine to resolve a string (STUDIO-240 — it previously reached into
`grouping._norm` and `grouping._resolve_strategy`).

Callers pass raw stored paths; normalisation happens inside, so no call site can
forget it and drift from the policy.

Note `normalize_path` is the grouping engine's path-comparison policy today.
STUDIO-229 introduces a shared filesystem path-boundary abstraction for the
scanner's prune helpers; when it lands, this should converge onto it rather than
keep a parallel notion of what a path boundary is.
"""
from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class SubtreeStrategy(StrEnum):
    """What automatic grouping is allowed to do inside a subtree.

    A `str` enum so persisted values, JSON responses and `== "off"` comparisons
    all keep working unchanged.
    """

    AUTO = "auto"
    OFF = "off"


#: The strategy applied when no ancestor of a model is configured.
DEFAULT_STRATEGY = SubtreeStrategy.AUTO


def normalize_path(path: str) -> str:
    """Normalise a folder path for ancestor comparison.

    Separators are unified to `/` and any trailing separator is dropped, so a
    stored `C:\\lib\\creator\\` and `C:/lib/creator` compare equal.
    """
    return path.replace("\\", "/").rstrip("/")


def parse_strategy(value: str) -> SubtreeStrategy:
    """Coerce a caller-supplied value to a `SubtreeStrategy`.

    Raises `ValueError` on anything else, so an API boundary can turn one
    exception into its 400 rather than each caller hand-rolling a membership
    test against a literal tuple.
    """
    try:
        return SubtreeStrategy(value)
    except ValueError as exc:
        allowed = ", ".join(repr(s.value) for s in SubtreeStrategy)
        raise ValueError(f"strategy must be one of {allowed}; got {value!r}") from exc


def is_within(model_path: str, subtree_path: str) -> bool:
    """True if `model_path` is `subtree_path` or sits beneath it.

    Descendant matching requires a separator boundary, so sibling folders whose
    names merely share a prefix — `.../STL` versus `.../STLBackup` — never match.
    """
    mp = normalize_path(model_path)
    sp = normalize_path(subtree_path)
    return mp == sp or mp.startswith(sp + "/")


def resolve_subtree_strategy(
    model_path: str, strategies: Iterable[tuple[str, str]]
) -> SubtreeStrategy:
    """The effective strategy for `model_path`: nearest configured ancestor wins.

    `strategies` is any iterable of (subtree_path, strategy) pairs as stored,
    in any order; paths are normalised here. Among the ancestors that match, the
    longest path wins — so a nearer `auto` overrides an outer `off`. Equal-length
    matches are ordered by path, so the winner cannot depend on the order rows
    came back from a query (STUDIO-248).

    Unrecognised stored strategy values are ignored rather than raising: the
    write path validates input, and a corrupt row should not break read-only
    resolution for an unrelated subtree.
    """
    best_rank: tuple[int, str] | None = None
    best = DEFAULT_STRATEGY
    for subtree_path, value in strategies:
        if not is_within(model_path, subtree_path):
            continue
        try:
            strategy = SubtreeStrategy(value)
        except ValueError:
            continue
        normalised = normalize_path(subtree_path)
        rank = (len(normalised), normalised)
        if best_rank is None or rank > best_rank:
            best_rank, best = rank, strategy
    return best

"""Configurable scan rules (#31).

Phase 1: folder/file *ignore patterns*. The scanner historically walked every
folder under a scan root; these patterns let a user skip subtrees (work-in-progress
dumps, slicer project folders, "_archive", …) without excluding each model by hand.

Storage: the ``scan_ignore_patterns`` key in the app_settings k/v store (a JSON
list of glob strings). User patterns are *merged* with the built-in defaults
(``_DEFAULT_IGNORE_PATTERNS``) rather than replacing them, so a user can only ever
add to the ignore set — never silently disable behaviour the scanner relies on.

Matching is case-insensitive (the library spans Windows/macOS/Linux drives) and is
evaluated against BOTH:
  * a path's basename ("Supports"), so a bare folder name targets every occurrence; and
  * its full POSIX-normalised path ("*/wip/*"), so a pattern can target a location.

Loaded once at the start of each scan run (see scanner._load_scan_rules) — the walk
consults the compiled matcher per folder, never the DB.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import AppSetting

IGNORE_PATTERNS_KEY = "scan_ignore_patterns"
TAG_RULES_KEY = "scan_tag_rules"
PARTS_NAMES_KEY = "scan_parts_names"

# Built-in ignore patterns, merged with the user's. Empty today (the scanner has
# always walked everything), but the hook makes the merge semantics explicit and
# gives Phase-2/3 work a place to seed sensible defaults.
_DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = ()


@dataclass(frozen=True)
class IgnoreMatcher:
    """An immutable, pre-normalised set of ignore globs.

    Frozen so it is safe to stash in a module global for the duration of a scan
    and share read-only across the parallel creator workers.
    """

    patterns: tuple[str, ...]  # already stripped, lower-cased, de-duplicated

    def matches(self, path: Path) -> bool:
        """True if `path` should be skipped by the scanner.

        A pattern matches when it globs either the basename or the full
        POSIX-normalised path (both lower-cased).
        """
        if not self.patterns:
            return False
        name = path.name.lower()
        full = path.as_posix().lower()
        return any(
            fnmatch.fnmatch(name, p) or fnmatch.fnmatch(full, p)
            for p in self.patterns
        )


def _normalise(raw: object) -> tuple[str, ...]:
    """Strip/lower/de-dupe a sequence of patterns, dropping blanks. Tolerates a
    non-list stored value (e.g. a hand-edited DB row) by treating it as empty."""
    if not isinstance(raw, (list, tuple)):
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        pat = str(item).strip().lower()
        if pat and pat not in seen:
            seen.add(pat)
            out.append(pat)
    return tuple(out)


def load_ignore_matcher(db: Session) -> IgnoreMatcher:
    """Build the IgnoreMatcher from built-in defaults merged with the stored
    ``scan_ignore_patterns`` list. Called once per scan run."""
    row = db.query(AppSetting).filter(AppSetting.key == IGNORE_PATTERNS_KEY).one_or_none()
    user = _normalise(row.value) if row is not None else ()
    return IgnoreMatcher(_normalise(_DEFAULT_IGNORE_PATTERNS + user))


# ---------------------------------------------------------------------------
# Tag-inference rules (#31, Phase 2)
# ---------------------------------------------------------------------------
# A user rule is {"keyword": <literal>, "tag": <auto-tag>}: when a folder/file
# name contains the whole word `keyword` (case-insensitive), `tag` is added to
# the model's auto-tags. These ADD to the built-in _TYPES/_MODIFIERS detection
# in name_parser — they never replace it — and deliberately do NOT feed
# character extraction / variant grouping, so a new tag rule can't reshape how
# products group (only what they're tagged).


@dataclass(frozen=True)
class CompiledTagRule:
    pattern: re.Pattern
    tag: str


def load_tag_rules(db: Session) -> tuple[CompiledTagRule, ...]:
    """Compile the stored ``scan_tag_rules`` into (whole-word pattern, tag) pairs.

    The keyword is regex-escaped, so a user can never inject an invalid or
    catastrophic pattern. De-duplicated on (keyword, tag); blanks dropped.
    Called once per scan run.
    """
    row = db.query(AppSetting).filter(AppSetting.key == TAG_RULES_KEY).one_or_none()
    raw = row.value if (row is not None and isinstance(row.value, list)) else []
    seen: set[tuple[str, str]] = set()
    out: list[CompiledTagRule] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("keyword", "")).strip()
        tag = str(item.get("tag", "")).strip().lower()
        key = (keyword.lower(), tag)
        if not keyword or not tag or key in seen:
            continue
        seen.add(key)
        # (?<!\w)…(?!\w) instead of \b…\b: a plain word-boundary fails when the
        # keyword starts/ends with a non-word char (e.g. "c++"), where \b can't
        # sit next to "+". The lookarounds assert no adjacent word char either way.
        out.append(CompiledTagRule(
            re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)", re.I), tag
        ))
    return tuple(out)


# ---------------------------------------------------------------------------
# Parts/structural folder names (#31, Phase 3)
# ---------------------------------------------------------------------------

def load_parts_names(db: Session) -> frozenset[str]:
    """Stored ``scan_parts_names`` as a lower-cased set of exact folder names.

    These extend the built-in _PARTS_EXACT/_STRUCTURAL_EXACT sets in name_parser:
    a matching folder is never a product boundary nor a variant-grouping
    character. Called once per scan run.
    """
    row = db.query(AppSetting).filter(AppSetting.key == PARTS_NAMES_KEY).one_or_none()
    if row is None or not isinstance(row.value, (list, tuple)):
        return frozenset()
    return frozenset(str(n).strip().lower() for n in row.value if str(n).strip())

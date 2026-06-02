"""
Configurable scan-root folder layouts.

A *layout template* describes the path levels under a scan root, down to and
including the level that names the Creator. Everything below the creator is left
to the scanner's content-driven heuristics (variant/character/model detection in
``scanner._walk_for_models``).

Template grammar (levels separated by ``/``):

  ``{creator}``  this level's folder name is the Creator. Exactly one, and it
                 must be the *last* token (the scanner takes over below it).
  ``{tag}``      a level above the creator whose folder name is captured as an
                 auto-tag on every model beneath it.
  ``{ignore}``   a structural level walked past, carrying no meaning. ``*`` is
                 accepted as a shorthand.

Examples::

  {creator}                  Abe3D/...                 (default — today's layout)
  {tag}/{creator}            Sci-Fi/Abe3D/...          → models tagged "sci-fi"
  {tag}/{tag}/{creator}      Sci-Fi/Mechs/Abe3D/...    → tagged "sci-fi", "mechs"
  {ignore}/{creator}         _incoming/Abe3D/...       → wrapper level skipped
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

CREATOR = "creator"
TAG = "tag"
IGNORE = "ignore"

DEFAULT_TEMPLATE = "{creator}"
_VALID_ROLES = {CREATOR, TAG, IGNORE}
_TOKEN_RE = re.compile(r"\{(\w+)\}")


class LayoutError(ValueError):
    """Raised when a layout template is malformed."""


def parse_template(template: str | None) -> list[str]:
    """Parse a template string into an ordered list of role tokens.

    Raises ``LayoutError`` on invalid input. An empty/blank template defaults to
    ``{creator}``.
    """
    template = (template or "").strip().strip("/\\")
    if not template:
        return [CREATOR]

    roles: list[str] = []
    for raw in re.split(r"[/\\]", template):
        raw = raw.strip()
        if not raw:
            continue
        if raw == "*":
            roles.append(IGNORE)
            continue
        m = _TOKEN_RE.fullmatch(raw)
        if not m:
            raise LayoutError(
                f"Invalid layout level {raw!r} — use {{creator}}, {{tag}}, {{ignore}} or *"
            )
        role = m.group(1).lower()
        if role not in _VALID_ROLES:
            raise LayoutError(
                f"Unknown layout role {{{role}}} — use {{creator}}, {{tag}} or {{ignore}}"
            )
        roles.append(role)

    if roles.count(CREATOR) != 1:
        raise LayoutError("Layout must contain exactly one {creator} level")
    if roles[-1] != CREATOR:
        raise LayoutError("{creator} must be the last level — the scanner detects models below it")
    return roles


def roles_for(template: str | None) -> list[str]:
    """Like ``parse_template`` but never raises — used on the scan hot path.

    An invalid stored template falls back to the default and logs a warning, so a
    bad value can't abort a scan.
    """
    try:
        return parse_template(template)
    except LayoutError as e:
        logger.warning(f"Invalid scan-root layout {template!r}: {e}; falling back to {DEFAULT_TEMPLATE}")
        return [CREATOR]


def iter_creator_dirs(root_path: Path, roles: list[str]) -> list[tuple[Path, list[str]]]:
    """Walk the prefix levels of a layout, returning each creator-level directory
    paired with the ``{tag}`` folder names collected on the path above it."""
    results: list[tuple[Path, list[str]]] = []

    def descend(directory: Path, idx: int, tags: list[str]):
        role = roles[idx]
        try:
            children = sorted(d for d in directory.iterdir() if d.is_dir())
        except (PermissionError, OSError):
            return
        for child in children:
            if role == CREATOR:
                results.append((child, tags))
            else:
                child_tags = tags + [child.name] if role == TAG else tags
                descend(child, idx + 1, child_tags)

    descend(root_path, 0, [])
    return results


def tags_for_path(path: Path, root: Path, roles: list[str]) -> list[str]:
    """Extract the ``{tag}`` folder names for a path at or below the creator level.

    Used when re-walking a single creator or a split pack, where we already know
    the path but still want the layout's above-creator tags.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        return []
    tags: list[str] = []
    for i, role in enumerate(roles):
        if role == TAG and i < len(rel.parts):
            tags.append(rel.parts[i])
    return tags


def creator_depth(roles: list[str]) -> int:
    """0-based index of the creator level within a path relative to the root."""
    return roles.index(CREATOR)

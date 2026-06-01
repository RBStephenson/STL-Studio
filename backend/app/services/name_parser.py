"""
Parse scale, type, and modifiers from folder/file names.
Used to identify product boundaries and auto-generate tags.

Sources checked (in order of priority):
  1. The folder name itself
  2. File names within the folder (STL/image filenames)
  3. Parent folder names up to the creator boundary

Miniature note:
  Miniatures often don't state a ratio scale. They use mm heights (28mm, 75mm)
  or genre keywords (dnd, wargame, tabletop). These are treated as type signals
  rather than scale signals, but are still surfaced as auto_tags.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class NameSignals:
    scales: list[str] = field(default_factory=list)     # ["1:6", "75mm"]
    types: list[str] = field(default_factory=list)       # ["bust", "miniature"]
    modifiers: list[str] = field(default_factory=list)   # ["pre-supported", "uncut"]
    is_product: bool = False
    is_parts: bool = False
    confidence: float = 0.0

    @property
    def auto_tags(self) -> list[str]:
        return list(dict.fromkeys(self.scales + self.types + self.modifiers))


# ---------------------------------------------------------------------------
# Scale patterns
# ---------------------------------------------------------------------------
_SCALE_RATIO = re.compile(r"(?<!\d)1[-/:\s_](\d{1,2})(?!\d)", re.I)

_SCALE_MM = re.compile(
    r"(?<!\d)(14|18|28|30|32|35|40|54|70|75|90|120|180|200|300|350)\s*mm\b",
    re.I,
)

# Scales that imply a collectible statue (not a miniature)
_STATUE_SCALES = {"1:4", "1:5", "1:6", "1:8", "1:9", "1:10", "1:12"}

# Normalise "1_12scale" / "1:6Scale" → "1_12 scale" before ratio regex runs
_SCALE_GLUED = re.compile(r"((?<!\d)1[-/:\s_]\d{1,2})(scale)\b", re.I)

# ---------------------------------------------------------------------------
# Type keywords
# ---------------------------------------------------------------------------
_TYPES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bbust[s]?\b",                    re.I), "bust"),
    (re.compile(r"\bstatue[s]?\b",                  re.I), "statue"),
    (re.compile(r"\bfigure[s]?\b",                  re.I), "figure"),
    (re.compile(r"\bdiorama[s]?\b",                 re.I), "diorama"),
    (re.compile(r"\bchibi[s]?\b",                   re.I), "chibi"),
    (re.compile(r"\bfan[-\s]?art\b",                re.I), "fan art"),
    (re.compile(r"\bkit\b",                         re.I), "kit"),
    # Miniature / tabletop
    (re.compile(r"\bminiature[s]?\b",               re.I), "miniature"),
    (re.compile(r"\bmini[s]?\b",                    re.I), "miniature"),
    (re.compile(r"\btabletop\b",                    re.I), "tabletop"),
    (re.compile(r"\bwargame[s]?\b",                 re.I), "wargame"),
    (re.compile(r"\bd&d\b|dnd\b|dungeons",          re.I), "dnd"),
    (re.compile(r"\brpg\b",                         re.I), "rpg"),
    (re.compile(r"\bterrain\b",                     re.I), "terrain"),
    (re.compile(r"\bscatter\b",                     re.I), "scatter terrain"),
    (re.compile(r"\bhero\b",                        re.I), "hero"),
    (re.compile(r"\bmonster[s]?\b",                 re.I), "monster"),
    (re.compile(r"\bcreature[s]?\b",                re.I), "creature"),
    (re.compile(r"\bvehicle[s]?\b",                 re.I), "vehicle"),
    (re.compile(r"\bprop[s]?\b",                    re.I), "prop"),
    (re.compile(r"\bsupport[-\s]?free\b",           re.I), "support-free"),
]

# ---------------------------------------------------------------------------
# Modifier keywords
# ---------------------------------------------------------------------------
_MODIFIERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bpre[-\s]?supported\b",          re.I), "pre-supported"),
    (re.compile(r"\bpresupported\b",                re.I), "pre-supported"),
    (re.compile(r"\bpre[-\s]?sup\b",                re.I), "pre-supported"),
    (re.compile(r"\bpresup\b",                      re.I), "pre-supported"),
    (re.compile(r"\bsupported\b",                   re.I), "pre-supported"),
    (re.compile(r"\buncut\b",                       re.I), "uncut"),
    (re.compile(r"\bcomplete\b",                    re.I), "complete"),
    (re.compile(r"\bcommercial\b",                  re.I), "commercial"),
    (re.compile(r"\bfree\b",                        re.I), "free"),
    (re.compile(r"\bpatreon\b",                     re.I), "patreon"),
    (re.compile(r"\bnsfw\b",                        re.I), "nsfw"),
    (re.compile(r"\bpinup\b|pin[-\s]up\b",         re.I), "pin-up"),
]

# ---------------------------------------------------------------------------
# Parts folder names (won't be treated as product boundaries)
# ---------------------------------------------------------------------------
_PARTS_EXACT: set[str] = {
    "parts", "extra", "extras", "base", "bases",
    "body", "head", "heads", "torso", "arms", "legs", "feet", "hands",
    "accessories", "accessory", "weapons", "weapon",
    "support", "supports", "supported",
    "stl", "files", "print files", "print",
    "unpainted", "painted", "bits",
}

_PARTS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bpart[s]?\b",        re.I),
    re.compile(r"\bextra[s]?\b",       re.I),
    re.compile(r"^extra[_\s]parte[s]?$", re.I),
    re.compile(r"^part[_\s]extra[s]?$",  re.I),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(name: str) -> NameSignals:
    """Analyse a single name string and return detected signals."""
    return _parse_text(name)


def parse_folder(
    folder_path: str,
    filenames: list[str] | None = None,
    parent_names: list[str] | None = None,
) -> NameSignals:
    """
    Analyse a folder holistically:
      - the folder name itself (highest weight)
      - file names within it (catches scale in STL filename)
      - parent folder names up to creator boundary (inherited scale)
    Returns a merged NameSignals with the best signals found.
    """
    folder_name = Path(folder_path).name
    primary = _parse_text(folder_name)

    # Merge signals from file names
    if filenames:
        for fname in filenames:
            stem = Path(fname).stem
            child = _parse_text(stem)
            _merge_into(primary, child)

    # Merge signals from parent folders (lower priority — don't override
    # is_product/is_parts already set by the folder name itself)
    if parent_names:
        for pname in parent_names:
            parent_sig = _parse_text(pname)
            _merge_into(primary, parent_sig, scales_only=True)

    # Recalculate is_product / confidence after merging
    has_product_signal = bool(primary.scales or primary.types or primary.modifiers)
    lower = folder_name.lower().strip()
    is_parts_exact = lower in _PARTS_EXACT
    is_parts_pattern = any(p.search(lower) for p in _PARTS_PATTERNS)

    if is_parts_exact or is_parts_pattern:
        primary.is_parts = True
        primary.is_product = False
        primary.confidence = 0.7
    elif has_product_signal:
        primary.is_product = True
        primary.confidence = min(
            1.0,
            0.5
            + 0.25 * len(primary.scales)
            + 0.15 * len(primary.types)
            + 0.10 * len(primary.modifiers),
        )
    else:
        primary.confidence = 0.2

    return primary


def children_look_like_parts(child_names: list[str]) -> bool:
    """True if a folder's child directories look like part/structure sub-folders
    (head, body, supported, files…) rather than distinct products.

    A child counts as part-like only if it's an explicit part keyword, a
    structural folder, or a generic non-descriptive token (single/double char or
    purely numeric, e.g. "A", "01"). It deliberately does NOT count low-confidence
    proper-noun names: a pack folder whose children are character names (Electro,
    Kraven, Mysterio…) must recurse into those characters, not collapse into one
    model.
    """
    if not child_names:
        return False

    def _is_part_like(n: str) -> bool:
        if parse(n).is_parts or is_structural_folder(n):
            return True
        token = n.strip().lower()
        return len(token) <= 2 or token.isdigit()

    parts_count = sum(1 for n in child_names if _is_part_like(n))
    return parts_count / len(child_names) >= 0.6


def _strip_signal_tokens(folder_name: str) -> str:
    """Remove scale/type/modifier tokens, returning what's left (may be empty)."""
    name = _SCALE_RATIO.sub("", folder_name)
    name = _SCALE_MM.sub("", name)
    for pattern, _ in _TYPES + _MODIFIERS:
        name = pattern.sub("", name)
    return re.sub(r"[-_\s]+", " ", name).strip(" -_")


def extract_character_name(folder_name: str) -> str:
    """Strip scale/type/modifier tokens from a folder name to infer character."""
    return _strip_signal_tokens(folder_name) or folder_name


# Folder names that describe structure or a variant (support status, container,
# render folder) rather than a character/product. These must never be used as the
# variant-grouping "character" — otherwise every creator's "Presupport" / "75mm" /
# "Unsupported" folder collapses into one giant cross-character bucket.
_STRUCTURAL_EXACT: set[str] = {
    "stl", "stls", "lychee", "chitubox", "files", "print", "print files",
    "presupport", "presupports", "presupported", "pre-supported", "pre supported",
    "supported", "unsupported", "no_supported", "no supported", "no_support",
    "nosupport", "nosupports", "supports", "support",
    "renders", "render", "images", "image", "photos", "photo",
    "preview", "previews", "gallery", "turntable",
    "split", "merged", "solid", "hollow",
}


def is_structural_folder(name: str) -> bool:
    """True if `name` is a structural/variant descriptor, not a character name.

    Catches support-status (presupport/supported/unsupported…), container folders
    (stl/lychee), render folders (renders/images), and folders made up *only* of
    scale/type tokens (e.g. "75mm", "Bust", "1-10 Scale Split").
    """
    low = name.lower().strip()
    if low in _STRUCTURAL_EXACT or low in _PARTS_EXACT:
        return True
    cleaned = re.sub(r"[\s_\-]+", "", _strip_signal_tokens(name)).lower()
    if cleaned in {"", "scale", "scalesplit", "split", "miniature", "mini"}:
        return True
    # Every word is itself structural/scale (e.g. "Render Images",
    # "Colored Turntable", "Supported Solid", "75mm Bust").
    _EXTRA = {"colored", "color", "turntable", "scale"}
    tokens = [t for t in re.split(r"[\s_\-]+", low) if t]
    return bool(tokens) and all(
        t in _STRUCTURAL_EXACT
        or t in _PARTS_EXACT
        or t in _EXTRA
        or re.fullmatch(r"\d+mm", t)            # any mm scale, incl. unlisted sizes
        or not _strip_signal_tokens(t)
        for t in tokens
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _parse_text(text: str) -> NameSignals:
    sig = NameSignals()
    lower = text.lower().strip()

    # Normalise "1_12scale" / "1:6scale" → "1_12 scale" so the ratio regex
    # can match when the scale number runs directly into the word "scale".
    text = _SCALE_GLUED.sub(r"\1 \2", text)

    for m in _SCALE_RATIO.finditer(text):
        tag = f"1:{m.group(1)}"
        if tag not in sig.scales:
            sig.scales.append(tag)

    for m in _SCALE_MM.finditer(text):
        tag = f"{m.group(1)}mm"
        if tag not in sig.scales:
            sig.scales.append(tag)

    # Infer "statue" type from collector-scale ratios when no type is explicit
    if any(s in _STATUE_SCALES for s in sig.scales) and "statue" not in sig.types:
        sig.types.append("statue")

    for pattern, tag in _TYPES:
        if pattern.search(text) and tag not in sig.types:
            sig.types.append(tag)

    for pattern, tag in _MODIFIERS:
        if pattern.search(text) and tag not in sig.modifiers:
            sig.modifiers.append(tag)

    has_signal = bool(sig.scales or sig.types or sig.modifiers)
    is_parts_exact = lower in _PARTS_EXACT
    is_parts_pattern = any(p.search(lower) for p in _PARTS_PATTERNS)

    if is_parts_exact or is_parts_pattern:
        sig.is_parts = True
        sig.confidence = 0.7
    elif has_signal:
        sig.is_product = True
        sig.confidence = min(1.0, 0.4 + 0.2 * len(sig.scales) + 0.15 * len(sig.types))
    else:
        sig.confidence = 0.2

    return sig


def _merge_into(target: NameSignals, source: NameSignals, scales_only: bool = False):
    """Add any new signals from source into target (no duplicates)."""
    for s in source.scales:
        if s not in target.scales:
            target.scales.append(s)
    if not scales_only:
        for t in source.types:
            if t not in target.types:
                target.types.append(t)
        for m in source.modifiers:
            if m not in target.modifiers:
                target.modifiers.append(m)

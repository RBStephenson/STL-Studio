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
from functools import lru_cache
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
    if not child_names:
        return False
    parts_count = sum(
        1 for n in child_names
        if parse(n).is_parts or parse(n).confidence < 0.25
    )
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
    # "full cut" / "full cutted" — print-prep term meaning pre-separated body parts,
    # analogous to "presupported". Must not be treated as a character/product name.
    "cutted",
    "full cut", "full cutted", "full_cut", "full_cutted", "fullcut", "fullcutted",
}


# Support-status / print-format tokens that mark a *variant* of a product rather
# than a distinct product. _strip_signal_tokens already removes scale/type/modifier
# tokens (incl. "pre-supported"/"supported"), but not these, so character_key folds
# them in too. Word boundaries keep "unsupported" from matching inside other words.
_SUPPORT_FORMAT = re.compile(
    r"\b("
    r"un[\s_-]?supported|presupport(?:ed)?|unsupported|supports?|presup|pre|"
    r"no[\s_-]?supports?|nosupports?|"
    r"solid|hollow|"
    r"without|uncut|no[\s_-]?cuts?|full[\s_-]?cut(?:s|ted)?|cut(?:s|ted)?|"
    r"ready[\s_-]?to[\s_-]?slice|readytoslice|"
    r"lychee|chitubox|merged|split"
    r")\b",
    re.I,
)

# Comma-style scale notation ("1,12", "1,4") used by some creators in place of "1:12".
_SCALE_COMMA = re.compile(r"(?<!\d)1\s*,\s*\d{1,2}(?!\d)")

# Any "<number>mm" size, not just the miniature whitelist in _SCALE_MM. Used only by
# the grouping-key path: an unusual size like 160mm/240mm (e.g. two bust sizes of the
# same character) is still just a variant, so it must not split the product identity.
_SCALE_MM_ANY = re.compile(r"(?<!\d)\d{1,4}\s*mm\b", re.I)

# Tokens that survive _strip_signal_tokens/_SUPPORT_FORMAT yet never distinguish one
# product from another: the leftover word "scale" (after "1-9" is stripped from
# "1-9 scale"), container/format words, part/extra markers, NSFW flags, render/version
# noise, and bare numbers. Stripped from the grouping key so e.g. "1-9 scale Ada Wong
# CA3D" and "1-6 Ada Wong CA3D" both reduce to "Ada Wong CA3D". A bare \d+ token folds
# in stray sizes like "15"/"20"; the \b before it keeps the digit in "2B" (a real
# character) intact, since there is no word boundary between "2" and "B".
_VARIANT_JUNK = re.compile(
    r"\b("
    r"scale|stls?|lychee|chitubox|files?|renders?|images?|previews?|photos?|"
    r"extras?|merge[d]?|version|without|cut(?:s|ted)?|nsfw|sfw|"
    r"\d+"
    r")\b",
    re.I,
)


def character_key(name: str, creator_name: str | None = None) -> str:
    """Normalise a folder name to its product identity for variant grouping.

    Strips scale/type/modifier tokens (via _strip_signal_tokens) plus support-status,
    print-format, and non-identifying "junk" tokens, so that e.g.
    "AleCask_32mm_UnSupported" and "AleCask_32mm_Supported_Solid" both reduce to
    "AleCask", "Crimson Wings APC supported" / "…unsupported" both reduce to
    "Crimson Wings APC", and "1-9 scale Ada Wong CA3D" / "1-6 Ada Wong CA3D" both
    reduce to "Ada Wong CA3D". Returns "" when nothing product-identifying remains
    (a pure variant descriptor such as "75mm Unsupported" or "15").

    When creator_name is supplied, trailing tokens that are the creator's own name or
    any concatenation of consecutive creator-name words (e.g. "CA 3D Studios" → also
    strips "CA3D") are removed, collapsing e.g. "Ada Wong CA3D" + "Ada Wong" for that
    creator. The strip is guarded: if nothing would remain, the key is left unchanged.
    """
    # Normalise underscores/dashes to spaces FIRST so the \b-anchored token regexes
    # fire — names like "AleCask_32mm_UnSupported" glue tokens together with "_",
    # which is a regex word char and would otherwise defeat every boundary.
    spaced = re.sub(r"[_\-]+", " ", name)
    spaced = _SCALE_COMMA.sub(" ", spaced)
    base = _strip_signal_tokens(spaced)
    base = _SUPPORT_FORMAT.sub(" ", base)
    base = _SCALE_MM.sub(" ", base)
    base = _SCALE_MM_ANY.sub(" ", base)
    base = _VARIANT_JUNK.sub(" ", base)
    # Treat brackets/parens as separators so "Captain Carl Jenkins (supported)"
    # reduces cleanly to "Captain Carl Jenkins" once the token inside is stripped.
    key = re.sub(r"[\s()\[\]]+", " ", base).strip(" -_()[]")

    if creator_name and key:
        key = _strip_creator_suffix(key, creator_name)

    return key


@lru_cache(maxsize=256)
def _creator_suffix_pattern(creator_name: str) -> re.Pattern | None:
    """Compile a regex matching creator name tokens (and consecutive concatenations)
    as a trailing suffix.  "CA 3D Studios" generates tokens ["ca", "3d", "studios"]
    plus all consecutive joins: "ca3d", "3dstudios", "ca3dstudios".
    Cached per creator name so repeated calls during a scan are free.
    """
    tokens = [t for t in re.split(r"[\s\-_]+", creator_name.lower()) if t]
    if not tokens:
        return None
    aliases: set[str] = set(tokens)
    for length in range(2, len(tokens) + 1):
        for i in range(len(tokens) - length + 1):
            aliases.add("".join(tokens[i : i + length]))
    # Longest first so the alternation prefers "ca3dstudios" over "ca3d" over "ca".
    alts = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    # Require at least one leading space so we never strip the whole key when it
    # is nothing but a creator tag (guard handled in _strip_creator_suffix).
    return re.compile(r"(?:\s+\b(?:" + alts + r")\b)+\s*$", re.I)


def _strip_creator_suffix(key: str, creator_name: str) -> str:
    """Remove trailing creator-tag tokens from a grouping key.
    Falls back to the original key when the result would be empty.
    """
    pattern = _creator_suffix_pattern(creator_name)
    if not pattern:
        return key
    stripped = pattern.sub("", key).strip()
    return stripped if stripped else key


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

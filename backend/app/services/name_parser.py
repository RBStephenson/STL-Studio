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
    # Garage-kit / statue scene (multi-word patterns first so "garage kit"
    # doesn't get swallowed by the bare "kit" match below)
    (re.compile(r"\bgarage[-\s]?kit[s]?\b",         re.I), "garage kit"),
    (re.compile(r"\bgk\b",                          re.I), "garage kit"),
    (re.compile(r"\bresin\b",                       re.I), "resin"),
    (re.compile(r"\bmaquette[s]?\b",                re.I), "maquette"),
    (re.compile(r"\bcollectible[s]?\b",             re.I), "collectible"),
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

# User-configured tag-inference rules (#31, Phase 2): extra (pattern, tag) pairs
# loaded from app_settings and merged into type detection at scan time. Module
# global, set once per scan run by the scanner (mirrors its override loading);
# default empty so non-scan callers see only the built-in rules. These ADD tags
# only — they do not feed _strip_signal_tokens / character_key, so a tag rule
# never changes how products group.
_user_type_rules: tuple[tuple[re.Pattern, str], ...] = ()


def set_tag_rules(rules: list[tuple[re.Pattern, str]] | None) -> None:
    """Replace the active user tag-inference rules. Pass None/empty to clear."""
    global _user_type_rules
    _user_type_rules = tuple(rules or ())

# ---------------------------------------------------------------------------
# Modifier keywords
# ---------------------------------------------------------------------------
_MODIFIERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bpre[-\s]?supported\b",          re.I), "pre-supported"),
    (re.compile(r"\bpresupported\b",                re.I), "pre-supported"),
    (re.compile(r"\bpre[-\s]?sup\b",                re.I), "pre-supported"),
    (re.compile(r"\bpresup\b",                      re.I), "pre-supported"),
    (re.compile(r"\buncut\b",                       re.I), "uncut"),
    (re.compile(r"\bcomplete\b",                    re.I), "complete"),
    (re.compile(r"\bcommercial\b",                  re.I), "commercial"),
    (re.compile(r"\bfree\b",                        re.I), "free"),
    (re.compile(r"\bpatreon\b",                     re.I), "patreon"),
    (re.compile(r"\bnsfw\b",                        re.I), "nsfw"),
    (re.compile(r"\bpinup\b|pin[-\s]up\b",         re.I), "pin-up"),
    # Statue/collectible edition tags — real product-distinguishing SKU variants,
    # not print-prep noise. "standard"/"regular" deliberately excluded: too generic,
    # would strip real character names (e.g. "1.JSC Batgirl Regular").
    (re.compile(r"\bdeluxe\b",                      re.I), "deluxe"),
    (re.compile(r"\bexclusive\b",                   re.I), "exclusive"),
    (re.compile(r"\blimited[-\s]?edition\b",        re.I), "limited edition"),
    (re.compile(r"\bbonus\b",                       re.I), "bonus"),
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

# User-configured extra parts/structural folder names (#31, Phase 3): exact,
# lower-cased folder names that should be treated like the built-in _PARTS_EXACT
# / _STRUCTURAL_EXACT sets — never a product boundary, never a variant-grouping
# character. Module global set once per scan run by the scanner; empty by
# default so non-scan callers see only the built-ins.
_user_parts_names: frozenset[str] = frozenset()


def set_parts_names(names: frozenset[str] | set[str] | None) -> None:
    """Replace the active user parts/structural folder names (lower-cased)."""
    global _user_parts_names
    _user_parts_names = frozenset(n.lower() for n in names) if names else frozenset()


def _is_parts_name(low: str) -> bool:
    """Built-in OR user-configured parts folder name (exact, already lower)."""
    return low in _PARTS_EXACT or low in _user_parts_names


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
    is_parts_exact = _is_parts_name(lower)
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


# ---------------------------------------------------------------------------
# Structured attributes — typed scalar values, not flat tags. Each describes a
# *variant* dimension of a product (how it was prepared / sliced), surfaced as a
# filterable attribute rather than buried in the display name. Separators are
# normalised to spaces first so "_"/"-"-glued tokens still hit the \b anchors.
# ---------------------------------------------------------------------------

# Order matters: more specific statuses are tested first so "unsupported" and
# "pre-supported" are never misread as plain "supported".
_SUPPORT_STATUS_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:un[\s_-]?supported|no[\s_-]?supports?|nosupports?)\b", re.I), "unsupported"),
    (re.compile(r"\b(?:pre[\s_-]?supported|presupport(?:ed)?|pre[\s_-]?sup|presup)\b", re.I), "pre-supported"),
    (re.compile(r"\bsupport(?:ed|s)?\b", re.I), "supported"),
]

_CUT_STATUS_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:full[\s_-]?cut(?:s|ted)?|fullcut(?:ted)?)\b", re.I), "full-cut"),
    (re.compile(r"\bhollow(?:ed)?\b", re.I), "hollow"),
    (re.compile(r"\bsolid\b", re.I), "solid"),
    (re.compile(r"\bsplit\b", re.I), "split"),
    (re.compile(r"\bmerged?\b", re.I), "merged"),
]

_SLICER_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\blychee\b", re.I), "lychee"),
    (re.compile(r"\bchitubox\b", re.I), "chitubox"),
]

# "v2", "v1.1" style version markers. Word forms ("final", "fixed") are
# deliberately NOT treated as versions — they collide with real names such as
# "Final Fantasy".
_VERSION_NUM = re.compile(r"\bv(\d+(?:\.\d+)?)\b", re.I)


def _spaced(name: str) -> str:
    """Normalise underscore/dash separators to spaces for \\b-anchored matching."""
    return re.sub(r"[_\-]+", " ", name)


def _first_match(name: str, rules: list[tuple[re.Pattern, str]]) -> Optional[str]:
    spaced = _spaced(name)
    for pattern, value in rules:
        if pattern.search(spaced):
            return value
    return None


def support_status(name: str) -> Optional[str]:
    """"unsupported" | "pre-supported" | "supported" | None."""
    return _first_match(name, _SUPPORT_STATUS_RULES)


def cut_status(name: str) -> Optional[str]:
    """"full-cut" | "hollow" | "solid" | "split" | "merged" | None."""
    return _first_match(name, _CUT_STATUS_RULES)


def slicer(name: str) -> Optional[str]:
    """"lychee" | "chitubox" | None."""
    return _first_match(name, _SLICER_RULES)


def version(name: str) -> Optional[str]:
    """Normalised version marker ("v2", "v1.1") or None."""
    m = _VERSION_NUM.search(_spaced(name))
    return f"v{m.group(1)}" if m else None


def parsed_attributes(name: str) -> dict[str, str]:
    """All structured variant attributes detected in a name, omitting None."""
    detected = {
        "support_status": support_status(name),
        "cut_status": cut_status(name),
        "slicer": slicer(name),
        "version": version(name),
    }
    return {k: v for k, v in detected.items() if v is not None}


# ---------------------------------------------------------------------------
# Display name — a clean, human-readable product name for the UI, derived from
# the same strip pipeline as the variant-grouping key but title-cased and with
# version markers removed.
# ---------------------------------------------------------------------------

def _titlecase_token(token: str) -> str:
    """Capitalise a token while preserving stylised forms.

    Left untouched: tokens containing a digit ("2B", "CA3D"), already
    mixed-case tokens ("McGee"), and short all-caps acronyms ("APC", "JSC").
    Everything else is capitalised ("ada" -> "Ada").
    """
    if any(ch.isdigit() for ch in token):
        return token
    if token != token.lower() and token != token.upper():
        return token
    if token.isupper() and len(token) <= 4:
        return token
    return token.capitalize()


def display_name(folder_name: str, creator_name: str | None = None) -> str:
    """Derive a clean, title-cased display name from a raw folder name.

    Reuses character_key (scale/type/modifier/support-format/junk + creator-tag
    stripping), additionally drops "v2"-style version markers, then title-cases
    with a guard for stylised tokens. Falls back to the raw folder name when
    nothing product-identifying remains (a pure variant descriptor).
    """
    key = character_key(folder_name, creator_name)
    key = _VERSION_NUM.sub(" ", key)
    key = re.sub(r"\s+", " ", key).strip(" -_")
    if not key:
        return folder_name
    return " ".join(_titlecase_token(t) for t in key.split())


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
    r"un[\s_-]?supported|presupport(?:ed)?|unsupported|support(?:ed|s)?|presup|pre|"
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

    When creator_name is supplied, a trailing creator-name *tag* is removed so e.g.
    "Ada Wong CA3D" collapses with "Ada Wong" for that creator. Only forms unlikely to
    coincide with a real character word are stripped — a glued abbreviation of 2+
    consecutive creator words ("CA 3D Studios" → "CA3D") or the full creator name. An
    individual word of a multi-word creator ("Dragon" from "Dragon Studios") is left
    alone, so "Red Dragon" keeps its identity. The strip is guarded: if nothing would
    remain, the key is left unchanged.
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
    # Treat brackets/parens/periods as separators so "Captain Carl Jenkins (supported)"
    # reduces cleanly to "Captain Carl Jenkins" once the token inside is stripped.
    # Periods are included so a leading number+dot prefix like "1.JSC …" doesn't leave
    # an orphaned "." after the digit is removed by _VARIANT_JUNK.
    key = re.sub(r"[\s()\[\].]+", " ", base).strip(" -_()[]")

    if creator_name and key:
        key = _strip_creator_suffix(key, creator_name)

    return key


@lru_cache(maxsize=256)
def _creator_suffix_pattern(creator_name: str) -> re.Pattern | None:
    """Compile a regex matching a trailing creator-name tag.

    Two forms are stripped, both unlikely to collide with a real character word:
      * a glued concatenation of 2+ consecutive creator words — the abbreviation
        case ("CA 3D Studios" → "CA3D", "3DStudios", "CA3DStudios"); and
      * the creator's full name spelled out ("CA 3D Studios").
    A lone word is stripped ONLY when it is the creator's *entire* name (e.g.
    "Ghamak"). Individual words of a multi-word name ("Dragon" from "Dragon
    Studios") are deliberately NOT stripped, so a character whose name ends in such
    a word ("Red Dragon") keeps its identity. Cached per creator name.
    """
    tokens = [t for t in re.split(r"[\s\-_]+", creator_name.lower()) if t]
    if not tokens:
        return None
    aliases: set[str] = set()
    if len(tokens) == 1:
        aliases.add(tokens[0])
    else:
        # Glued concatenations of 2+ consecutive words (abbreviation-style tags).
        for length in range(2, len(tokens) + 1):
            for i in range(len(tokens) - length + 1):
                aliases.add("".join(tokens[i : i + length]))
        # The full name spelled out with spaces.
        aliases.add(" ".join(tokens))
    # Longest first so the alternation prefers the most specific match.
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
    if low in _STRUCTURAL_EXACT or _is_parts_name(low):
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
        or _is_parts_name(t)
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

    # User tag-inference rules (#31) — additive, after the built-ins.
    for pattern, tag in _user_type_rules:
        if pattern.search(text) and tag not in sig.types:
            sig.types.append(tag)

    for pattern, tag in _MODIFIERS:
        if pattern.search(text) and tag not in sig.modifiers:
            sig.modifiers.append(tag)

    has_signal = bool(sig.scales or sig.types or sig.modifiers)
    is_parts_exact = _is_parts_name(lower)
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

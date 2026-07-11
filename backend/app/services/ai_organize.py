"""Normalize STL file part names and categories for a miniature figure library.

Two-stage pipeline:
  1. Fast Python heuristics handle the mechanical patterns (Sup_ detection,
     keyword-based part type, name cleanup from filename).
  2. An optional LLM pass refines anything left ambiguous.

The LLM is optional — if no URL is configured the heuristic results are
returned directly. This makes the feature useful even without Ollama.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx
from anthropic import Anthropic  # module symbol so tests can monkeypatch it

_log = logging.getLogger(__name__)

# Fallback request timeout (seconds) when a caller doesn't specify one. The
# real value normally comes from the assigned AiApiConfig.request_timeout.
_DEFAULT_TIMEOUT = 10.0

# Anthropic-only knobs. The organize response is a small JSON object, so a
# modest cap is plenty; effort maps to an extended-thinking budget (mirrors the
# painting guide generator).
_ANTHROPIC_MAX_TOKENS = 4096
_EFFORT_THINKING_BUDGET = {"low": 0, "medium": 4096, "high": 10000}

# Same reasoning for the OpenAI-compatible (Ollama etc.) path: without an
# explicit cap, a local model that gets stuck (repetition, a quantization that
# doesn't respect response_format cleanly, ...) has nothing stopping it from
# generating until it hits the *server's* own context limit — minutes later,
# with a truncated, unparseable response as the only result. Bounding the
# reply here means a misbehaving model fails fast instead of slow.
#
# 2048 was too thin in practice: a model that emits hidden reasoning into its
# own field (rather than the visible "thinking" block the "think": False
# toggle below is meant to suppress — some model tags don't honor that toggle
# at all) can burn the *entire* budget mid-thought and never reach the actual
# JSON answer, returning HTTP 200 with empty content and finish_reason
# "length". Sized to roughly match the Anthropic path's headroom (4096 base,
# up to +10000 for extended thinking) instead of assuming a well-behaved model
# needs only a couple hundred tokens for this task.
_OPENAI_MAX_TOKENS = 8192


# Matches the ``scheme://userinfo@`` prefix of a URL anywhere in a string, so we
# can scrub credentials both from bare endpoint URLs and from URLs echoed inside
# exception messages / response bodies.
_URL_CRED_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/@\s]*@")


def _redact_url(text: str) -> str:
    """Strip any userinfo (``user:password@``) from URLs within ``text``.

    A user could configure an endpoint like ``https://user:secret@host:11434``;
    we log the endpoint in the request trace and error details, so drop the
    credential component before it reaches a log or the surfaced error message.
    Works on a bare URL or a URL embedded in a larger string (e.g. an httpx
    exception message).
    """
    return _URL_CRED_RE.sub(lambda m: m.group("scheme"), text)


@dataclass
class LlmOutcome:
    """Result of the LLM refinement stage, so callers can tell what happened.

    ``status`` is one of:
      - "disabled":  no URL/model configured — heuristics only, by design.
      - "skipped":   LLM configured but heuristics resolved everything.
      - "ok":        LLM was called and returned suggestions.
      - "error":     LLM was called but failed; ``detail`` explains why.
    """
    status: str = "disabled"
    detail: str | None = None
    suggestions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OrganizeResult:
    """Merged suggestions plus the outcome of the optional LLM pass."""
    suggestions: list[dict[str, Any]]
    llm: LlmOutcome


_SENSITIVE_LOG_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "token",
    "password",
    "secret",
    "bearer",
}


def _sanitize_log_value(key: str, value: Any) -> Any:
    key_l = key.lower()
    if key_l in _SENSITIVE_LOG_KEYS or any(s in key_l for s in ("token", "secret", "password", "api_key", "apikey", "authorization")):
        return "[REDACTED]"
    return value


def _log_step(step: str, **kw: Any) -> None:
    parts = " ".join(f"{k}={_sanitize_log_value(k, v)!r}" for k, v in kw.items())
    _log.info("ai_organize %s %s", step, parts)


# ---------------------------------------------------------------------------
# Part-type keyword map — checked against the stem after stripping Sup_/S_ prefix
# and extension. Longer / more-specific tokens first.
# "armor" must appear before "arm" to avoid the substring matching "arm" in "armor".
# ---------------------------------------------------------------------------
_PART_TYPE_KEYWORDS: list[tuple[list[str], str]] = [
    (["presupported", "supported"], None),          # these alone don't give a type
    (["fullbody", "full_body", "complete"], "Full"),
    # Armor before Body so "armor_chest" → Armor rather than Body (chest keyword).
    # Armor before Arm so "armor" substring doesn't match the bare "arm" keyword.
    (["armor", "armour", "pauldron", "vambrace", "cuirass", "breastplate",
      "gorget", "bracer", "spaulder", "chainmail"], "Armor"),
    (["helm", "helmet", "head", "skull", "face", "hair", "hood"], "Head"),
    (["torso", "chest", "body", "trunk", "abdomen"], "Body"),
    (["shoulderpad", "shoulder"], "Shoulder"),
    (["upperarm", "forearm", "lowerarm"], "Arm"),
    (["arm"], "Arm"),
    (["hand", "fist", "grip", "gauntlet"], "Hand"),
    (["upperleg", "lowerleg", "thigh", "shin", "knee"], "Leg"),
    (["leg"], "Leg"),
    (["foot", "feet", "boot", "shoe", "greave"], "Foot"),
    (["base", "plinth", "stand"], "Base"),
    (["sword", "blade", "axe", "mace", "hammer", "spear", "lance",
      "staff", "wand", "bow", "crossbow", "gun", "rifle", "pistol",
      "knife", "dagger", "flail", "morningstar", "weapon", "weap"], "Weapon"),
    (["shield", "buckler", "targe"], "Shield"),
    (["cape", "cloak", "mantle", "tabard", "scabbard", "holster",
      "belt", "backpack", "pack", "wing", "tail", "accessory"], "Accessory"),
]

# Common misspellings found in STL file names from miniature creators.
_SPELLING_FIXES: dict[str, str] = {
    "helmit":       "helmet",
    "helmt":        "helmet",
    "shiled":       "shield",
    "sheild":       "shield",
    "sholder":      "shoulder",
    "sholeder":     "shoulder",
    "shouler":      "shoulder",
    "gauntelt":     "gauntlet",
    "guantlet":     "gauntlet",
    "guantelt":     "gauntlet",
    "pauldorn":     "pauldron",
    "accesorry":    "accessory",
    "acessory":     "accessory",
    "accessery":    "accessory",
    "wepon":        "weapon",
    "swrod":        "sword",
    "bace":         "base",
    "presuported":  "presupported",
    "presuppored":  "presupported",
    "presupored":   "presupported",
    "torse":        "torso",
    "torce":        "torso",
    "legg":         "leg",
    "leggs":        "legs",
}

_SUP_PREFIX_RE = re.compile(r"^(?:sup_|\(s\)_?|s_sup_)", re.IGNORECASE)
_SUP_INFIX_RE  = re.compile(r"[\-_ ]?(?:pre)?supported", re.IGNORECASE)


def _stem(filename: str) -> str:
    """Return filename without extension, lowercased."""
    return re.sub(r"\.[^.]+$", "", filename).lower()


def clean_name(filename: str) -> str:
    """Turn a raw filename into a readable label.

    Works on the original filename (before lowercasing) so CamelCase can be
    detected. Extension and Sup_ prefix/infix are stripped, then "Supported"
    is prepended to the final name if the file was a supported variant.

    Public (no leading underscore): also used by scanner.py to auto-fill
    STLFile.part_name the first time a file is indexed, so a freshly
    scanned/imported file gets a real, saved name — not just the dimmed
    filename-derived placeholder the UI shows for a genuinely empty one.
    """
    # Remove extension
    s = re.sub(r"\.[^.]+$", "", filename)
    # Detect supported variant before stripping markers
    is_supported = bool(_SUP_PREFIX_RE.match(s) or _SUP_INFIX_RE.search(s))
    s = _SUP_PREFIX_RE.sub("", s)
    s = _SUP_INFIX_RE.sub("", s)
    # Split CamelCase BEFORE lowercasing so we can detect word boundaries
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)   # "STLFile" → "STL File"
    # Replace underscores/hyphens with spaces
    s = re.sub(r"[_\-]+", " ", s)
    # Collapse extra whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Remove version tokens: v1, v2, ver2, V3
    s = re.sub(r"\s+v(?:er)?\d+\s*$", "", s, flags=re.IGNORECASE).strip()
    # Remove unit suffixes: 32mm, 25mm
    s = re.sub(r"\s+\d+mm\s*$", "", s, flags=re.IGNORECASE).strip()
    # Format each word: strip leading zeros from numeric tokens ("01" → "1"),
    # fix spelling, then title-case.
    def _fmt(w: str) -> str:
        if w.isdigit():
            return str(int(w))
        fixed = _SPELLING_FIXES.get(w.lower(), w.lower())
        return fixed.capitalize()

    words = s.split()
    result = " ".join(_fmt(w) for w in words) if words else ""
    return ("Supported " + result).strip() if is_supported else result


def _infer_part_type(stem: str) -> str | None:
    """Return a part type from keyword scan of the file stem."""
    # Apply spelling corrections word-by-word so e.g. "shiled" → "shield" matches.
    corrected = " ".join(
        _SPELLING_FIXES.get(w, w) for w in re.split(r"[\s_\-]+", stem.lower())
    )
    for keywords, ptype in _PART_TYPE_KEYWORDS:
        if ptype is None:
            continue
        for kw in keywords:
            if kw in corrected:
                return ptype
    return None


def _is_sup(filename: str) -> bool:
    low = filename.lower()
    return bool(_SUP_PREFIX_RE.match(low) or _SUP_INFIX_RE.search(low))


def _find_base(filename: str, all_filenames: list[str]) -> str | None:
    """For a presupported file, try to find the base file in the list."""
    stem = _stem(filename)
    # Remove the Sup_ prefix / infix to get the candidate base stem
    candidate = _SUP_PREFIX_RE.sub("", stem)
    candidate = _SUP_INFIX_RE.sub("", candidate).strip("_- ")

    for other in all_filenames:
        if other == filename:
            continue
        if _stem(other) == candidate or _stem(other) == candidate.lower():
            return other
    # Fuzzy: check if any non-sup file's stem is a substring of our candidate
    for other in all_filenames:
        if other == filename or _is_sup(other):
            continue
        other_stem = _stem(other)
        if other_stem and other_stem in candidate:
            return other
    return None


def heuristic_pass(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply naming-convention heuristics without any LLM call.

    Returns a list of suggestion dicts (same shape the LLM returns), only
    including files where at least one field changed.
    """
    all_filenames = [f["filename"] for f in files]
    suggestions: list[dict[str, Any]] = []

    for f in files:
        fid       = f["id"]
        filename  = f["filename"]
        cur_type  = f.get("part_type")
        cur_name  = f.get("part_name")
        stem      = _stem(filename)

        is_sup         = _is_sup(filename)
        new_type       = _infer_part_type(stem) or cur_type
        new_name       = clean_name(filename) or cur_name
        sup_base       = _find_base(filename, all_filenames) if is_sup else None

        changed = (
            (new_type != cur_type and new_type is not None) or
            (new_name != cur_name and new_name) or
            sup_base is not None
        )
        if changed:
            suggestions.append({
                "id": fid,
                "part_type": new_type,
                "part_name": new_name,
                "sup_base_filename": sup_base,
            })

    _log_step("heuristic_done", input=len(files), suggestions=len(suggestions))
    return suggestions


# ---------------------------------------------------------------------------
# link_sups strategy: pure heuristic, no LLM call — matches a currently-
# unlinked "sup"/"supported"/"hollowed"-named file to its likely base part by
# name, for the reviewer to confirm before it's saved as sup_of_id.
# ---------------------------------------------------------------------------

# Deliberately broader than _SUP_PREFIX_RE/_SUP_INFIX_RE above (which only
# recognize "sup_"/"(s)_"/"s_sup_" prefixes and "(pre)supported" as an
# infix): this strategy's own request is "sup", "supported", or "hollowed" as
# a standalone word anywhere in the name, matched on the word boundary so
# "Superman" or "Supply Crate" don't false-positive on the bare "sup" form.
_LINK_KEYWORD_RE = re.compile(r"\b(?:sup|supported|hollowed)\b", re.IGNORECASE)


def _norm_name(name: str) -> str:
    """Lowercase, separator-normalized comparison key for link_sups matching."""
    s = re.sub(r"[_\-]+", " ", name)
    return re.sub(r"\s+", " ", s).strip().lower()


def _match_keys(f: dict[str, Any]) -> list[str]:
    """Name(s) to check/match this file under, filename first.

    The filename is the reliable signal for this pairing pattern — a sup and
    its base almost always share the same filename stem plus a keyword,
    even on a library where part_name has drifted (independently re-typed,
    copy-pasted, or produced by an earlier/buggier AI Organize run — real
    data has seen e.g. two *different* physical parts both labeled exactly
    "Escaraba 1 Base" by part_name alone, #967-follow-up). part_name is
    still checked second, for the rarer case where a file's name was fixed
    up without renaming the file itself.
    """
    keys = []
    fn_key = _norm_name(_stem(f.get("filename", "")))
    if fn_key:
        keys.append(fn_key)
    pn = (f.get("part_name") or "").strip()
    if pn:
        pn_key = _norm_name(pn)
        if pn_key and pn_key not in keys:
            keys.append(pn_key)
    return keys


def heuristic_link_sups(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match each currently-unlinked, sup/supported/hollowed-named file to
    its likely base part by name.

    Two deliberate restrictions, both from the feature request this
    implements directly:
      1. Only a file with no sup_of_id already set is considered a candidate
         to link — an existing link (however it got there) is never
         second-guessed or overwritten by this heuristic.
      2. Only a file whose name contains one of the link keywords is ever
         treated as the "sup" side of a match. A plain-named file is only
         ever a match *target* (a base), never linked TO another file by
         this pass — this is a rescue for the common "loose supported
         variant, never linked" case, not a general fuzzy-matching pass
         across the whole file list.

    See _match_keys for why matching tries the filename before part_name.
    """
    suggestions: list[dict[str, Any]] = []

    # Index every plain (non-keyword) file under each of its match keys —
    # filename keys inserted first, so a part_name collision (two different
    # files sharing a mislabeled part_name) can never displace a correct
    # filename-based entry.
    base_by_key: dict[str, dict[str, Any]] = {}
    for f in files:
        for key in _match_keys(f):
            if not _LINK_KEYWORD_RE.search(key):
                base_by_key.setdefault(key, f)

    for f in files:
        if f.get("sup_of_id") is not None:
            continue
        base: dict[str, Any] | None = None
        for key in _match_keys(f):
            if not _LINK_KEYWORD_RE.search(key):
                continue
            candidate_key = _norm_name(_LINK_KEYWORD_RE.sub(" ", key))
            if not candidate_key:
                continue
            base = base_by_key.get(candidate_key)
            if base is not None:
                break
        if base is None or base["id"] == f["id"]:
            continue
        suggestions.append({
            "id": f["id"],
            "part_type": None,
            "part_name": None,
            "sup_base_filename": base["filename"],
        })

    _log_step("link_sups_done", input=len(files), suggestions=len(suggestions))
    return suggestions


# ---------------------------------------------------------------------------
# LLM refinement (optional)
# ---------------------------------------------------------------------------

# The app's fixed category list (mirrors frontend/src/pages/model-detail/utils.ts
# PART_TYPE_SUGGESTIONS — the only categories the Category combobox offers).
# Keep the two in sync by hand; there's no shared build step across the
# Python/TypeScript boundary. The AI must pick from this exact list so its
# output lines up with what the UI (and _normalize_type below) expects,
# instead of inventing near-miss variants like "Accessory" vs "Accessories".
CANONICAL_PART_TYPES = [
    "Head", "Torso", "Body", "Full",
    "Right Arm", "Left Arm", "Arms",
    "Right Leg", "Left Leg", "Legs",
    "Hands", "Feet", "Base",
    "Weapon", "Shield", "Armor", "Cloak", "Cape",
    "Hair", "Wings", "Tail", "Accessories",
]

# Appended to both prompts below (#910-follow-up): the "think": False request
# field (see _llm_refine_openai) only suppresses reasoning on models Ollama
# natively recognizes as hybrid-reasoning — a model whose chat template
# reasons unconditionally regardless of that flag ignores it outright. A
# plain-language instruction in the prompt text itself is a second, largely
# independent lever: even a model that won't honor the API flag will often
# still respect being told directly not to reason, measurably cutting both
# latency and the odds of a long reasoning tangent degrading into repetition
# before it ever reaches the answer. This does not replace response_schema
# below — schema-constrained decoding forces the final shape regardless of
# what the model does beforehand; this is about not spending the whole
# max_tokens budget getting there.
_NO_REASONING_SUFFIX = (
    "\n\nDo not think, plan, or explain before answering. Output ONLY the "
    "JSON object described above as your entire response — no reasoning, "
    "no markdown fence, no text before or after it."
)

_SYSTEM_PROMPT = ("""You are an assistant that normalizes 3D-printing STL file names for a miniature figure library.

Given a JSON list of STL files with heuristically-suggested part_type and part_name, refine only what is wrong or missing.

Rules:
1. part_type: one category from this exact list — {part_types}. Null if truly unknowable. Never invent a category outside this list.
2. part_name: a short human-readable label (e.g. "Right Arm", "Helmeted Head"). Strip underscores, extensions, and redundant tokens.
3. sup_base_filename: if this file is a presupported variant, return the EXACT filename of its base counterpart in the list. Otherwise null.
4. Omit files where the existing heuristic suggestions are already correct.
5. Return ONLY the JSON object — no markdown, no explanation.

Format: {{"files": [{{"id": <int>, "part_type": <str|null>, "part_name": <str|null>, "sup_base_filename": <str|null>}}, ...]}}""".format(part_types=", ".join(CANONICAL_PART_TYPES))
    + _NO_REASONING_SUFFIX)

# Mirrors _SYSTEM_PROMPT's format above, for response_format={"type":
# "json_schema", ...} on the OpenAI-compatible path (#910-follow-up):
# constrains decoding to this exact shape regardless of how well a given
# model otherwise follows written instructions. additionalProperties: false
# at every object level so a model can't pad the reply with invented keys.
_PARTS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "part_type": {"type": ["string", "null"]},
                    "part_name": {"type": ["string", "null"]},
                    "sup_base_filename": {"type": ["string", "null"]},
                },
                "required": ["id", "part_type", "part_name", "sup_base_filename"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["files"],
    "additionalProperties": False,
}

# Unit-based strategy (#878): groups files by the in-game unit/character they
# belong to (e.g. every file for "Royal Guard 1" — head, helmet, weapon —
# shares that name) instead of by physical part type. Deliberately NOT
# constrained to CANONICAL_PART_TYPES — a unit name is derived per-model, so
# there's no fixed list to snap to; _to_pascal_case below is the only
# normalization applied, to keep casing consistent across a unit's files.
#
# Response is grouped by unit rather than one flat object per file (#894-
# follow-up): a unit's name is often several words (e.g. "Ogre Champion With
# Great Weapon") and previously got repeated verbatim on every one of that
# unit's files. Stating it once per group instead is a direct, unbounded-
# with-unit-size win on completion length — the main lever for latency on a
# slow/local model, and less for it to generate correctly before a
# repetition/formatting slip corrupts the JSON. sup_base_filename was also
# dropped: Sup_ files are excluded from every candidate batch (both
# strategies), so the field could only ever come back null — pure dead
# weight in both the prompt and every response object.
_UNIT_SYSTEM_PROMPT = ("""You are an assistant that groups 3D-printing STL files for a miniature figure library by the in-game unit or character they belong to, not by physical part type.

Given a JSON list of STL files (each {"id": <int>, "filename": <str>}), group them by which in-game unit/character they belong to — e.g. every file for "Royal Guard 1" (its head, helmet, weapon, etc.) belongs in one group — and give each file a short physical-part label.

Rules:
1. Group name: a short unit/character name derived from the filenames (e.g. "Royal Guard 1", "Ogre Champion"). Use the exact same name (consistent spelling and number) for every file belonging to that unit.
2. part_name: a short human-readable label for what this specific file physically is (e.g. "Head Female", "Right Arm"). Strip underscores, extensions, and redundant tokens.
3. Put any file whose unit is truly unknowable in "unknown" instead of guessing.
4. Return ONLY the JSON object below — no markdown, no explanation, no extra keys.

Format: {"units": [{"name": <str>, "members": [{"id": <int>, "part_name": <str|null>}, ...]}, ...], "unknown": [<int>, ...]}"""
    + _NO_REASONING_SUFFIX)

# Mirrors _UNIT_SYSTEM_PROMPT's format — see _PARTS_JSON_SCHEMA above.
_UNIT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "members": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "part_name": {"type": ["string", "null"]},
                            },
                            "required": ["id", "part_name"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "members"],
                "additionalProperties": False,
            },
        },
        "unknown": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["units", "unknown"],
    "additionalProperties": False,
}


def _to_pascal_case(s: str) -> str:
    """Title-case each whitespace/underscore/hyphen-separated word.

    Unit-based part_type suggestions are freeform (never snapped to a fixed
    list), so nothing else guarantees consistent casing across a unit's files
    — the LLM could return "Royal Guard 1" for one file and "royal guard 1"
    for another. This is applied to every unit-strategy suggestion so the
    same unit always renders identically."""
    words = [w for w in re.split(r"[\s_\-]+", s.strip()) if w]
    return " ".join(w.capitalize() for w in words)


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _prefix_unit_name(unit: str, part_name: str) -> str:
    """Compose a unit-strategy file's final part_name as "<unit> <part>".

    The prompt deliberately asks for a bare physical-part label per file
    (e.g. "Base", "Right Arm") rather than repeating the unit name on every
    one — that was the whole point of the grouped response format (#894-
    follow-up): shorter completions, one name stated once per group. But
    part_name is the label actually shown for a file wherever part_type
    (the unit name here, not a category) isn't also displayed alongside it —
    "Base" on its own is ambiguous the moment a model has more than one unit
    with a base. Prefixing here, once, at the point suggestions are finalized
    keeps the prompt's token savings while making the applied name
    unambiguous on its own (#941).

    A single-file "unit" (e.g. "Escaraba_Flamer.stl") commonly gets a
    part_name that's just the unit name's own distinguishing word
    ("Flamer") — naively concatenating produced "Escaraba Flamer Flamer"
    (#942-follow-up). So before concatenating, check for redundancy on
    normalized (lowercased, punctuation/whitespace-stripped) text:
      - part_name already contains the unit name (and possibly more), e.g.
        unit "Royal Guard 1" + part_name "Royal Guard 1 Head" -> kept as-is,
        it's already the full compound name.
      - the unit name already says everything part_name does, e.g. unit
        "Escaraba Flamer" + part_name "Flamer" -> just the unit name.
      - otherwise, concatenated as before.

    This is a plain substring check on normalized text (so e.g. unit
    "Escaraba Leftarm 1" + part_name "Left Arm" is caught as redundant —
    "leftarm" is a substring of "escarabaleftarm1" either way spacing goes),
    not a word-aware one — a part_name using different word order or a
    synonym for the same physical thing the unit name already implies won't
    be recognized as redundant, and the model's own inconsistent
    spelling/spacing for the unit name itself (e.g. "Leftarm" instead of
    "Left Arm") isn't corrected here either; that's a naming-quality nuance
    of the LLM's own unit grouping, not something this finalization step
    can fix after the fact.
    """
    if not part_name:
        return part_name
    unit_norm = _NON_ALNUM_RE.sub("", unit.lower())
    part_norm = _NON_ALNUM_RE.sub("", part_name.lower())
    if unit_norm and unit_norm in part_norm:
        return part_name
    if part_norm and part_norm in unit_norm:
        return unit
    return f"{unit} {part_name}"


def _strip_json_fence(raw_text: str) -> str:
    """Strip an optional ```json ... ``` fence some models wrap replies in."""
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```", 2)[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.rsplit("```", 1)[0].strip()
    return raw_text


_RAW_RESPONSE_LOG_CAP = 1500  # chars — enough to see the failure shape without flooding logs

_TRAILING_COMMA_RE = re.compile(r",(\s*[\]}])")


def _repair_json(raw_text: str) -> str:
    """Best-effort fix-ups for the common ways an LLM's JSON is *almost*
    valid (#928-follow-up): a trailing comma before a closing bracket, or
    stray prose wrapped around the object despite being told to return only
    JSON. Deliberately narrow — not a general JSON repair tool — since a more
    aggressive fixer risks silently producing plausible-looking but wrong
    data instead of surfacing the failure. Truncated JSON (cut off by
    max_tokens) is out of scope here; that's already caught upstream by the
    empty-content/finish_reason check, not this path."""
    text = raw_text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _load_llm_json(raw_text: str, source: str) -> tuple[Any, LlmOutcome | None]:
    """Strip an optional fence and parse JSON — shared by both response
    parsers. Returns ``(data, None)`` on success or ``(None, error_outcome)``
    on failure.

    A first parse failure gets one retry against a best-effort repaired
    version (see _repair_json) before giving up — cheap insurance against an
    otherwise-good reply with one stray syntax slip (#928-follow-up).

    On failure, the offending text is logged at WARNING (not DEBUG) —
    "non-JSON content" alone doesn't say whether the model rambled prose,
    got stuck repeating itself, or was simply cut off mid-object by
    max_tokens; seeing the actual reply is the only way to tell which."""
    raw_text = _strip_json_fence(raw_text)
    try:
        return json.loads(raw_text), None
    except json.JSONDecodeError:
        pass

    repaired = _repair_json(raw_text)
    if repaired != raw_text:
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            pass
        else:
            _log.info(
                "ai_organize llm_repaired recovered malformed-but-close JSON from %s", source,
            )
            return data, None

    detail = f"LLM returned non-JSON content from {source}"
    _log.warning(
        "ai_organize llm_error %s — raw reply (%d chars, showing up to %d): %r",
        detail, len(raw_text), _RAW_RESPONSE_LOG_CAP, raw_text[:_RAW_RESPONSE_LOG_CAP],
    )
    return None, LlmOutcome(status="error", detail=detail)


def _flat_suggestions_from_data(data: Any, source: str) -> LlmOutcome:
    """Extract the "parts"-strategy flat ``{"files": [...]}`` shape."""
    suggestions = data.get("files", []) if isinstance(data, dict) else []
    if not isinstance(suggestions, list):
        _log.warning(
            "ai_organize llm_error malformed 'files' field from %s — parsed JSON was: %s",
            source, repr(data)[:_RAW_RESPONSE_LOG_CAP],
        )
        return LlmOutcome(status="error",
                          detail=f"Malformed 'files' field in response from {source}")

    _log_step("llm_done", suggestions=len(suggestions))
    return LlmOutcome(status="ok", suggestions=suggestions)


def _parse_suggestions(raw_text: str, source: str) -> LlmOutcome:
    """Parse a model's raw text reply into an :class:`LlmOutcome`.

    Shared by the OpenAI and Anthropic paths: strips an optional ```json fence,
    parses the JSON object, and extracts its ``files`` list. ``source`` is a
    human-readable label (endpoint URL or "Anthropic API") used in log/error text.
    """
    # Full model output — only emitted when LOG_LEVEL=DEBUG, so the INFO trace
    # stays terse while the raw suggestions are available on demand.
    _log.debug("ai_organize llm_raw_response %s", raw_text[:2000])
    data, err = _load_llm_json(raw_text, source)
    if err:
        return err
    return _flat_suggestions_from_data(data, source)


def _parse_unit_suggestions(raw_text: str, source: str) -> LlmOutcome:
    """Parse the unit strategy's grouped ``{"units": [...], "unknown": [...]}``
    reply (see _UNIT_SYSTEM_PROMPT), flattening it into the same per-file
    suggestion shape _parse_suggestions returns — id/part_type/part_name/
    sup_base_filename — so the batching and merge logic downstream don't need
    to know the wire format differs. ``part_type`` carries the unit/group
    name; ``sup_base_filename`` is always None (see _UNIT_SYSTEM_PROMPT's
    comment for why it was dropped from the prompt).

    Falls back to the older flat ``{"files": [...]}`` shape if a model
    ignores the grouped format and replies in that one anyway — cheap
    insurance against a model that's simply more reliable with the shape it's
    seen more of in training.
    """
    _log.debug("ai_organize llm_raw_response %s", raw_text[:2000])
    data, err = _load_llm_json(raw_text, source)
    if err:
        return err

    if not isinstance(data, dict):
        _log.warning(
            "ai_organize llm_error malformed response from %s — parsed JSON was: %s",
            source, repr(data)[:_RAW_RESPONSE_LOG_CAP],
        )
        return LlmOutcome(status="error", detail=f"Malformed response from {source}")

    if "units" not in data and "files" in data:
        return _flat_suggestions_from_data(data, source)

    suggestions: list[dict[str, Any]] = []
    units = data.get("units", [])
    if isinstance(units, list):
        for group in units:
            if not isinstance(group, dict):
                continue
            name = group.get("name")
            members = group.get("members", [])
            if not isinstance(members, list):
                continue
            for m in members:
                if not isinstance(m, dict) or not isinstance(m.get("id"), int):
                    continue
                suggestions.append({
                    "id": m["id"],
                    "part_type": name,
                    "part_name": m.get("part_name"),
                    "sup_base_filename": None,
                })

    unknown = data.get("unknown", [])
    if isinstance(unknown, list):
        for fid in unknown:
            if isinstance(fid, int):
                suggestions.append({
                    "id": fid, "part_type": None, "part_name": None, "sup_base_filename": None,
                })

    _log_step("llm_done", suggestions=len(suggestions))
    return LlmOutcome(status="ok", suggestions=suggestions)


def _text_from_anthropic(resp: Any) -> str:
    """Concatenate the text blocks of an Anthropic messages response (skips any
    extended-thinking blocks)."""
    parts = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts).strip()


def _llm_refine_anthropic(
    files: list[dict[str, Any]],
    model: str,
    api_key: str,
    timeout: float = _DEFAULT_TIMEOUT,
    effort: str | None = None,
    system_prompt: str = _SYSTEM_PROMPT,
    user_prefix: str = "",
    parser: Callable[[str, str], LlmOutcome] = _parse_suggestions,
) -> LlmOutcome:
    """Refine via the Anthropic Messages API. Mirrors the OpenAI path's contract:
    returns ``status="error"`` with a human-readable ``detail`` on any failure.

    ``user_prefix``, when given, is prepended (as plain text, before the JSON
    file list) to the user turn — used by the unit strategy's batching to tell
    a later batch which unit names earlier batches already established, so
    the same unit doesn't get renamed across batches. ``parser`` picks the
    response shape to expect — the unit strategy's is grouped, not flat (see
    _parse_unit_suggestions)."""
    source = "Anthropic API"
    if not api_key:
        detail = "No API key configured for this Anthropic connection."
        _log.warning("ai_organize llm_error %s", detail)
        return LlmOutcome(status="error", detail=detail)

    _log_step("llm_request", endpoint=source, model=model,
              file_count=len(files), timeout_s=timeout)
    t0 = time.monotonic()
    try:
        client = Anthropic(api_key=api_key, timeout=timeout)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prefix + json.dumps(files, ensure_ascii=False)},
            ],
        }
        budget = _EFFORT_THINKING_BUDGET.get((effort or "low"), 0)
        if budget:
            # max_tokens must exceed the thinking budget.
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kwargs["max_tokens"] = _ANTHROPIC_MAX_TOKENS + budget
        resp = client.messages.create(**kwargs)
    except Exception as exc:  # anthropic.APIError, auth, timeout, etc.
        detail = f"{exc.__class__.__name__}: {exc}".strip().rstrip(":")
        _log.warning("ai_organize llm_error source=%s reason=%s", source, detail)
        return LlmOutcome(status="error", detail=detail)

    _log_step("llm_response", elapsed_s=round(time.monotonic() - t0, 1), status="ok")
    raw_text = _text_from_anthropic(resp)
    if not raw_text:
        # Mirrors the OpenAI path's empty-content diagnostic: stop_reason
        # ("max_tokens" confirms it ran out of budget) plus the content block
        # types actually returned (e.g. all "thinking", no "text") say why,
        # even though max_tokens here already reserves headroom on top of the
        # thinking budget specifically to avoid this (see kwargs above).
        stop_reason = getattr(resp, "stop_reason", None)
        block_types = [getattr(b, "type", None) for b in (getattr(resp, "content", []) or [])]
        detail = f"Empty response from {source} (stop_reason={stop_reason!r})"
        _log.warning("ai_organize llm_error %s — content block types: %s", detail, block_types)
        return LlmOutcome(status="error", detail=detail)
    return parser(raw_text, source)


def _llm_refine_openai(
    files: list[dict[str, Any]],
    base_url: str,
    model: str,
    api_key: str,
    timeout: float = _DEFAULT_TIMEOUT,
    system_prompt: str = _SYSTEM_PROMPT,
    user_prefix: str = "",
    parser: Callable[[str, str], LlmOutcome] = _parse_suggestions,
    response_schema: dict[str, Any] | None = None,
    disable_reasoning: bool = True,
) -> LlmOutcome:
    """Call an OpenAI-compatible /v1/chat/completions endpoint (e.g. Ollama).

    On any failure the outcome carries ``status="error"`` and a human-readable
    ``detail``, and the caller falls back to the heuristic results. Errors are
    logged at WARNING (not INFO) with the endpoint and the underlying reason so
    connection refusals, timeouts, and HTTP errors are distinguishable in logs.

    ``user_prefix``: see _llm_refine_anthropic — same purpose here. ``parser``:
    see _llm_refine_anthropic — same purpose here.

    ``response_schema`` (#910-follow-up): when given, requests schema-
    constrained decoding (``response_format={"type": "json_schema", ...}``)
    instead of the looser ``"json_object"`` mode — forces the model's output
    into this exact shape via constrained decoding rather than hoping it
    follows the prompt's written format instructions, which a model can
    drift away from (e.g. inventing its own key names) even while still
    producing well-formed JSON. Falls back to ``"json_object"`` when omitted.

    ``disable_reasoning`` (#939-follow-up, default True): sends "think": false
    and "reasoning_effort": "none" to suppress a thinking-capable model's
    hidden reasoning phase, since there's nothing to reason about for this
    task. Configurable per AiApiConfig (opt-in reasoning) because forcing it
    off is a call-time choice, not a hardcoded one — some deployments may
    want the model's own judgment on ambiguous names badly enough to accept
    the added latency and max_tokens risk that comes with it.
    """
    import re as _re
    base_url = _re.sub(
        r"(?i)(https?://)(?:localhost|127\.0\.0\.1)\b",
        r"\1host.docker.internal",
        base_url.rstrip("/"),
    )

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response_format: dict[str, Any] = (
        {"type": "json_schema", "json_schema": {"name": "ai_organize_response", "schema": response_schema, "strict": True}}
        if response_schema is not None
        else {"type": "json_object"}
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prefix + json.dumps(files, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "response_format": response_format,
        "max_tokens": _OPENAI_MAX_TOKENS,
    }
    if disable_reasoning:
        # Some locally-served models (DeepSeek-R1-style, QwQ, Gemma reasoning
        # variants, etc.) support an extended "thinking"/reasoning phase
        # before the real answer. There's nothing to reason about for this
        # task — it's filename pattern-matching — and a thinking model can
        # spend its *entire* max_tokens budget on hidden reasoning and emit
        # nothing into content at all (#903-follow-up: exactly this — 78s,
        # status 200, empty content).
        #
        # "think" is the native Ollama /api/chat field — it is NOT read by
        # Ollama's OpenAI-compatible /v1/chat/completions endpoint at all
        # (ollama/ollama#15288), so kept here only in case some other
        # OpenAI-compatible server (llama.cpp, etc.) honors it. The field
        # this endpoint actually reads is "reasoning_effort" (ollama/ollama
        # #14820); "none" is the documented value to disable thinking.
        # Ignored by servers/models that don't recognize either field.
        payload["think"] = False
        payload["reasoning_effort"] = "none"

    endpoint = f"{base_url}/v1/chat/completions"
    # Credential-safe form for logs and surfaced error messages.
    log_endpoint = _redact_url(endpoint)
    _log_step("llm_request", endpoint=log_endpoint, model=model,
              file_count=len(files), timeout_s=timeout)
    t0 = time.monotonic()

    def _request_error(exc: httpx.RequestError) -> LlmOutcome:
        # str(exc) includes the target host/port and the OS-level reason
        # (e.g. "Connection refused", "timed out"), which the class name alone
        # discarded. A timeout is by far the most common remote-Ollama failure,
        # so name it explicitly. Redact the exception text too: httpx errors
        # echo the request URL, which may carry userinfo credentials.
        detail = _redact_url(f"{exc.__class__.__name__}: {exc}".strip().rstrip(":"))
        if isinstance(exc, httpx.TimeoutException):
            detail = (
                f"Timed out after {timeout:g}s calling {log_endpoint} — the model may "
                f"be cold-starting; raise this API's timeout in Settings."
            )
        _log.warning("ai_organize llm_error endpoint=%r reason=%s", log_endpoint, detail)
        return LlmOutcome(status="error", detail=detail)

    try:
        resp = httpx.post(endpoint, json=payload, headers=headers, timeout=timeout)
    except httpx.RequestError as exc:
        return _request_error(exc)

    # Retry once per optional field a strict server rejects outright (rather
    # than just ignoring) — checked in sequence so a server that objects to
    # both fields sheds each in turn instead of only ever trying the first.
    for optional_key in ("response_format", "think", "reasoning_effort"):
        if resp.status_code == 400 and optional_key in payload and optional_key in resp.text:
            payload.pop(optional_key, None)
            try:
                resp = httpx.post(endpoint, json=payload, headers=headers, timeout=timeout)
            except httpx.RequestError as exc:
                return _request_error(exc)

    elapsed = time.monotonic() - t0
    _log_step("llm_response", elapsed_s=round(elapsed, 1), status=resp.status_code)

    if not resp.is_success:
        body_snippet = resp.text[:300].replace("\n", " ")
        detail = f"HTTP {resp.status_code} from {log_endpoint}: {body_snippet}"
        _log.warning("ai_organize llm_error %s", detail)
        return LlmOutcome(status="error", detail=detail)

    try:
        body    = resp.json()
        choice  = body["choices"][0]
        message = choice.get("message", {})
        raw_text: str = (message.get("content") or "").strip()
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        detail = f"Unexpected response shape from {log_endpoint}: {exc.__class__.__name__}"
        _log.warning("ai_organize llm_error %s", detail)
        return LlmOutcome(status="error", detail=detail)

    if not raw_text:
        # A model with a hidden "thinking"/reasoning phase can spend its
        # entire max_tokens budget reasoning and never emit anything into
        # content — the request still succeeds (status 200) with nothing to
        # show for it. finish_reason == "length" confirms it ran out of
        # budget rather than the model choosing to stop; the full message
        # object surfaces a reasoning/thinking field the server may have put
        # the content in instead, if there is one.
        finish_reason = choice.get("finish_reason")
        detail = f"Empty response content from {log_endpoint} (finish_reason={finish_reason!r})"
        _log.warning(
            "ai_organize llm_error %s — full message: %s",
            detail, repr(message)[:_RAW_RESPONSE_LOG_CAP],
        )
        return LlmOutcome(status="error", detail=detail)

    return parser(raw_text, log_endpoint)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_LLM_FILE_CAP = 15   # max files sent to LLM per request

# Unit strategy gets a smaller per-call cap than parts (#910-follow-up): it
# has no heuristic fallback and, unlike parts' single flat request, its
# per-unit grouping reasoning (when a model reasons at all) scales with how
# many distinct units are in play in one call — a verbose local model that
# can just about finish a handful of files in one go runs out of budget well
# before _LLM_FILE_CAP on a real multi-unit kit. More, smaller calls trade
# latency for actually finishing instead of hard-failing on a large batch.
_UNIT_LLM_FILE_CAP = 5


def _run_unit_batches(
    candidates: list[dict[str, Any]],
    call_llm: Callable[[list[dict[str, Any]], str, str], LlmOutcome],
    batch_size: int = _UNIT_LLM_FILE_CAP,
) -> LlmOutcome:
    """Send every unit-strategy candidate to the LLM in chunks of
    ``batch_size`` (defaults to _UNIT_LLM_FILE_CAP), one call per chunk,
    instead of a single capped call that silently drops everything past the
    first cap's worth of files (#884) — the unit strategy has no heuristic
    fallback to catch what a single call misses, unlike "parts".

    Each chunk after the first is told which unit names earlier chunks
    already established, so the same physical unit doesn't get renamed
    differently across chunks. Success-via-API-or-nothing (#821) still holds
    across the whole run: the first chunk that errors makes the entire
    result "error", exactly as a single non-batched call would — never a mix
    of some real suggestions and some silently missing.
    """
    all_suggestions: list[dict[str, Any]] = []
    known_units: list[str] = []  # insertion order, for a stable/readable hint
    total = len(candidates)

    for start in range(0, total, batch_size):
        chunk = candidates[start:start + batch_size]
        prefix = ""
        if known_units:
            prefix = (
                "Units already established from earlier files in this same "
                "model (reuse one of these exactly — same spelling and "
                "number — if a file below belongs to it): "
                + ", ".join(known_units) + "\n\n"
            )
        _log_step(
            "llm_batch", sending=len(chunk), of=total,
            batch=start // batch_size + 1,
        )
        outcome = call_llm(chunk, _UNIT_SYSTEM_PROMPT, prefix)
        if outcome.status != "ok":
            return outcome
        for s in outcome.suggestions:
            pt = s.get("part_type")
            if pt:
                cased = _to_pascal_case(pt)
                s["part_type"] = cased
                if cased not in known_units:
                    known_units.append(cased)
        all_suggestions.extend(outcome.suggestions)

    return LlmOutcome(status="ok", suggestions=all_suggestions)


def run(
    files: list[dict[str, Any]],
    base_url: str,
    model: str,
    api_key: str = "",
    timeout: float = _DEFAULT_TIMEOUT,
    api_type: str = "openai",
    effort: str | None = None,
    strategy: str = "parts",
    batch_size: int | None = None,
    reasoning_enabled: bool = False,
) -> OrganizeResult:
    """Return merged suggestions plus the outcome of the optional LLM pass.

    ``strategy="parts"`` (default): heuristics run first and are always
    returned immediately. The LLM then always runs too (capped at
    _LLM_FILE_CAP files, so the response time stays reasonable even for
    models with hundreds of files) — it is never skipped just because
    heuristics filled in every part_type; the AI still gets a chance to
    correct a wrong heuristic guess or fix a part_name, which "already
    resolved" coverage of part_type alone can't tell you. Each candidate file
    is sent with its current best-known part_type/part_name (the heuristic
    suggestion when there is one, else what was already stored), matching
    what the system prompt tells the model it's receiving.

    ``strategy="unit"`` (#878): groups files by the in-game unit/character
    they belong to instead of by physical part — e.g. every file for "Royal
    Guard 1" gets that as its part_type, not "Head"/"Weapon"/etc. There is no
    keyword heuristic for this (a unit name isn't derivable from the same
    part-type keyword map), so this strategy skips Stage 1 entirely and goes
    straight to the LLM with the unit-grouping prompt. Its part_type
    suggestions are freeform (no canonical list to snap to), so each one is
    Pascal-cased for consistency across a unit's files before being returned.

    Both strategies: Sup_ files are excluded from the LLM batch — they
    inherit their base file's type and would just duplicate that file's
    request. Remaining candidates are further deduped by cleaned filename
    (e.g. "Head_28mm.stl" / "Head_75mm.stl" — the same part at different
    scales both clean to "Head") — only one representative per group is sent,
    and its suggestion is copied to every sibling. The returned
    :class:`OrganizeResult` reports whether the LLM ran, was skipped (no
    non-Sup files to send), was disabled, or errored so the caller can
    surface that to the user instead of silently degrading.

    ``api_type`` selects the transport: "openai" (an OpenAI-compatible endpoint
    at ``base_url``, e.g. Ollama) or "anthropic" (the Anthropic Messages API,
    which needs no URL but requires ``api_key``; ``effort`` maps to a thinking
    budget).

    ``batch_size``, when given, overrides the per-request file cap for
    whichever strategy runs (_LLM_FILE_CAP for "parts", _UNIT_LLM_FILE_CAP for
    "unit") — configurable per AiApiConfig so a fast/reliable endpoint can send
    more files per call and a slow/flaky one can send fewer. ``None`` keeps
    the built-in defaults.

    ``reasoning_enabled`` (OpenAI-compatible path only, #939-follow-up):
    defaults to False, which actively suppresses a thinking-capable model's
    hidden reasoning phase (see _llm_refine_openai's ``disable_reasoning``).
    Set True to let the model reason before answering — off by default
    because reasoning adds latency and risks the exact empty-content failure
    the suppression exists to avoid, for a task (filename pattern-matching)
    that gains little from it.

    ``strategy="link_sups"`` (#967): matches a currently-unlinked
    sup/supported/hollowed-named file to its likely base part by name — see
    heuristic_link_sups. Pure heuristic, no LLM call and no API config
    needed at all; this returns immediately, before ``base_url``/``model``
    are even inspected.
    """
    if strategy == "link_sups":
        suggestions = heuristic_link_sups(files)
        _log_step("start", file_count=len(files), has_llm=False, api_type=api_type, strategy=strategy)
        return OrganizeResult(suggestions=suggestions, llm=LlmOutcome(status="ok", suggestions=suggestions))

    # An Anthropic config carries no URL; an OpenAI-compatible one needs one.
    llm_ready = bool(model) if api_type == "anthropic" else bool(base_url and model)
    _log_step("start", file_count=len(files), has_llm=llm_ready, api_type=api_type, strategy=strategy)
    outcome = LlmOutcome(status="disabled")
    merged: dict[int, dict[str, Any]] = {}

    if strategy == "parts":
        # Stage 1: fast Python heuristics
        heuristic = heuristic_pass(files)
        merged = {s["id"]: s for s in heuristic}

        # For Sup_ files whose base file's type WAS inferred, inherit it.
        all_filenames = [f["filename"] for f in files]
        type_by_filename: dict[str, str | None] = {}
        for f in files:
            sug = merged.get(f["id"])
            type_by_filename[f["filename"]] = sug.get("part_type") if sug else f.get("part_type")

        for f in files:
            sug = merged.get(f["id"])
            if sug and sug.get("part_type") is None and _is_sup(f["filename"]):
                base = sug.get("sup_base_filename") or _find_base(f["filename"], all_filenames)
                if base and type_by_filename.get(base):
                    sug["part_type"] = type_by_filename[base]

    # Stage 2: LLM refinement — always runs when configured (never skipped
    # based on how much Stage 1 already resolved; unit strategy has no Stage
    # 1 at all, so this is the only stage).
    if llm_ready:
        def _with_heuristic(f: dict[str, Any]) -> dict[str, Any]:
            sug = merged.get(f["id"]) or {}
            out = dict(f)
            if sug.get("part_type") is not None:
                out["part_type"] = sug["part_type"]
            if sug.get("part_name"):
                out["part_name"] = sug["part_name"]
            return out

        # Unit strategy has no heuristic stage (merged is always empty), and
        # its prompt only asks the model to group by filename — the stored
        # part_type/part_name it would otherwise inherit are stale leftovers
        # from a different classification scheme, not useful context. Sending
        # just id/filename shrinks the prompt for no loss of signal.
        def _candidate(f: dict[str, Any]) -> dict[str, Any]:
            if strategy == "unit":
                return {"id": f["id"], "filename": f["filename"]}
            return _with_heuristic(f)

        all_candidates = [
            _candidate(f) for f in files
            if not _is_sup(f["filename"])   # Sup_ files inherit; don't duplicate
        ]

        # Dedupe scale/version variants of the same physical part (e.g.
        # "Head_28mm.stl" and "Head_75mm.stl" both clean to "Head") before
        # hitting the LLM (#861-follow-up). They'd get an identical answer
        # anyway, since part_type/part_name are derived from the cleaned name
        # either way — so only the first file per cleaned name is sent, and
        # its suggestion is copied to every sibling afterward. This shrinks
        # both the prompt and (more importantly) the completion — fewer JSON
        # objects to generate is the main lever for latency on a slow/remote
        # model, and it also means more *distinct* parts fit under
        # _LLM_FILE_CAP instead of the cap being spent on duplicates.
        groups: dict[str, list[dict[str, Any]]] = {}
        for f in all_candidates:
            groups.setdefault(clean_name(f["filename"]), []).append(f)
        representatives = [members[0] for members in groups.values()]
        if len(representatives) < len(all_candidates):
            _log_step("llm_dedupe", candidates=len(all_candidates), unique=len(representatives))

        parser = _parse_unit_suggestions if strategy == "unit" else _parse_suggestions
        # Anthropic has no equivalent to OpenAI-style schema-constrained
        # decoding in this API shape, so response_schema is OpenAI-path only.
        response_schema = _UNIT_JSON_SCHEMA if strategy == "unit" else _PARTS_JSON_SCHEMA

        def _call_llm(chunk: list[dict[str, Any]], system_prompt: str, user_prefix: str = "") -> LlmOutcome:
            if api_type == "anthropic":
                return _llm_refine_anthropic(
                    chunk, model, api_key, timeout, effort,
                    system_prompt=system_prompt, user_prefix=user_prefix, parser=parser,
                )
            return _llm_refine_openai(
                chunk, base_url, model, api_key, timeout=timeout,
                system_prompt=system_prompt, user_prefix=user_prefix, parser=parser,
                response_schema=response_schema, disable_reasoning=not reasoning_enabled,
            )

        if not representatives:
            outcome = LlmOutcome(status="skipped")
            _log_step("llm_skip", reason="no non-Sup files to send")
        elif strategy == "unit":
            # Batched (#884): a single _LLM_FILE_CAP-sized call would silently
            # drop every file past the cap, since unit strategy has no
            # heuristic fallback to catch the rest (unlike "parts" below).
            outcome = _run_unit_batches(
                representatives, _call_llm,
                batch_size=batch_size or _UNIT_LLM_FILE_CAP,
            )
        else:
            candidates = representatives[:(batch_size or _LLM_FILE_CAP)]
            _log_step("llm_batch", sending=len(candidates), of=len(files))
            outcome = _call_llm(candidates, _SYSTEM_PROMPT)

        # Fan each representative's suggestion back out to every sibling that
        # shared its cleaned name (a group of 1 is a no-op here).
        expanded: list[dict[str, Any]] = []
        rep_id_to_key = {members[0]["id"]: key for key, members in groups.items()}
        for s in outcome.suggestions:
            expanded.append(s)
            key = rep_id_to_key.get(s.get("id"))
            if key is None:
                continue
            for sibling in groups[key][1:]:
                expanded.append({**s, "id": sibling["id"]})
        outcome.suggestions = expanded

        for s in outcome.suggestions:
            fid = s.get("id")
            if not isinstance(fid, int):
                continue
            existing = merged.get(fid, {"id": fid, "filename": "", "sup_base_filename": None})
            if s.get("part_type") is not None:
                existing["part_type"] = (
                    _to_pascal_case(s["part_type"]) if strategy == "unit" else s["part_type"]
                )
            if s.get("part_name"):
                part_name = s["part_name"]
                if strategy == "unit" and existing.get("part_type"):
                    part_name = _prefix_unit_name(existing["part_type"], part_name)
                existing["part_name"] = part_name
            if s.get("sup_base_filename"):
                existing["sup_base_filename"] = s["sup_base_filename"]
            merged[fid] = existing

    # Guarantee every file leaves organize with a real part_name, never just
    # the filename-derived placeholder the STL files table shows (dimmed) for
    # an empty one (#947). A file can reach here still nameless for several
    # reasons — heuristics/LLM judged no change needed while a name was
    # already missing, the LLM omitted the file from its response entirely,
    # or it landed in "unknown" — this closes all of them in one place rather
    # than chasing each upstream cause individually. Only fills a genuinely
    # empty name; anything already set (by heuristics, the LLM, or a prior
    # save) is left untouched.
    #
    # Skipped entirely on "error": success-via-API-or-nothing (#821) requires
    # an errored run to return zero suggestions, never a partial mix — this
    # loop must not manufacture suggestions out of an otherwise-empty result.
    if outcome.status != "error":
        for f in files:
            fid = f["id"]
            current_name = (merged.get(fid) or {}).get("part_name") or f.get("part_name")
            if current_name:
                continue
            auto_name = clean_name(f["filename"])
            if not auto_name:
                continue
            if fid not in merged:
                merged[fid] = {"id": fid, "sup_base_filename": None}
            merged[fid]["part_name"] = auto_name

    result = list(merged.values())
    _log_step("done", total_suggestions=len(result), llm_status=outcome.status)
    return OrganizeResult(suggestions=result, llm=outcome)

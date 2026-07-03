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
from typing import Any

import httpx

_log = logging.getLogger(__name__)


def _log_step(step: str, **kw: Any) -> None:
    parts = " ".join(f"{k}={v!r}" for k, v in kw.items())
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


def _clean_name(filename: str) -> str:
    """Turn a raw filename into a readable label.

    Works on the original filename (before lowercasing) so CamelCase can be
    detected. Extension and Sup_ prefix/infix are stripped, then "Supported"
    is prepended to the final name if the file was a supported variant.
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
        new_name       = _clean_name(filename) or cur_name
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
# LLM refinement (optional)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an assistant that normalizes 3D-printing STL file names for a miniature figure library.

Given a JSON list of STL files with heuristically-suggested part_type and part_name, refine only what is wrong or missing.

Rules:
1. part_type: one short category — Body, Head, Arm, Leg, Hand, Foot, Weapon, Shield, Armor, Base, Full, Accessory, Torso, Shoulder. Null if truly unknowable.
2. part_name: a short human-readable label (e.g. "Right Arm", "Helmeted Head"). Strip underscores, extensions, and redundant tokens.
3. sup_base_filename: if this file is a presupported variant, return the EXACT filename of its base counterpart in the list. Otherwise null.
4. Omit files where the existing heuristic suggestions are already correct.
5. Return ONLY the JSON object — no markdown, no explanation.

Format: {"files": [{"id": <int>, "part_type": <str|null>, "part_name": <str|null>, "sup_base_filename": <str|null>}, ...]}"""


def _llm_refine(
    files: list[dict[str, Any]],
    base_url: str,
    model: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Call the LLM and return a merged suggestion list.

    On any error, logs and returns an empty list so the caller falls back to
    the heuristic results.
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

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(files, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    endpoint = f"{base_url}/v1/chat/completions"
    _log_step("llm_request", endpoint=endpoint, model=model, file_count=len(files))
    t0 = time.monotonic()

    try:
        resp = httpx.post(endpoint, json=payload, headers=headers, timeout=10)
    except httpx.RequestError as exc:
        _log_step("llm_error", reason=exc.__class__.__name__)
        return []

    if resp.status_code == 400 and "response_format" in resp.text:
        payload.pop("response_format", None)
        try:
            resp = httpx.post(endpoint, json=payload, headers=headers, timeout=10)
        except httpx.RequestError as exc:
            _log_step("llm_error", reason=exc.__class__.__name__)
            return []

    elapsed = time.monotonic() - t0
    _log_step("llm_response", status=resp.status_code, elapsed_s=round(elapsed, 1))

    if not resp.is_success:
        _log_step("llm_error", reason=f"HTTP {resp.status_code}")
        return []

    try:
        body      = resp.json()
        raw_text: str = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as exc:
        _log_step("llm_error", reason=f"bad shape: {exc}")
        return []

    if raw_text.startswith("```"):
        raw_text = raw_text.split("```", 2)[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        _log.warning("ai_organize llm returned non-JSON: %s", raw_text[:200])
        return []

    suggestions = data.get("files", [])
    _log_step("llm_done", suggestions=len(suggestions) if isinstance(suggestions, list) else "bad")
    return suggestions if isinstance(suggestions, list) else []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_LLM_FILE_CAP = 15   # max files sent to LLM per request


def run(
    files: list[dict[str, Any]],
    base_url: str,
    model: str,
    api_key: str = "",
) -> list[dict[str, Any]]:
    """Return a merged list of suggestions for the given files.

    Heuristics run first and are always returned immediately. The LLM is
    only called for files where heuristics could NOT determine a part_type
    (capped at _LLM_FILE_CAP), so the response time stays reasonable even
    for models with hundreds of files.
    """
    _log_step("start", file_count=len(files), has_llm=bool(base_url and model))

    # Stage 1: fast Python heuristics
    heuristic = heuristic_pass(files)
    merged: dict[int, dict[str, Any]] = {s["id"]: s for s in heuristic}

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

    # Stage 2: LLM refinement for genuinely ambiguous files only.
    if base_url and model:
        unresolved = [
            f for f in files
            if not (merged.get(f["id"]) or {}).get("part_type")
            and not _is_sup(f["filename"])   # Sup_ files inherit; don't duplicate
        ][:_LLM_FILE_CAP]

        if unresolved:
            _log_step("llm_batch", sending=len(unresolved), of=len(files))
            llm_results = _llm_refine(unresolved, base_url, model, api_key)
            for s in llm_results:
                fid = s.get("id")
                if not isinstance(fid, int):
                    continue
                existing = merged.get(fid, {"id": fid, "filename": "", "sup_base_filename": None})
                if s.get("part_type") is not None:
                    existing["part_type"] = s["part_type"]
                if s.get("part_name"):
                    existing["part_name"] = s["part_name"]
                if s.get("sup_base_filename"):
                    existing["sup_base_filename"] = s["sup_base_filename"]
                merged[fid] = existing
        else:
            _log_step("llm_skip", reason="no unresolved files after heuristics")

    result = list(merged.values())
    _log_step("done", total_suggestions=len(result))
    return result

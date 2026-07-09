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
from typing import Any

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

# The app's fixed category list (mirrors frontend/src/pages/model-detail/utils.ts
# PART_TYPE_SUGGESTIONS — the only categories the Category combobox offers).
# Keep the two in sync by hand; there's no shared build step across the
# Python/TypeScript boundary. The AI must pick from this exact list so its
# output lines up with what the UI (and _normalize_type below) expects,
# instead of inventing near-miss variants like "Accessory" vs "Accessories".
CANONICAL_PART_TYPES = [
    "Head", "Torso", "Body",
    "Right Arm", "Left Arm", "Arms",
    "Right Leg", "Left Leg", "Legs",
    "Hands", "Feet", "Base",
    "Weapon", "Shield", "Armor", "Cloak", "Cape",
    "Hair", "Wings", "Tail", "Accessories",
]

_SYSTEM_PROMPT = """You are an assistant that normalizes 3D-printing STL file names for a miniature figure library.

Given a JSON list of STL files with heuristically-suggested part_type and part_name, refine only what is wrong or missing.

Rules:
1. part_type: one category from this exact list — {part_types}. Null if truly unknowable. Never invent a category outside this list.
2. part_name: a short human-readable label (e.g. "Right Arm", "Helmeted Head"). Strip underscores, extensions, and redundant tokens.
3. sup_base_filename: if this file is a presupported variant, return the EXACT filename of its base counterpart in the list. Otherwise null.
4. Omit files where the existing heuristic suggestions are already correct.
5. Return ONLY the JSON object — no markdown, no explanation.

Format: {{"files": [{{"id": <int>, "part_type": <str|null>, "part_name": <str|null>, "sup_base_filename": <str|null>}}, ...]}}""".format(part_types=", ".join(CANONICAL_PART_TYPES))


def _parse_suggestions(raw_text: str, source: str) -> LlmOutcome:
    """Parse a model's raw text reply into an :class:`LlmOutcome`.

    Shared by the OpenAI and Anthropic paths: strips an optional ```json fence,
    parses the JSON object, and extracts its ``files`` list. ``source`` is a
    human-readable label (endpoint URL or "Anthropic API") used in log/error text.
    """
    # Full model output — only emitted when LOG_LEVEL=DEBUG, so the INFO trace
    # stays terse while the raw suggestions are available on demand.
    _log.debug("ai_organize llm_raw_response %s", raw_text[:2000])

    if raw_text.startswith("```"):
        raw_text = raw_text.split("```", 2)[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        detail = f"LLM returned non-JSON content from {source}"
        _log.warning("ai_organize llm_error %s", detail)
        return LlmOutcome(status="error", detail=detail)

    suggestions = data.get("files", []) if isinstance(data, dict) else []
    if not isinstance(suggestions, list):
        _log.warning("ai_organize llm_error malformed 'files' field from %s", source)
        return LlmOutcome(status="error",
                          detail=f"Malformed 'files' field in response from {source}")

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
) -> LlmOutcome:
    """Refine via the Anthropic Messages API. Mirrors the OpenAI path's contract:
    returns ``status="error"`` with a human-readable ``detail`` on any failure."""
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
            "system": _SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": json.dumps(files, ensure_ascii=False)},
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
        detail = f"Empty response from {source}"
        _log.warning("ai_organize llm_error %s", detail)
        return LlmOutcome(status="error", detail=detail)
    return _parse_suggestions(raw_text, source)


def _llm_refine_openai(
    files: list[dict[str, Any]],
    base_url: str,
    model: str,
    api_key: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> LlmOutcome:
    """Call an OpenAI-compatible /v1/chat/completions endpoint (e.g. Ollama).

    On any failure the outcome carries ``status="error"`` and a human-readable
    ``detail``, and the caller falls back to the heuristic results. Errors are
    logged at WARNING (not INFO) with the endpoint and the underlying reason so
    connection refusals, timeouts, and HTTP errors are distinguishable in logs.
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

    if resp.status_code == 400 and "response_format" in resp.text:
        payload.pop("response_format", None)
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
        body      = resp.json()
        raw_text: str = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        detail = f"Unexpected response shape from {log_endpoint}: {exc.__class__.__name__}"
        _log.warning("ai_organize llm_error %s", detail)
        return LlmOutcome(status="error", detail=detail)

    return _parse_suggestions(raw_text, log_endpoint)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_LLM_FILE_CAP = 15   # max files sent to LLM per request


def run(
    files: list[dict[str, Any]],
    base_url: str,
    model: str,
    api_key: str = "",
    timeout: float = _DEFAULT_TIMEOUT,
    api_type: str = "openai",
    effort: str | None = None,
) -> OrganizeResult:
    """Return merged suggestions plus the outcome of the optional LLM pass.

    Heuristics run first and are always returned immediately. The LLM then
    always runs too (capped at _LLM_FILE_CAP files, so the response time
    stays reasonable even for models with hundreds of files) — it is never
    skipped just because heuristics filled in every part_type; the AI still
    gets a chance to correct a wrong heuristic guess or fix a part_name,
    which "already resolved" coverage of part_type alone can't tell you.
    Each candidate file is sent with its current best-known part_type/
    part_name (the heuristic suggestion when there is one, else what was
    already stored), matching what the system prompt tells the model it's
    receiving. Sup_ files are excluded — they inherit their base file's type
    and would just duplicate that file's request. The returned
    :class:`OrganizeResult` reports whether the LLM ran, was skipped (no
    non-Sup files to send), was disabled, or errored so the caller can
    surface that to the user instead of silently degrading.

    ``api_type`` selects the transport: "openai" (an OpenAI-compatible endpoint
    at ``base_url``, e.g. Ollama) or "anthropic" (the Anthropic Messages API,
    which needs no URL but requires ``api_key``; ``effort`` maps to a thinking
    budget).
    """
    # An Anthropic config carries no URL; an OpenAI-compatible one needs one.
    llm_ready = bool(model) if api_type == "anthropic" else bool(base_url and model)
    _log_step("start", file_count=len(files), has_llm=llm_ready, api_type=api_type)
    outcome = LlmOutcome(status="disabled")

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

    # Stage 2: LLM refinement — always runs (never skipped based on how much
    # heuristics already resolved); it can confirm, correct, or fill in gaps.
    if llm_ready:
        def _with_heuristic(f: dict[str, Any]) -> dict[str, Any]:
            sug = merged.get(f["id"]) or {}
            out = dict(f)
            if sug.get("part_type") is not None:
                out["part_type"] = sug["part_type"]
            if sug.get("part_name"):
                out["part_name"] = sug["part_name"]
            return out

        candidates = [
            _with_heuristic(f) for f in files
            if not _is_sup(f["filename"])   # Sup_ files inherit; don't duplicate
        ][:_LLM_FILE_CAP]

        if candidates:
            _log_step("llm_batch", sending=len(candidates), of=len(files))
            if api_type == "anthropic":
                outcome = _llm_refine_anthropic(candidates, model, api_key, timeout, effort)
            else:
                outcome = _llm_refine_openai(candidates, base_url, model, api_key, timeout=timeout)
            for s in outcome.suggestions:
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
            outcome = LlmOutcome(status="skipped")
            _log_step("llm_skip", reason="no non-Sup files to send")

    result = list(merged.values())
    _log_step("done", total_suggestions=len(result), llm_status=outcome.status)
    return OrganizeResult(suggestions=result, llm=outcome)

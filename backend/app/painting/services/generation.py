"""AI draft generation: prompt assembly + Claude call + parse to GuideDraft (#526).

Bring-your-own-API-key (spec Q0; no keys in the repo). Takes the assembled system
prompt (#525) + per-figure user prompt, calls the Anthropic API asking for a
GuideDraft JSON object, and parses/validates the result. Paint-id reconciliation
happens in the job runner (draft_jobs) after this returns.

The Anthropic client is referenced via the module-level `Anthropic` symbol so
tests can monkeypatch it at the boundary — no live API call in the suite.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from anthropic import Anthropic
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import AppSetting
from app.painting.models import Guide
from app.painting.schemas import GuideDraft
from app.painting.services import images
from app.painting.services.generation_prompt import assemble_system_prompt, build_user_prompt
from app.services import secrets

# Appended to the user prompt when a reference image accompanies the request, so
# the model grounds skin tone / value / texture in the supplied image.
_REFERENCE_INSTRUCTION = (
    "\nA reference image of the figure/subject is attached. Analyze it for skin "
    "tone, overall value structure, and surface textures, and let it guide the "
    "palette and recipes you choose from the owned paints."
)

# Sensible default; the user can override via the `ai_model` app setting (#517).
DEFAULT_MODEL = "claude-sonnet-4-6"
# A full multi-tab guide's JSON runs well past 8k output tokens; 8192 truncated
# the reply mid-JSON and surfaced as a cryptic parse error. 16384 gives a whole
# guide room to complete — comfortably under Sonnet's 64K / Opus's 128K ceiling.
_MAX_TOKENS = 16384

# Generation effort → extended-thinking budget (tokens). "low" disables thinking
# for speed/cost; medium/high spend reasoning budget for richer guides.
_EFFORT_THINKING_BUDGET = {"low": 0, "medium": 4096, "high": 10000}


def _effort(db: Session) -> str:
    row = db.get(AppSetting, "ai_effort")
    value = row.value if row is not None else None
    return value if value in _EFFORT_THINKING_BUDGET else "low"


class GenerationError(RuntimeError):
    """Generation failed — bad/missing key, API error, or unparseable output."""


class MissingApiKeyError(GenerationError):
    """No API key is configured (caller should surface a 503)."""


def _model(db: Session) -> str:
    row = db.get(AppSetting, "ai_model")
    value = row.value if row is not None else None
    return value or DEFAULT_MODEL


@dataclass
class GuidesConfig:
    """Resolved AI Guide Drafts endpoint (model/key/effort). A dataclass (not a
    tuple) so the secret ``api_key`` field stays isolated under static
    analysis — see ``_OrganizeConfig`` in app/routers/models.py for why."""
    model: str
    api_key: str
    effort: str


def load_guides_config(db: Session) -> GuidesConfig:
    """Resolve the AI Guide Drafts endpoint. Raises MissingApiKeyError (a
    GenerationError) if nothing usable is configured — callers surface that as
    a 503, or as the job's error state.

    Driven by a named AiApiConfig assigned via the ``ai_guides_api`` setting
    (the "Use API" selector in Settings → AI & Integrations → AI Functions).
    Falls back to the legacy global ``ai_api_key`` / ``ai_model`` / ``ai_effort``
    settings when no config is assigned, for installs that predate named
    configs. Guide drafts are Anthropic-only today — the whole prompt/response
    pipeline assumes the Messages API — so only an Anthropic config applies.
    """
    enabled_row = db.get(AppSetting, "ai_guides_enabled")
    if not enabled_row or not bool(enabled_row.value):
        raise MissingApiKeyError("AI Guide Drafts is not enabled.")

    api_row = db.get(AppSetting, "ai_guides_api")
    config_id = api_row.value if api_row else None
    if config_id:
        from app.models import AiApiConfig

        cfg = db.get(AiApiConfig, int(config_id))
        if not cfg:
            raise MissingApiKeyError(
                "The AI API assigned to Guide Drafts no longer exists — reselect one in Settings."
            )
        if cfg.api_type != "anthropic":
            raise MissingApiKeyError(
                "AI Guide Drafts requires an Anthropic API — reselect one in Settings."
            )
        key = secrets.get_ai_api_config_key(db, cfg.id)
        if not key:
            raise MissingApiKeyError("No API key is configured for the assigned AI API.")
        effort = cfg.effort if cfg.effort in _EFFORT_THINKING_BUDGET else "low"
        return GuidesConfig(model=cfg.model or DEFAULT_MODEL, api_key=key, effort=effort)

    # Legacy fallback: standalone ai_api_key_enc / ai_model / ai_effort settings.
    key = secrets.get_ai_api_key(db)
    if not key:
        raise MissingApiKeyError("No AI API key is configured.")
    return GuidesConfig(model=_model(db), api_key=key, effort=_effort(db))


def _text_from_response(resp) -> str:
    """Concatenate the text blocks of an Anthropic messages response."""
    parts = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


def _parse_json_object(text: str) -> dict:
    """Parse the model's reply into a JSON object, tolerating code fences and
    incidental surrounding prose."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Strip a ```json … ``` fence.
        segments = cleaned.split("```")
        cleaned = segments[1] if len(segments) >= 2 else text
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    cleaned = cleaned.strip().strip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} span.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError as exc:
                raise GenerationError(f"model output was not valid JSON: {exc}") from exc
        raise GenerationError("model output contained no JSON object")


def _build_message_content(db: Session, guide: Guide):
    """The user-message content: the per-figure text prompt, plus a reference
    image block when the guide has one (Anthropic multimodal). Text-only — a
    plain string — when no reference image is set, matching the original path."""
    text = build_user_prompt(guide)
    reference = images.load_reference(db, guide)
    if reference is None:
        return text

    raw, media_type = reference
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(raw).decode("ascii"),
            },
        },
        {"type": "text", "text": text + _REFERENCE_INSTRUCTION},
    ]


def generate_guide_draft(db: Session, guide: Guide) -> GuideDraft:
    """Call Claude to generate a GuideDraft for a guide. Free of persistence —
    the job runner reconciles paints and saves the result."""
    cfg = load_guides_config(db)

    client = Anthropic(api_key=cfg.api_key)
    kwargs = {
        "model": cfg.model,
        "max_tokens": _MAX_TOKENS,
        "system": assemble_system_prompt(db),
        "messages": [{"role": "user", "content": _build_message_content(db, guide)}],
    }
    budget = _EFFORT_THINKING_BUDGET[cfg.effort]
    if budget:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        # max_tokens must exceed the thinking budget.
        kwargs["max_tokens"] = _MAX_TOKENS + budget
    try:
        # Stream and collect the final message: at these output sizes (and with
        # the thinking budget added on top) a non-streaming request risks the
        # SDK's long-request timeout. get_final_message() reassembles the whole
        # reply regardless.
        with client.messages.stream(**kwargs) as stream:
            resp = stream.get_final_message()
    except Exception as exc:  # anthropic.APIError and friends
        raise GenerationError(f"AI request failed: {exc}") from exc

    # A truncated reply (hit the output ceiling) yields invalid JSON; surface it
    # as an actionable error instead of a cryptic parse failure deep in the text.
    if getattr(resp, "stop_reason", None) == "max_tokens":
        raise GenerationError(
            "The guide was too long and got cut off before completing. "
            "Try lowering the generation effort or simplifying the figure, then retry."
        )

    data = _parse_json_object(_text_from_response(resp))
    try:
        return GuideDraft.model_validate(data)
    except ValidationError as exc:
        raise GenerationError(
            f"AI output did not match the GuideDraft schema: {exc}"
        ) from exc

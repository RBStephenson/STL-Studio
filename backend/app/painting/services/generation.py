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
DEFAULT_MODEL = "claude-sonnet-5"
# A full multi-tab guide's JSON runs well past 8k output tokens; 8192 truncated
# the reply mid-JSON and surfaced as a cryptic parse error. 16384 gives a whole
# guide room to complete — comfortably under Sonnet's 64K / Opus's 128K ceiling.
_MAX_TOKENS = 16384

# Generation effort, passed through as the API's own effort level. Adaptive
# thinking picks its depth per request, so there is no fixed token budget to
# reserve — "low" now means the cheapest/fastest setting rather than "thinking
# off" (STUDIO-395: the old fixed `budget_tokens` parameter is rejected with a
# 400 by every current model, and disabling thinking outright is itself invalid
# on some of them).
_EFFORT_LEVELS = ("low", "medium", "high")

# Models that predate adaptive thinking. They reject BOTH `thinking: adaptive`
# and `output_config.effort`, so they get neither and the Effort setting is a
# no-op for them — which suits the one entry here, since Haiku is chosen for
# speed and cost rather than reasoning depth. Keep this in step with
# ANTHROPIC_MODELS in frontend/src/pages/settings/AiIntegrationsTab.tsx.
_PRE_ADAPTIVE_MODELS = ("claude-haiku-4-5",)


def _effort(db: Session) -> str:
    row = db.get(AppSetting, "ai_effort")
    value = row.value if row is not None else None
    return value if value in _EFFORT_LEVELS else "low"


class GenerationError(RuntimeError):
    """Generation failed — bad/missing key, API error, or unparseable output."""


class MissingApiKeyError(GenerationError):
    """No API key is configured (caller should surface a 503)."""


def _model(db: Session) -> str:
    row = db.get(AppSetting, "ai_model")
    value = row.value if row is not None else None
    return value or DEFAULT_MODEL


@dataclass
class AnthropicApiConfig:
    """Resolved Anthropic endpoint (model/key/effort) for a feature that reuses
    the named-AiApiConfig selection mechanism. A dataclass (not a tuple) so the
    secret ``api_key`` field stays isolated under static analysis — see
    ``_OrganizeConfig`` in app/routers/models.py for why."""
    model: str
    api_key: str
    effort: str


def resolve_anthropic_config(
    db: Session, *, setting_key: str, feature_label: str
) -> AnthropicApiConfig:
    """Resolve an Anthropic endpoint from a named AiApiConfig setting, falling
    back to the legacy global ``ai_api_key`` / ``ai_model`` / ``ai_effort``
    settings when none is assigned. Raises MissingApiKeyError (a
    GenerationError) if nothing usable is configured.

    Shared by every feature that reuses the "Use API" selector pattern
    (Settings → AI & Integrations → AI Functions) — e.g. Guide Drafts'
    ``ai_guides_api`` and Paint Shelf's swatch-chart vision fallback
    (STUDIO-332) reusing the same setting. Feature-specific enable gates
    (like Guide Drafts' ``ai_guides_enabled``) are the caller's job, not
    this resolver's — a feature that has no enable flag of its own, or a
    different one, should not have to satisfy an unrelated feature's gate.
    """
    api_row = db.get(AppSetting, setting_key)
    config_id = api_row.value if api_row else None
    if config_id:
        from app.models import AiApiConfig

        cfg = db.get(AiApiConfig, int(config_id))
        if not cfg:
            raise MissingApiKeyError(
                f"The AI API assigned to {feature_label} no longer exists — reselect one in Settings."
            )
        if cfg.api_type != "anthropic":
            raise MissingApiKeyError(
                f"{feature_label} requires an Anthropic API — reselect one in Settings."
            )
        key = secrets.get_ai_api_config_key(db, cfg.id)
        if not key:
            raise MissingApiKeyError("No API key is configured for the assigned AI API.")
        effort = cfg.effort if cfg.effort in _EFFORT_LEVELS else "low"
        return AnthropicApiConfig(model=cfg.model or DEFAULT_MODEL, api_key=key, effort=effort)

    # Legacy fallback: standalone ai_api_key_enc / ai_model / ai_effort settings.
    key = secrets.get_ai_api_key(db)
    if not key:
        raise MissingApiKeyError("No AI API key is configured.")
    return AnthropicApiConfig(model=_model(db), api_key=key, effort=_effort(db))


def load_guides_config(db: Session) -> AnthropicApiConfig:
    """Resolve the AI Guide Drafts endpoint. Raises MissingApiKeyError (a
    GenerationError) if Guide Drafts isn't enabled or nothing usable is
    configured — callers surface that as a 503, or as the job's error state.

    Driven by a named AiApiConfig assigned via the ``ai_guides_api`` setting.
    Guide drafts are Anthropic-only today — the whole prompt/response pipeline
    assumes the Messages API — so only an Anthropic config applies.
    """
    enabled_row = db.get(AppSetting, "ai_guides_enabled")
    if not enabled_row or not bool(enabled_row.value):
        raise MissingApiKeyError("AI Guide Drafts is not enabled.")
    return resolve_anthropic_config(
        db, setting_key="ai_guides_api", feature_label="AI Guide Drafts"
    )


def text_from_response(resp) -> str:
    """Concatenate the text blocks of an Anthropic messages response.

    Shared with any feature that parses a Claude Messages API reply — e.g.
    Paint Shelf's swatch-chart vision fallback (STUDIO-332)."""
    parts = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


def parse_json_object(text: str) -> dict:
    """Parse the model's reply into a JSON object, tolerating code fences and
    incidental surrounding prose. Shared, see `text_from_response`."""
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
    # Adaptive thinking plus an effort level. `max_tokens` needs no headroom for
    # a separate thinking budget any more, because there isn't one.
    if cfg.model not in _PRE_ADAPTIVE_MODELS:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": cfg.effort}
    try:
        # Stream and collect the final message: at these output sizes a
        # non-streaming request risks the SDK's long-request timeout.
        # get_final_message() reassembles the whole reply regardless.
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

    data = parse_json_object(text_from_response(resp))
    try:
        return GuideDraft.model_validate(data)
    except ValidationError as exc:
        raise GenerationError(
            f"AI output did not match the GuideDraft schema: {exc}"
        ) from exc

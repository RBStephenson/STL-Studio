"""Generation prompt assembly (#525, M4 §8.3).

Builds the system + user prompts for AI guide generation: the value-first domain
rules (ported from the figure-painting skill, bundled at
`data/generation_prompt.md`) plus the user's live Paint Shelf injected as a hard
inventory constraint. Pure — no network, no model call (that's #526).

The bundled prompt ships under `app/painting/data/` because `docs/` isn't
included in the Docker image or the standalone binary; the docs skill file stays
the human source-of-truth this is derived from.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.painting.models import Guide, Paint, PaintBrand, PaintLine

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "data" / "generation_prompt.md"
_SHELF_PLACEHOLDER = "{shelf}"


def _load_template() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def build_shelf_constraint(db: Session) -> str:
    """Format the owned Paint Shelf as the inventory the model must stay within."""
    rows = (
        db.query(Paint.name, Paint.code, Paint.value_pct, Paint.hex,
                 PaintBrand.name, PaintLine.name)
        .join(PaintLine, Paint.paint_line_id == PaintLine.id)
        .join(PaintBrand, PaintLine.brand_id == PaintBrand.id)
        .filter(Paint.owned.is_(True))
        .order_by(PaintBrand.name, PaintLine.name, Paint.name)
        .all()
    )
    if not rows:
        return (
            "The Paint Shelf is EMPTY. Do not invent paints — tell the user to add "
            "paints to their shelf (or import a PaintRack CSV) before generating."
        )

    lines = ["Owned paints — the ONLY paints you may reference, by exact name:"]
    for name, code, value_pct, hex_, brand, line in rows:
        value = f", ~{value_pct}% value" if value_pct is not None else ""
        swatch = f", {hex_}" if hex_ else ""
        lines.append(f"- {name} ({code}) — {brand} / {line}{value}{swatch}")
    return "\n".join(lines)


def assemble_system_prompt(db: Session) -> str:
    """The full system prompt: domain rules + the live shelf constraint."""
    return _load_template().replace(_SHELF_PLACEHOLDER, build_shelf_constraint(db))


def build_user_prompt(guide: Guide) -> str:
    """The per-figure request derived from the guide's metadata/context."""
    parts = ["Generate a value-first painting guide for this figure:"]
    parts.append(f"- Title: {guide.title}")
    if guide.scale:
        parts.append(f"- Scale: {guide.scale}")
    if guide.franchise:
        parts.append(f"- Franchise / subject: {guide.franchise}")
    if guide.subtitle:
        parts.append(f"- Notes: {guide.subtitle}")
    if guide.light_source:
        parts.append(f"- Light source: {guide.light_source}")
    if guide.technique_tags:
        parts.append(f"- Techniques to feature: {', '.join(guide.technique_tags)}")
    brief = (guide.character_brief or {}).get("philosophy") if guide.character_brief else None
    if brief:
        parts.append(f"- Painter's brief: {brief}")
    parts.append(
        "\nReturn only the GuideDraft JSON object described in the system prompt."
    )
    return "\n".join(parts)

"""Draft reconciliation: map a GuideDraft's name-only paints to shelf IDs (#523).

A generated (or imported) GuideDraft may reference paints by `name` before they
map to real Paint Shelf rows. `reconcile_draft_paints` resolves those against the
shelf using the same matcher the HTML importer uses, fills in `paint_id`s, and
reports anything it couldn't resolve (the inventory-gap list, spec §9.7). It does
no AI and no network — pure DB lookup over the draft tree.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.painting.schemas import GuideDraft
from app.painting.services.importing import make_db_resolver


@dataclass
class UnresolvedDraftPaint:
    name: str
    tab: str
    step: str


@dataclass
class DraftReconcileResult:
    draft: GuideDraft           # a copy with paint_ids filled where resolved
    unresolved: list[UnresolvedDraftPaint] = field(default_factory=list)


def reconcile_draft_paints(db: Session, draft: GuideDraft) -> DraftReconcileResult:
    """Resolve name-only swatch/mix paints in a draft to Paint Shelf IDs.

    Swatches that already carry a `paint_id` are left untouched. Name-only
    paints are looked up; a hit fills `paint_id`, a miss is reported. The input
    draft isn't mutated — a reconciled copy is returned.
    """
    resolver = make_db_resolver(db)
    data = draft.model_dump()
    unresolved: list[UnresolvedDraftPaint] = []

    def _resolve_entry(entry: dict, tab_name: str, step_title: str) -> None:
        if entry.get("paint_id") is not None:
            return
        name = (entry.get("name") or "").strip()
        if not name:
            return
        paint_id = resolver(name, None)
        if paint_id is not None:
            entry["paint_id"] = paint_id
        else:
            unresolved.append(
                UnresolvedDraftPaint(name=name, tab=tab_name, step=step_title)
            )

    for tab in data.get("tabs", []):
        tab_name = tab.get("name", "")
        for phase in tab.get("phases", []):
            for step in phase.get("steps", []):
                step_title = step.get("title", "")
                for swatch in step.get("swatches", []):
                    _resolve_entry(swatch, tab_name, step_title)
                for component in step.get("mix_components", []):
                    _resolve_entry(component, tab_name, step_title)

    return DraftReconcileResult(
        draft=GuideDraft.model_validate(data),
        unresolved=unresolved,
    )

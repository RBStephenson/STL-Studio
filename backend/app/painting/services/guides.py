"""Guide assembly helpers (M2, #258).

Turns the nested `GuideCreate`/`GuideUpdate` payloads into the relational
Tab -> Phase -> Step -> Swatch/MixComponent spine, and validates the paint
references every swatch/mix points at. The JSON display blocks are stored
verbatim (as dicts) on their owning row.

The router owns transaction/commit and the guide-header fields; this module
owns the content spine so the router stays thin.
"""
from sqlalchemy.orm import Session

from app.painting.models import (
    GuideMixComponent, GuidePhase, GuideStep, GuideSwatch, GuideTab, Paint,
)
from app.painting.schemas import GuideCreate, GuideUpdate, TabIn


def collect_paint_ids(tabs: list[TabIn]) -> set[int]:
    """Every paint_id referenced by a swatch or mix component in the tree."""
    ids: set[int] = set()
    for tab in tabs:
        for phase in tab.phases:
            for step in phase.steps:
                ids.update(s.paint_id for s in step.swatches)
                # A mix component may be name-only (paint_id None) under #425.
                ids.update(m.paint_id for m in step.mix_components if m.paint_id is not None)
    return ids


def missing_paint_ids(db: Session, paint_ids: set[int]) -> list[int]:
    """Which of these paint ids don't exist (sorted, for a stable message)."""
    if not paint_ids:
        return []
    found = {
        pid for (pid,) in db.query(Paint.id).filter(Paint.id.in_(paint_ids)).all()
    }
    return sorted(paint_ids - found)


def _block(value) -> dict | None:
    """A JSON display block (Pydantic model) -> dict for the JSON column."""
    return value.model_dump() if value is not None else None


def build_tab(tab_in: TabIn) -> GuideTab:
    tab = GuideTab(
        name=tab_in.name,
        dom_id=tab_in.dom_id,
        sort_order=tab_in.sort_order,
        has_expert_subtab=tab_in.has_expert_subtab,
        section=_block(tab_in.section),
        value_map=_block(tab_in.value_map),
        subtabs=[s.model_dump() for s in tab_in.subtabs],
        callouts=[c.model_dump() for c in tab_in.callouts],
        raw_blocks=[b.model_dump() for b in tab_in.raw_blocks],
        method_block=_block(tab_in.method_block),
        skin_config=_block(tab_in.skin_config),
        metals_config=_block(tab_in.metals_config),
    )
    for phase_in in tab_in.phases:
        phase = GuidePhase(
            label=phase_in.label,
            subtab_key=phase_in.subtab_key,
            sort_order=phase_in.sort_order,
        )
        for step_in in phase_in.steps:
            step = GuideStep(
                title=step_in.title,
                technique_tag=step_in.technique_tag,
                technique_label=step_in.technique_label,
                body=step_in.body,
                value_intent=step_in.value_intent,
                tip=step_in.tip,
                warning=step_in.warning,
                ratio_box=step_in.ratio_box,
                sort_order=step_in.sort_order,
            )
            step.swatches = [
                GuideSwatch(
                    paint_id=s.paint_id,
                    value_pct=s.value_pct,
                    role_label=s.role_label,
                    sort_order=s.sort_order,
                )
                for s in step_in.swatches
            ]
            step.mix_components = [
                GuideMixComponent(
                    paint_id=m.paint_id, name=m.name, parts=m.parts, sort_order=m.sort_order
                )
                for m in step_in.mix_components
            ]
            phase.steps.append(step)
        tab.phases.append(phase)
    return tab


def build_tabs(tabs_in: list[TabIn]) -> list[GuideTab]:
    return [build_tab(t) for t in tabs_in]

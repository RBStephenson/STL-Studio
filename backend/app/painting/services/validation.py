"""Code-convention validation (M1 slice, #244 — spec §6.2, §8.4).

A paint line may declare a `code_pattern` regex (e.g. ^MPA-\\d{3}$) that every
paint code in the line must satisfy. The pattern is applied with re.search as
written — the spec's examples carry their own anchors, so the pattern author
controls strictness.

The guide validator (`validate_guide`, #489) builds on this: it walks a guide's
content tree and returns structured flags (block vs warn) for the editor panel
and the publish gate (spec §8.4). The domain colour-accuracy checks (skin-anchor
band, highlight-direction) are deferred to #506 — they need complexion metadata
the spine doesn't carry yet.
"""
import re

from sqlalchemy.orm import Session

from app.painting.models import Guide, Paint, PaintLine
from app.painting.schemas import ValidationFlag

# Minimum value% spread between the lightest and darkest valued swatch in a step
# before the range reads as "compressed" (skill Color Accuracy Checker, Step 4).
VALUE_COMPRESSION_MIN = 15


def validate_pattern(pattern: str | None) -> str | None:
    """Return an error message if `pattern` is not a valid regex, else None."""
    if not pattern:
        return None
    try:
        re.compile(pattern)
    except re.error as e:
        return f"Invalid code pattern '{pattern}': {e}"
    return None


def validate_code(code: str, pattern: str | None) -> str | None:
    """Return an error message if `code` does not satisfy the line's
    `code_pattern`, else None. Lines without a pattern accept any code."""
    if not pattern:
        return None
    try:
        compiled = re.compile(pattern)
    except re.error:
        # Patterns are validated on line create/update, so this only guards
        # against hand-edited DBs — skip rather than block all writes.
        return None
    # No !r here — repr doubles backslashes in patterns like ^MPA-\d{3}$.
    if compiled.search(code) is None:
        return f"Code '{code}' does not match the line's code pattern '{pattern}'"
    return None


# ---------------------------------------------------------------------------
# Guide validator (#489)
# ---------------------------------------------------------------------------

class _PaintInfo:
    __slots__ = ("owned", "code", "name", "pattern")

    def __init__(self, owned: bool, code: str, name: str, pattern: str | None):
        self.owned = owned
        self.code = code
        self.name = name
        self.pattern = pattern


def _paint_info(db: Session, paint_ids: set[int]) -> dict[int, _PaintInfo]:
    """One query: id -> (owned, code, name, line code_pattern) for the checks."""
    if not paint_ids:
        return {}
    rows = (
        db.query(Paint.id, Paint.owned, Paint.code, Paint.name, PaintLine.code_pattern)
        .join(PaintLine, Paint.paint_line_id == PaintLine.id)
        .filter(Paint.id.in_(paint_ids))
        .all()
    )
    return {r[0]: _PaintInfo(r[1], r[2], r[3], r[4]) for r in rows}


def validate_guide(db: Session, guide: Guide) -> list[ValidationFlag]:
    """Walk a guide's content tree and return validation flags (#489, spec §8.4).

    `block` flags prevent publish; `warn` flags are advisory. Unknown paint ids
    are already rejected at save time (router `_validate_paints`), so here a
    resolved paint is assumed to exist — we check `owned` and code validity.
    Colour-accuracy domain checks are deferred (#506)."""
    flags: list[ValidationFlag] = []

    ids: set[int] = set()
    for tab in guide.tabs:
        for phase in tab.phases:
            for step in phase.steps:
                ids.update(s.paint_id for s in step.swatches if s.paint_id is not None)
                ids.update(m.paint_id for m in step.mix_components if m.paint_id is not None)
    info = _paint_info(db, ids)

    def paint_checks(paint_id: int | None, loc: dict, where: str) -> None:
        if paint_id is None:
            return
        pi = info.get(paint_id)
        if pi is None:
            return  # existence already enforced upstream
        if not pi.owned:
            flags.append(ValidationFlag(
                severity="block", code="paint_not_owned",
                message=f"{pi.name} {pi.code} ({where}) isn't marked owned on the Paint Shelf.",
                **loc,
            ))
        code_err = validate_code(pi.code, pi.pattern)
        if code_err:
            flags.append(ValidationFlag(
                severity="block", code="paint_code_invalid",
                message=f"{pi.name}: {code_err}.", **loc,
            ))

    for ti, tab in enumerate(guide.tabs):
        step_count = sum(len(p.steps) for p in tab.phases)
        if step_count == 0:
            flags.append(ValidationFlag(
                severity="warn", code="empty_tab",
                message=f"Tab “{tab.name}” has no steps.",
                tab_index=ti, path=tab.name,
            ))
        for pi_, phase in enumerate(tab.phases):
            for si, step in enumerate(phase.steps):
                path = f"{tab.name} › {phase.label or 'Steps'} › {step.title or f'Step {si + 1}'}"
                base = {"tab_index": ti, "phase_index": pi_, "step_index": si, "path": path}

                if not step.swatches and not step.mix_components:
                    flags.append(ValidationFlag(
                        severity="warn", code="step_no_swatches",
                        message="Step has no paint swatches.", **base,
                    ))

                values: list[int] = []
                for wi, sw in enumerate(step.swatches):
                    loc = {**base, "swatch_index": wi}
                    paint_checks(sw.paint_id, loc, "swatch")
                    if sw.value_pct is not None:
                        if sw.value_pct < 0 or sw.value_pct > 100:
                            flags.append(ValidationFlag(
                                severity="warn", code="value_out_of_range",
                                message=f"Value {sw.value_pct}% is outside 0–100.", **loc,
                            ))
                        else:
                            values.append(sw.value_pct)
                for mc in step.mix_components:
                    paint_checks(mc.paint_id, base, "mix component")

                if len(values) >= 2 and max(values) - min(values) < VALUE_COMPRESSION_MIN:
                    flags.append(ValidationFlag(
                        severity="warn", code="value_compression",
                        message=(
                            f"Swatch values span only {max(values) - min(values)}% "
                            f"({min(values)}–{max(values)}%); push the contrast wider."
                        ),
                        **base,
                    ))

    return flags

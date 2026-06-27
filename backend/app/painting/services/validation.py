"""Code-convention validation (M1 slice, #244 — spec §6.2, §8.4).

A paint line may declare a `code_pattern` regex (e.g. ^MPA-\\d{3}$) that every
paint code in the line must satisfy. The pattern is applied with re.search as
written — the spec's examples carry their own anchors, so the pattern author
controls strictness.

The guide validator (`validate_guide`, #489) builds on this: it walks a guide's
content tree and returns structured flags (block vs warn) for the editor panel
and the publish gate (spec §8.4). The domain colour-accuracy checks (skin-anchor
band #498, highlight-direction #506) ride alongside; both fire only when a Skin
tab states the character's complexion band, so guides without that metadata are
never flagged.
"""
import re

import numpy as np
from skimage.color import rgb2lab
from sqlalchemy.orm import Session

from app.painting.models import Guide, Paint, PaintLine
from app.painting.schemas import ValidationFlag

# Minimum value% spread between the lightest and darkest valued swatch in a step
# before the range reads as "compressed" (skill Color Accuracy Checker, Step 4).
# Value priority by scale (generation_prompt.md §"Value priority by scale"): small
# scales are painted with extreme/high contrast, so a wider spread is expected.
VALUE_COMPRESSION_MIN = 15
VALUE_COMPRESSION_MIN_HIGH_CONTRAST = 25
_HIGH_CONTRAST_SCALES = {"28mm", "1:12"}

# The white & black rule (generation_prompt.md §"The white & black rule"): pure
# white/black flatten as general swatches — white is the final specular only,
# black only the deepest occlusion. A swatch reading near-pure at these bounds
# must carry a role that justifies it.
NEAR_WHITE_VALUE = 98
NEAR_BLACK_VALUE = 2
_PURE_WHITE_HEXES = {"#ffffff", "#fff"}
_PURE_BLACK_HEXES = {"#000000", "#000"}
# Role keywords (matched case-insensitively in role_label) that legitimise a
# near-white / near-black swatch.
_WHITE_OK_ROLES = ("specular", "highlight", "catch", "edge", "hot")
_BLACK_OK_ROLES = ("shadow", "occlusion", "recess", "lining", "pupil", "black", "darkest")

# Skin-anchor band validation (skill §"Step 2 — Skin Tone Anchor Validation",
# folded from #506). Complexion bands ordered light→dark; the anchor paint must
# not belong to a lighter band than the character's stated complexion. Fires
# only when a Skin tab carries a stated band (skin_config.complexion_band), so
# guides without that metadata are not flagged.
_COMPLEXION_BANDS = ["very_fair", "fair", "medium", "olive", "brown", "deep"]
# Free-text band → canonical ordinal key. Substrings, matched case-insensitively.
_BAND_KEYWORDS = {
    "porcelain": "very_fair", "very fair": "very_fair",
    "fair": "fair",
    "medium": "medium", "tan": "medium",
    "olive": "olive", "mediterranean": "olive",
    "brown": "brown",
    "deep": "deep", "dark brown": "deep",
}
# Anchor paint name (lowercased substring) → the complexion band it anchors,
# from the skill's Step 2 table (Pro Acryl + Army Painter Fanatic triads).
_ANCHOR_PAINT_BAND = {
    "shadow flesh": "very_fair", "bright shadow flesh": "very_fair",
    "pearl skin": "very_fair", "opal skin": "very_fair", "ruby skin": "very_fair",
    "warm flesh": "fair", "peach flesh": "fair", "barbarian flesh": "fair",
    "agate skin": "fair", "moonstone skin": "fair",
    "advanced flesh tone": "medium", "tan flesh": "medium",
    "leopard stone skin": "medium", "tourmaline skin": "medium", "jasper skin": "medium",
    "olive flesh": "olive", "topaz skin": "olive",
    "tiger's eye skin": "olive", "carnelian skin": "olive",
    "dark warm flesh": "brown", "quartz skin": "brown",
    "dorado skin": "brown", "amber skin": "brown",
    "dark flesh": "deep", "mocca skin": "deep",
    "onyx skin": "deep", "obsidian skin": "deep",
}
# role_label keywords that mark a swatch as the skin mid-tone anchor.
_ANCHOR_ROLES = ("anchor", "mid-tone", "midtone", "mid tone", "base")

# Highlight-direction validation (skill §"Step 3 — Highlight Direction Validation",
# #506). On brown/deep complexions the highlight must shift warm golden-amber —
# pink/cream/rose-triad highlights read chalky or tonally wrong. Cool highlights
# are only acceptable under a stated cool light source.
_DARK_SKIN_BANDS = {"brown", "deep"}
# role_label keywords marking a swatch as a skin highlight.
_HIGHLIGHT_ROLES = ("highlight", "specular", "apex", "peak", "raised", "catch")
# Highlight paints the skill names as wrong on dark/deep skin (rose triad +
# pink/cream/pearl/ivory), matched as lowercased substrings.
_WRONG_DARK_HIGHLIGHT = (
    "pearl skin", "opal skin", "ruby skin", "moonstone skin", "agate skin",
    "barbarian flesh", "bright shadow flesh", "shadow flesh",
    "rose", "pink", "cream", "ivory", "pearl",
)
# Below this CIE b* a tinted highlight isn't "warm" (golden); pink and cool
# highlights both fall here. Near-white specular (low chroma) is exempt.
_HIGHLIGHT_WARM_B_MIN = 8.0
_HIGHLIGHT_MIN_CHROMA = 12.0
# light_source notes that justify a cooler highlight (skill: "cool only under
# cool light").
_COOL_LIGHT_KEYWORDS = ("cool", "cold", "blue", "moon", "night", "overcast")


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
    __slots__ = ("owned", "code", "name", "pattern", "hex")

    def __init__(self, owned: bool, code: str, name: str, pattern: str | None, hex_: str | None):
        self.owned = owned
        self.code = code
        self.name = name
        self.pattern = pattern
        self.hex = hex_


def _paint_info(db: Session, paint_ids: set[int]) -> dict[int, _PaintInfo]:
    """One query: id -> (owned, code, name, line code_pattern, hex) for the checks."""
    if not paint_ids:
        return {}
    rows = (
        db.query(Paint.id, Paint.owned, Paint.code, Paint.name,
                 PaintLine.code_pattern, Paint.hex)
        .join(PaintLine, Paint.paint_line_id == PaintLine.id)
        .filter(Paint.id.in_(paint_ids))
        .all()
    )
    return {r[0]: _PaintInfo(r[1], r[2], r[3], r[4], r[5]) for r in rows}


def _role_matches(role_label: str | None, keywords) -> bool:
    """True when the swatch's role_label contains any of the keywords."""
    if not role_label:
        return False
    low = role_label.lower()
    return any(k in low for k in keywords)


def _is_near_white(hex_: str | None, value_pct: int | None) -> bool:
    if hex_ and hex_.strip().lower() in _PURE_WHITE_HEXES:
        return True
    return value_pct is not None and value_pct >= NEAR_WHITE_VALUE


def _is_near_black(hex_: str | None, value_pct: int | None) -> bool:
    if hex_ and hex_.strip().lower() in _PURE_BLACK_HEXES:
        return True
    return value_pct is not None and value_pct <= NEAR_BLACK_VALUE


def _stated_band(tab) -> str | None:
    """The character's complexion band stated on a Skin tab, normalised to a
    canonical ordinal key, or None when not stated. Reads `complexion_band` from
    the tab's skin_config / method_block JSON (no schema change; #506 wires the
    draft to emit it)."""
    for block in (tab.skin_config, tab.method_block):
        if isinstance(block, dict):
            raw = block.get("complexion_band")
            if isinstance(raw, str) and raw.strip():
                low = raw.lower()
                # Prefer an exact canonical key, else match a keyword substring.
                if low in _COMPLEXION_BANDS:
                    return low
                for kw, band in _BAND_KEYWORDS.items():
                    if kw in low:
                        return band
    return None


def _anchor_band(paint_name: str | None) -> str | None:
    """The complexion band an anchor paint belongs to, by name, or None."""
    if not paint_name:
        return None
    low = paint_name.lower()
    for needle, band in _ANCHOR_PAINT_BAND.items():
        if needle in low:
            return band
    return None


def _hex_lab(hex_: str | None) -> tuple[float, float, float] | None:
    """'#RRGGBB' -> CIE Lab (L*, a*, b*), or None for missing/malformed hex."""
    if not hex_:
        return None
    s = hex_.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        rgb = np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], dtype=float) / 255.0
    except ValueError:
        return None
    lab = rgb2lab(rgb.reshape(1, 1, 3)).reshape(3)
    return float(lab[0]), float(lab[1]), float(lab[2])


def _light_is_cool(guide: Guide) -> bool:
    """True when the guide states a cool/cold light source (justifies cooler
    highlights, skill Step 3)."""
    note = (guide.light_source or "").lower()
    return any(k in note for k in _COOL_LIGHT_KEYWORDS)


def _wrong_dark_highlight(name: str | None, hex_: str | None, light_cool: bool) -> str | None:
    """Why this highlight is wrong on dark/deep skin, or None if it's fine.

    Pink/cream/rose-triad paints are flagged by name (always wrong). A tinted
    highlight that isn't warm by hue (low CIE b*) is flagged unless a cool light
    source is stated. Near-white specular highlights are exempt.
    """
    low = (name or "").lower()
    if any(k in low for k in _WRONG_DARK_HIGHLIGHT):
        return "pink/cream"
    lab = _hex_lab(hex_)
    if lab is not None and not light_cool:
        _, a, b = lab
        chroma = (a * a + b * b) ** 0.5
        if chroma >= _HIGHLIGHT_MIN_CHROMA and b < _HIGHLIGHT_WARM_B_MIN:
            return "not warm"
    return None


def validate_guide(db: Session, guide: Guide, *, strict: bool = True) -> list[ValidationFlag]:
    """Walk a guide's content tree and return validation flags (#489, spec §8.4).

    `block` flags prevent publish; `warn` flags are advisory. Unknown paint ids
    are already rejected at save time (router `_validate_paints`), so here a
    resolved paint is assumed to exist — we check `owned` and code validity.

    Domain rules ported from the figure-painting skill (#498) ride alongside the
    structural checks: the white/black rule, the every-step value-intent rule,
    scale-aware value compression, the skin-anchor band check (#498), and the
    highlight-direction check (#506)."""
    flags: list[ValidationFlag] = []

    compression_min = (
        VALUE_COMPRESSION_MIN_HIGH_CONTRAST
        if (guide.scale in _HIGH_CONTRAST_SCALES)
        else VALUE_COMPRESSION_MIN
    )

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
                    pi = info.get(sw.paint_id) if sw.paint_id is not None else None
                    hex_ = pi.hex if pi else None
                    if sw.value_pct is not None:
                        if sw.value_pct < 0 or sw.value_pct > 100:
                            flags.append(ValidationFlag(
                                severity="warn", code="value_out_of_range",
                                message=f"Value {sw.value_pct}% is outside 0–100.", **loc,
                            ))
                        else:
                            values.append(sw.value_pct)
                    # The white & black rule: a near-pure swatch needs a role that
                    # justifies it (specular for white, occlusion for black).
                    label = pi.name if pi else (sw.name or "This swatch")
                    if _is_near_white(hex_, sw.value_pct) and not _role_matches(sw.role_label, _WHITE_OK_ROLES):
                        flags.append(ValidationFlag(
                            severity="warn", code="white_misuse",
                            message=(
                                f"{label} reads as pure white but isn't roled as a specular "
                                "highlight — pure white flattens a general swatch; reserve it "
                                "for the final specular dot/edge."
                            ),
                            **loc,
                        ))
                    if _is_near_black(hex_, sw.value_pct) and not _role_matches(sw.role_label, _BLACK_OK_ROLES):
                        flags.append(ValidationFlag(
                            severity="warn", code="black_misuse",
                            message=(
                                f"{label} reads as pure black but isn't roled as a shadow/"
                                "occlusion — pure black reads as a hole; use a cool dark anchor "
                                "and reserve near-black for the deepest recesses."
                            ),
                            **loc,
                        ))
                for mc in step.mix_components:
                    paint_checks(mc.paint_id, base, "mix component")

                if strict:
                    # Every step must state its value intent (generation_prompt.md
                    # §"Core philosophy"). Only nudge steps that actually apply paint.
                    if (step.swatches or step.mix_components) and not (step.value_intent or "").strip():
                        flags.append(ValidationFlag(
                            severity="warn", code="value_intent_missing",
                            message="Step applies paint but states no value intent (target value).",
                            **base,
                        ))

                    if len(values) >= 2 and max(values) - min(values) < compression_min:
                        flags.append(ValidationFlag(
                            severity="warn", code="value_compression",
                            message=(
                                f"Swatch values span only {max(values) - min(values)}% "
                                f"({min(values)}–{max(values)}%); push the contrast wider."
                            ),
                            **base,
                        ))

        _check_skin_anchor(tab, ti, info, flags)
        _check_highlight_direction(tab, ti, guide, info, flags)

    return flags


def _check_skin_anchor(tab, ti: int, info: dict, flags: list[ValidationFlag]) -> None:
    """Skin-anchor band check (skill Step 2, folded from #506).

    When a Skin tab states the character's complexion band, the mid-tone anchor
    paint must not belong to a *lighter* band — the single most common skin
    error. Skipped entirely when no band is stated, so guides without the
    metadata are never flagged."""
    if "skin" not in (tab.name or "").lower():
        return
    band = _stated_band(tab)
    if band is None:
        return
    band_idx = _COMPLEXION_BANDS.index(band)

    for pi_, phase in enumerate(tab.phases):
        for si, step in enumerate(phase.steps):
            for wi, sw in enumerate(step.swatches):
                if not _role_matches(sw.role_label, _ANCHOR_ROLES):
                    continue
                pi = info.get(sw.paint_id) if sw.paint_id is not None else None
                anchor = _anchor_band(pi.name if pi else sw.name)
                if anchor is None:
                    continue
                if _COMPLEXION_BANDS.index(anchor) < band_idx:
                    name = pi.name if pi else sw.name
                    value = f" (~{sw.value_pct}% value)" if sw.value_pct is not None else ""
                    path = f"{tab.name} › {phase.label or 'Steps'} › {step.title or f'Step {si + 1}'}"
                    flags.append(ValidationFlag(
                        severity="warn", code="skin_anchor_too_light",
                        message=(
                            f"⚠ COLOR ACCURACY FLAG: {name}{value} anchors the "
                            f"'{anchor.replace('_', ' ')}' complexion band, lighter than the "
                            f"character's stated '{band.replace('_', ' ')}' — the anchor reads "
                            "too light. Use the band-appropriate anchor (skill Step 2)."
                        ),
                        tab_index=ti, phase_index=pi_, step_index=si, swatch_index=wi, path=path,
                    ))


def _check_highlight_direction(
    tab, ti: int, guide: Guide, info: dict, flags: list[ValidationFlag],
) -> None:
    """Highlight-direction check (skill Step 3, #506).

    On a Skin tab stating a brown/deep complexion, skin highlights must shift
    warm golden-amber; pink/cream/rose highlights (or cool ones, absent a cool
    light source) read wrong. Skipped for lighter bands and when no band is
    stated, so guides without the metadata are never flagged."""
    if "skin" not in (tab.name or "").lower():
        return
    band = _stated_band(tab)
    if band not in _DARK_SKIN_BANDS:
        return
    light_cool = _light_is_cool(guide)

    for pi_, phase in enumerate(tab.phases):
        for si, step in enumerate(phase.steps):
            for wi, sw in enumerate(step.swatches):
                if not _role_matches(sw.role_label, _HIGHLIGHT_ROLES):
                    continue
                pi = info.get(sw.paint_id) if sw.paint_id is not None else None
                name = pi.name if pi else sw.name
                hex_ = pi.hex if pi else None
                reason = _wrong_dark_highlight(name, hex_, light_cool)
                if reason is None:
                    continue
                detail = (
                    "pink/cream highlights read chalky on deep skin"
                    if reason == "pink/cream"
                    else "this highlight isn't warm enough"
                )
                path = f"{tab.name} › {phase.label or 'Steps'} › {step.title or f'Step {si + 1}'}"
                flags.append(ValidationFlag(
                    severity="warn", code="highlight_direction",
                    message=(
                        f"⚠ COLOR ACCURACY FLAG: {name} as a highlight on "
                        f"'{band.replace('_', ' ')}' skin — {detail}. Shift warm "
                        "golden-amber (skill Step 3)."
                    ),
                    tab_index=ti, phase_index=pi_, step_index=si, swatch_index=wi, path=path,
                ))

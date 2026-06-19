"""Static-HTML export: serialize a structured guide back to the legacy
self-contained HTML file format (spec §9.5, §9.6).

Half of the golden-fixture round-trip (#261): import a hand-built guide ->
export it here -> normalized-DOM diff against the original. The DOM emitted
here reproduces the real corpus shape (`painting-guides/by-category/**/*.html`),
anchored on the latest exemplar (Presto). Driven by the same data the React
reader (#259) consumes, so the two stay in lockstep — HTML is an output, never
the source of truth (spec §9.1).

Scope note (#260): the structured *data* tabs round-trip (hero, paint bar,
char brief, section header, value map, method block, sub-tabs, phases/steps/
swatches, the GUIDE_THINNING block). The shared **skills tabs**
(airbrush-skills / brush-skills / thinning-ref) are emitted as the injection
placeholders the corpus ships — their bespoke content is built at runtime by
skills-reference.js and isn't part of the guide schema. Series-badge sibling
cross-links need stored legacy filenames (a follow-up the #261 round-trip will
justify); only the active chip is emitted here. Prose fields (char brief,
section intro, method recommendation/freckle note, step body/tip/warning) are
authored HTML and emitted verbatim; plain-text fields are escaped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape

from sqlalchemy.orm import Session

from app.painting.models import Guide, Paint, PaintBrand, PaintLine

GUIDE_CSS_HREF = "../../assets/guide.css"
PRINT_CSS_HREF = "../../assets/print.css"
GUIDE_JS_SRC = "../../assets/guide.js"
SKILLS_JS_SRC = "../../assets/skills-reference.js"

# The three shared tabs skills-reference.js injects at runtime (label + dom id).
SKILLS_TABS = [
    ("Airbrush Skills", "airbrush-skills"),
    ("Brush Skills", "brush-skills"),
    ("Thinning Ref", "thinning-ref"),
]

# Author footer — identical across the corpus (boilerplate, not guide data).
_FOOTER = (
    '<footer class="guide-footer">\n'
    "  Guide by\n"
    '  <a href="https://www.youtube.com/@brent_the_programmer9108" target="_blank">brent_the_programmer</a>\n'
    "  &middot;\n"
    '  <a href="https://instagram.com/stephenson913" target="_blank">@stephenson913</a>\n'
    "</footer>"
)

_BACK_TO_TOP = (
    '<button class="back-to-top" id="backToTop" title="Back to top"\n'
    "        onclick=\"window.scrollTo({top:0,behavior:'smooth'})\">↑</button>"
)

_REF_MODAL = (
    '<div class="ref-modal" id="refModal" onclick="if(event.target===this)closeRefModal()">\n'
    '  <div class="ref-modal-inner">\n'
    '    <button class="ref-modal-close" onclick="closeRefModal()" title="Close">✕</button>\n'
    '    <img class="ref-modal-img" id="refModalImg" src="" alt="">\n'
    '    <div class="ref-modal-caption" id="refModalCaption"></div>\n'
    "  </div>\n"
    "</div>"
)

# Inline behaviors (ref modal + sub-tab switch + back-to-top); shared boilerplate.
_BEHAVIOR_JS = """  function openRefModal(src, alt) {
    var modal = document.getElementById('refModal');
    document.getElementById('refModalImg').src = src;
    document.getElementById('refModalImg').alt = alt;
    document.getElementById('refModalCaption').textContent = alt;
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
  function closeRefModal() {
    document.getElementById('refModal').classList.remove('open');
    document.body.style.overflow = '';
  }
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeRefModal();
  });

  function showSubTab(parentId, contentId, btn) {
    const parent = document.getElementById(parentId);
    if (!parent) return;
    parent.querySelectorAll('.sub-content').forEach(c => c.classList.remove('active'));
    parent.querySelectorAll('.sub-tab').forEach(b => b.classList.remove('active'));
    const el = document.getElementById(contentId);
    if (el) el.classList.add('active');
    if (btn) btn.classList.add('active');
  }
  (function() {
    const btn = document.getElementById('backToTop');
    if (!btn) return;
    window.addEventListener('scroll', function() {
      btn.classList.toggle('visible', window.scrollY > 300);
    }, { passive: true });
  })();"""


@dataclass
class PaintInfo:
    name: str
    code: str
    brand: str
    hex: str | None


def _t(value) -> str:
    """Escape a plain-text node (& < > only) — authored apostrophes/quotes
    survive. Attribute values use escape(..., quote=True)."""
    return escape(str(value), quote=False)


def _attr(value) -> str:
    return escape(str(value), quote=True)


def _html(value) -> str:
    """An authored rich-text field — emitted verbatim (may carry <strong>/<em>/<a>)."""
    return "" if value is None else str(value)


def _slugify(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in text)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "tab"


def _paint_lookup(db: Session, guide: Guide) -> dict[int, PaintInfo]:
    ids: set[int] = set()
    for tab in guide.tabs:
        for phase in tab.phases:
            for step in phase.steps:
                ids.update(s.paint_id for s in step.swatches)
                ids.update(m.paint_id for m in step.mix_components)
    if not ids:
        return {}
    rows = (
        db.query(Paint, PaintBrand.name)
        .join(PaintLine, Paint.paint_line_id == PaintLine.id)
        .join(PaintBrand, PaintLine.brand_id == PaintBrand.id)
        .filter(Paint.id.in_(ids))
        .all()
    )
    return {
        paint.id: PaintInfo(name=paint.name, code=paint.code, brand=brand, hex=paint.hex)
        for paint, brand in rows
    }


def attach_resolved_paints(db: Session, guide: Guide) -> Guide:
    """Attach a transient ``.paint`` summary to every swatch/mix component so the
    API read schema surfaces resolved name/code/hex/brand. The relational spine
    stores only ``paint_id``; the React reader (#259) needs the display fields
    that the static exporter resolves the same way (``_paint_lookup``). The
    attribute is unmapped, so it is never persisted."""
    from app.painting.schemas import PaintSummary

    paints = _paint_lookup(db, guide)

    def summary(paint_id: int) -> PaintSummary | None:
        info = paints.get(paint_id)
        if info is None:
            return None
        return PaintSummary(name=info.name, code=info.code, brand=info.brand, hex=info.hex)

    for tab in guide.tabs:
        for phase in tab.phases:
            for step in phase.steps:
                for node in (*step.swatches, *step.mix_components):
                    node.paint = summary(node.paint_id)
    return guide


def _tab_dom_id(tab) -> str:
    return tab.dom_id or _slugify(tab.name)


class _Buf:
    def __init__(self) -> None:
        self._parts: list[str] = []

    def add(self, html: str) -> None:
        self._parts.append(html)

    def __str__(self) -> str:
        return "\n".join(self._parts)


# --- swatches / steps ------------------------------------------------------

def _swatch_value(value_pct: int | None, role_label: str | None) -> str:
    bits: list[str] = []
    if value_pct is not None:
        bits.append(f"~{value_pct}% value")
    if role_label:
        bits.append(role_label)
    return " — ".join(bits)


def _render_swatch(swatch, paints: dict[int, PaintInfo]) -> str:
    info = paints.get(swatch.paint_id)
    if info is None:  # CRUD validates paint ids, so this is defensive only
        return ""
    dot = f"background:{_attr(info.hex)}" if info.hex else ""
    name = f"{info.name} {info.code}".strip()
    value = _swatch_value(swatch.value_pct, swatch.role_label)
    value_span = f'<div class="swatch-value">{_t(value)}</div>' if value else ""
    return (
        '<div class="swatch">'
        f'<div class="swatch-dot" style="{dot}"></div>'
        '<div class="swatch-info">'
        f'<div class="swatch-name">{_t(name)}</div>'
        f'<div class="swatch-brand">{_t(info.brand)}</div>'
        f"{value_span}</div></div>"
    )


def _fmt_parts(parts: float) -> str:
    return str(int(parts)) if float(parts).is_integer() else f"{parts:g}"


def _hex_to_rgb(h: str) -> tuple[int, int, int] | None:
    s = h.lstrip("#")
    if len(s) != 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None


def _blend_hex(hexes: list[str | None]) -> str | None:
    """Mean RGB of the resolvable component colors — the mix chip's dot."""
    rgbs = [rgb for h in hexes if h and (rgb := _hex_to_rgb(h))]
    if not rgbs:
        return None
    n = len(rgbs)
    r, g, b = (sum(c[i] for c in rgbs) // n for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


def _render_mix(components, paints: dict[int, PaintInfo]) -> str:
    """A multi-paint mix as one swatch chip: blended dot, 'A + B' name, and a
    ratio suffix when the parts aren't all equal (#339). Re-joining the names
    restores the legacy swatch-name for the import round-trip."""
    infos = [(paints.get(c.paint_id), c.parts) for c in components]
    infos = [(info, parts) for info, parts in infos if info is not None]
    if not infos:
        return ""
    names = " + ".join(f"{info.name} {info.code}".strip() for info, _ in infos)
    parts = [p for _, p in infos]
    if len(set(parts)) > 1:
        names = f"{names} ({':'.join(_fmt_parts(p) for p in parts)})"
    dot = _blend_hex([info.hex for info, _ in infos])
    dot_style = f"background:{_attr(dot)}" if dot else ""
    return (
        '<div class="swatch">'
        f'<div class="swatch-dot" style="{dot_style}"></div>'
        '<div class="swatch-info">'
        f'<div class="swatch-name">{_t(names)}</div>'
        "</div></div>"
    )


def _render_step(buf: _Buf, step, number: int, paints: dict[int, PaintInfo]) -> None:
    tag = step.technique_tag or ""
    label = step.technique_label or (tag.title() if tag else "")
    number_text = f"Step {number} · {label}" if label else f"Step {number}"
    buf.add('<div class="step">')
    buf.add(f'<span class="{_attr(("step-number " + tag).strip())}">{_t(number_text)}</span>')
    buf.add(f"<h3>{_t(step.title)}</h3>")
    if step.body:
        buf.add(f"<p>{_html(step.body)}</p>")
    if step.swatches or step.mix_components:
        buf.add('<div class="swatches">')
        for s in step.swatches:
            buf.add(_render_swatch(s, paints))
        if step.mix_components:
            buf.add(_render_mix(step.mix_components, paints))
        buf.add("</div>")
    if step.ratio_box:
        buf.add(f'<div class="ratio-box">{_t(step.ratio_box)}</div>')
    if step.tip:
        buf.add(f'<div class="tip">{_html(step.tip)}</div>')
    if step.warning:
        buf.add(f'<div class="warning">{_html(step.warning)}</div>')
    buf.add("</div>")


def _render_phases(buf: _Buf, phases, paints: dict[int, PaintInfo]) -> None:
    """A run of phases (already filtered to one sub-content), steps numbered 1..N."""
    number = 0
    for phase in phases:
        if phase.label:  # unlabeled phases emit no divider
            buf.add(f'<div class="phase-label">{_t(phase.label)}</div>')
        for step in phase.steps:
            number += 1
            _render_step(buf, step, number, paints)


# --- tab display blocks ----------------------------------------------------

def _render_section_header(buf: _Buf, section: dict | None) -> None:
    if not section:
        return
    buf.add('<div class="section-header">')
    buf.add(f'<h2>{_t(section.get("heading", ""))}</h2>')
    if section.get("intro"):
        buf.add(f"<p>{_html(section['intro'])}</p>")
    buf.add("</div>")


def _render_value_map(buf: _Buf, value_map: dict | None) -> None:
    if not value_map or not value_map.get("chips"):
        return
    if value_map.get("label"):
        buf.add(f'<div class="phase-label">{_t(value_map["label"])}</div>')
    buf.add('<div class="value-map">')
    for chip in value_map["chips"]:
        buf.add(
            '<div class="value-chip">'
            f'<div class="chip-swatch" style="background:{_attr(chip.get("hex", ""))};"></div>'
            f'<div class="chip-val">~{_t(chip.get("value_pct", ""))}%</div>'
            f'<div class="chip-label">{_t(chip.get("zone_label", ""))}</div>'
            "</div>"
        )
    buf.add("</div>")


def _render_method_block(buf: _Buf, method: dict | None) -> None:
    if not method:
        return
    buf.add('<div class="phase-label">Method Selection</div>')
    if method.get("recommendation"):
        buf.add(f'<div class="method-rec-block">{_html(method["recommendation"])}</div>')
    cards = method.get("cards") or []
    if cards:
        buf.add('<div class="method-cards">')
        for card in cards:
            klass = "method-card recommended" if card.get("recommended") else "method-card"
            buf.add(f'<div class="{klass}">')
            if card.get("badge"):
                buf.add(f'<span class="method-card-badge">{_t(card["badge"])}</span>')
            buf.add(f'<h4>{_t(card.get("title", ""))}</h4>')
            if card.get("body"):
                buf.add(f"<p>{_html(card['body'])}</p>")
            for key, cls in (("pros", "mc-pros"), ("cons", "mc-cons"), ("best", "mc-best")):
                if card.get(key):
                    buf.add(f'<span class="{cls}">{_t(card[key])}</span>')
            buf.add("</div>")
        buf.add("</div>")
    if method.get("freckle_note"):
        buf.add(f'<div class="freckle-note">{_html(method["freckle_note"])}</div>')


def _render_callouts(buf: _Buf, callouts, kinds: tuple[str, ...]) -> None:
    """Tab-level callouts (#271). Intro 'text' nodes emit a <p>; 'tip'/'warning'
    emit the matching callout div. Filtered by `kinds` so intros render above the
    content and tip/warning render below it, each in document order."""
    for c in callouts or []:
        kind = c.get("kind")
        if kind not in kinds:
            continue
        if kind == "text":
            buf.add(f"<p>{_html(c.get('html', ''))}</p>")
        else:
            buf.add(f'<div class="{kind}">{_html(c.get("html", ""))}</div>')


def _render_tab(buf: _Buf, tab, paints: dict[int, PaintInfo], active: bool) -> None:
    dom_id = _tab_dom_id(tab)
    cls = "tab-content active" if active else "tab-content"
    buf.add(f'<div class="{cls}" id="{_attr(dom_id)}">')
    _render_section_header(buf, tab.section)
    _render_callouts(buf, tab.callouts, ("text",))
    _render_value_map(buf, tab.value_map)
    _render_method_block(buf, tab.method_block)
    # Verbatim unmodelled blocks (wargaming batch-stage / tier-card / etc., #271).
    for rb in tab.raw_blocks or []:
        buf.add(rb["html"])

    subtabs = tab.subtabs or []
    if subtabs:
        buf.add('<div class="phase-label">Step-by-Step</div>')
        buf.add('<div class="sub-tabs">')
        for i, sub in enumerate(subtabs):
            sub_cls = "sub-tab active" if i == 0 else "sub-tab"
            if sub.get("css_class"):
                sub_cls = f"{sub_cls} {sub['css_class']}" if i != 0 else \
                    f"sub-tab {sub['css_class']} active"
            content_id = f"{dom_id}-{sub['key']}"
            buf.add(
                f'<div class="{_attr(sub_cls)}" '
                f"onclick=\"showSubTab('{_attr(dom_id)}', '{_attr(content_id)}', this)\">"
                f"{_t(sub['label'])}</div>"
            )
        buf.add("</div>")
        for i, sub in enumerate(subtabs):
            content_id = f"{dom_id}-{sub['key']}"
            sc_cls = "sub-content active" if i == 0 else "sub-content"
            buf.add(f'<div class="{sc_cls}" id="{_attr(content_id)}">')
            sub_callouts = sub.get("callouts")
            _render_callouts(buf, sub_callouts, ("text",))
            sub_phases = [p for p in tab.phases if p.subtab_key == sub["key"]]
            _render_phases(buf, sub_phases, paints)
            _render_callouts(buf, sub_callouts, ("tip", "warning"))
            buf.add("</div>")
    else:
        direct = [p for p in tab.phases if not p.subtab_key]
        _render_phases(buf, direct, paints)
    _render_callouts(buf, tab.callouts, ("tip", "warning"))
    buf.add("</div>")


# --- GUIDE_THINNING --------------------------------------------------------

def _guide_thinning_js(thinning: dict | None) -> str:
    t = thinning or {}
    payload = {
        "airbrushRows": t.get("airbrush_rows") or [],
        "brushRows": t.get("brush_rows") or [],
        "thinningCards": t.get("thinning_cards") or [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).replace("</", "<\\/")


# --- document --------------------------------------------------------------

def _render_hero(buf: _Buf, db: Session, guide: Guide) -> None:
    buf.add('<div class="hero">')
    if guide.category_label:
        buf.add(f'<div class="category">{_t(guide.category_label)}</div>')
    lead = guide.title_lead or guide.title
    remainder = ""
    if guide.title_lead and guide.title.startswith(guide.title_lead):
        remainder = guide.title[len(guide.title_lead):]
    buf.add(f"<h1><span>{_t(lead)}</span>{_t(remainder)}</h1>")
    if guide.subtitle:
        buf.add(f'<div class="subtitle">{_t(guide.subtitle)}</div>')
    if guide.quote:
        buf.add(f'<div class="film-ref">\n  <em>"{_t(guide.quote)}"</em>\n</div>')
    # Series badge — active chip only (sibling cross-links need legacy filenames).
    buf.add('<div class="series-badge">')
    buf.add(f'<span class="active">{_t(guide.title_lead or guide.title)}</span>')
    buf.add("</div>")
    credit = guide.creator_credit or {}
    if credit.get("name"):
        parts = [f'Figure by <strong>{_t(credit["name"])}</strong>']
        if credit.get("url"):
            link_text = credit.get("link_text") or credit["url"]
            parts.append(
                f'<a href="{_attr(credit["url"])}" target="_blank">{_t(link_text)}</a>'
            )
        buf.add(f'<div class="creator-credit">\n  {" · ".join(parts)}\n</div>')
    buf.add("</div>")


def render_guide_html(db: Session, guide: Guide) -> str:
    paints = _paint_lookup(db, guide)
    buf = _Buf()

    buf.add("<!DOCTYPE html>")
    buf.add('<html lang="en">')
    buf.add("<head>")
    buf.add('  <meta charset="UTF-8">')
    buf.add('  <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    suffix = f" — {guide.scale} Scale Painting Guide" if guide.scale else " — Painting Guide"
    buf.add(f"  <title>{_t(guide.title)}{_t(suffix)}</title>")
    buf.add(f'  <link rel="stylesheet" href="{GUIDE_CSS_HREF}">')
    buf.add(f'  <link rel="stylesheet" href="{PRINT_CSS_HREF}" media="print">')
    if guide.head_style:
        buf.add(f"  <style>\n{guide.head_style}\n  </style>")
    buf.add("</head>")
    buf.add("<body>")

    buf.add('<nav class="guide-nav">\n  <a href="../../index.html">← All Guides</a>\n</nav>')

    _render_hero(buf, db, guide)

    pills = guide.paint_lines_used or []
    if pills:
        buf.add('<div class="paint-bar">')
        buf.add('<span class="paint-bar-label">Paint Lines Used</span>')
        for pill in pills:
            dot = (
                f'<span class="pill-dot" style="background:{_attr(pill["color"])};"></span>'
                if pill.get("color") else ""
            )
            buf.add(f'<span class="paint-pill">{dot}{_t(pill.get("name", ""))}</span>')
        buf.add("</div>")

    buf.add('<div class="container">')
    brief = (guide.character_brief or {}).get("philosophy")
    if brief:
        buf.add(f'<div class="char-brief">{_html(brief)}</div>')

    # Tab nav: authored tabs + the three shared skills tabs.
    buf.add('<div class="tabs">')
    for i, tab in enumerate(guide.tabs):
        cls = "tab tab-btn active" if i == 0 else "tab tab-btn"
        buf.add(
            f'<div class="{cls}" onclick="showTab(\'{_attr(_tab_dom_id(tab))}\', this)">'
            f"{_t(tab.name)}</div>"
        )
    for label, dom_id in SKILLS_TABS:
        buf.add(
            f'<div class="tab tab-btn" onclick="showTab(\'{dom_id}\', this)">{label}</div>'
        )
    buf.add("</div>")

    for i, tab in enumerate(guide.tabs):
        _render_tab(buf, tab, paints, active=(i == 0))

    # Skills tabs: injection placeholders (content built by skills-reference.js).
    for _label, dom_id in SKILLS_TABS:
        buf.add(
            f'<div class="tab-content" id="{dom_id}">\n'
            "  <!-- Content injected by skills-reference.js -->\n"
            "</div>"
        )

    buf.add("</div><!-- end .container -->")
    buf.add(_FOOTER)
    buf.add(_BACK_TO_TOP)
    buf.add(_REF_MODAL)

    buf.add(f"<script>\nwindow.GUIDE_THINNING = {_guide_thinning_js(guide.thinning_config)};\n</script>")
    buf.add(f'<script src="{GUIDE_JS_SRC}"></script>')
    buf.add(f'<script src="{SKILLS_JS_SRC}"></script>')
    buf.add(f"<script>\n{_BEHAVIOR_JS}\n</script>")

    buf.add("</body>")
    buf.add("</html>")
    return str(buf)

"""HTML importer: parse a legacy guide file into a structured GuideDraft +
an import report (spec §9.6).

The inverse of services/rendering.py — keyed on the real corpus class names.
Together they form the round-trip golden test (#261): export a stored guide,
import it back, and the structured data should match. The import report is the
schema-coverage proof (§9.7): `unmapped_nodes` is a precise to-do list of DOM
the schema doesn't model yet, and `unresolved_paints` doubles as an
inventory-gap list.

Engine: BeautifulSoup + the stdlib html.parser (matches the scrapers). Import
lands guides as **draft** for human review — never auto-published.

Paint resolution is lossy by nature (the swatch shows a display string, not an
id). A `resolve_paint(swatch_name, brand) -> paint_id | None` callback maps it
to the Paint Shelf; misses are recorded, not guessed. Unresolved swatches are
dropped from the draft (it must stay POSTable) and listed in the report.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from bs4 import BeautifulSoup, Tag
from sqlalchemy.orm import Session

from app.painting.models import Paint, PaintBrand, PaintLine

# Tabs whose bodies skills-reference.js builds at runtime — not guide data, so
# the importer skips them (mirrors the exporter emitting placeholders).
SKILLS_TAB_IDS = {"airbrush-skills", "brush-skills", "thinning-ref"}

# Fixed .phase-label dividers the exporter emits as furniture, not real phases.
_FURNITURE_LABELS = {"method selection", "step-by-step"}

PaintResolver = Callable[[str, Optional[str]], Optional[int]]


@dataclass
class ImportReport:
    resolved_paints: int = 0
    unresolved_paints: list[dict] = field(default_factory=list)  # {name, brand, step}
    unmapped_nodes: list[str] = field(default_factory=list)      # gap list (§9.7)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "resolved_paints": self.resolved_paints,
            "unresolved_paints": self.unresolved_paints,
            "unmapped_nodes": self.unmapped_nodes,
            "notes": self.notes,
        }


def make_db_resolver(db: Session) -> PaintResolver:
    """Resolve a swatch display string ('Coal Black 002' / 'P-002 Black Primer')
    to a Paint id by matching name+code in either order within the brand. The
    name/code split is lossy (spec §9.6), so we match on the combined string
    rather than guessing the boundary."""
    def resolve(swatch_name: str, brand: Optional[str]) -> Optional[int]:
        if not swatch_name:
            return None
        target = " ".join(swatch_name.split()).lower()
        q = (
            db.query(Paint.id, Paint.name, Paint.code)
            .join(PaintLine, Paint.paint_line_id == PaintLine.id)
            .join(PaintBrand, PaintLine.brand_id == PaintBrand.id)
        )
        if brand:
            q = q.filter(PaintBrand.name == brand)
        for pid, name, code in q.all():
            forms = {f"{name} {code}".lower(), f"{code} {name}".lower(), name.lower()}
            if target in forms:
                return pid
        return None
    return resolve


def _txt(node: Optional[Tag]) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _inner_html(node: Optional[Tag]) -> str:
    """Concatenated inner HTML of a node (preserves authored <strong>/<em>/<a>)."""
    if node is None:
        return ""
    return "".join(str(c) for c in node.children).strip()


def _bg_color(style: Optional[str]) -> Optional[str]:
    if not style:
        return None
    m = re.search(r"background:\s*([^;]+)", style)
    return m.group(1).strip() if m else None


def _classes(node: Tag) -> list[str]:
    c = node.get("class")
    return list(c) if c else []


# --- swatches / steps ------------------------------------------------------

_VALUE_RE = re.compile(r"~\s*(\d+)\s*%\s*value(?:\s*[—-]\s*(.*))?", re.I)


def _parse_swatch(node: Tag, resolve: PaintResolver, report: ImportReport,
                  step_title: str) -> Optional[dict]:
    name = _txt(node.select_one(".swatch-name"))
    brand = _txt(node.select_one(".swatch-brand")) or None
    value_text = _txt(node.select_one(".swatch-value"))
    value_pct: Optional[int] = None
    role: Optional[str] = None
    m = _VALUE_RE.search(value_text)
    if m:
        value_pct = int(m.group(1))
        role = (m.group(2) or "").strip() or None
    elif value_text:
        # No "~N% value" prefix — the whole string is the role label.
        role = value_text

    paint_id = resolve(name, brand)
    if paint_id is None:
        report.unresolved_paints.append({"name": name, "brand": brand, "step": step_title})
        return None
    report.resolved_paints += 1
    sw: dict = {"paint_id": paint_id}
    if value_pct is not None:
        sw["value_pct"] = value_pct
    if role:
        sw["role_label"] = role
    return sw


_STEP_NUM_RE = re.compile(r"^Step\s+\d+\s*·\s*(.*)$")


def _parse_step(node: Tag, resolve: PaintResolver, report: ImportReport) -> dict:
    title = _txt(node.select_one("h3"))
    step: dict = {"title": title}

    num = node.select_one(".step-number")
    if num is not None:
        tag_cls = [c for c in _classes(num) if c != "step-number"]
        if tag_cls:
            step["technique_tag"] = tag_cls[0]
        m = _STEP_NUM_RE.match(_txt(num))
        if m and m.group(1):
            step["technique_label"] = m.group(1)

    body = node.find("p", recursive=False)
    if body is not None:
        step["body"] = _inner_html(body)

    swatches = []
    for sw_node in node.select(".swatches > .swatch"):
        sw = _parse_swatch(sw_node, resolve, report, title)
        if sw is not None:
            swatches.append(sw)
    if swatches:
        step["swatches"] = swatches

    ratio = node.select_one(".ratio-box")
    if ratio is not None:
        step["ratio_box"] = _txt(ratio)
    tip = node.select_one(".tip")
    if tip is not None:
        step["tip"] = _inner_html(tip)
    warning = node.select_one(".warning")
    if warning is not None:
        step["warning"] = _inner_html(warning)
    return step


def _parse_phases(container: Tag, subtab_key: Optional[str],
                  resolve: PaintResolver, report: ImportReport) -> list[dict]:
    """Walk a container's children, grouping .step runs under their .phase-label."""
    phases: list[dict] = []
    current: Optional[dict] = None
    for child in container.find_all(recursive=False):
        classes = _classes(child)
        if "phase-label" in classes:
            current = {"label": _txt(child)}
            if subtab_key:
                current["subtab_key"] = subtab_key
            current["steps"] = []
            phases.append(current)
        elif "step" in classes:
            if current is None:
                current = {"label": "", "steps": []}
                if subtab_key:
                    current["subtab_key"] = subtab_key
                phases.append(current)
            current["steps"].append(_parse_step(child, resolve, report))
    return [p for p in phases if p["steps"]]


# --- tab display blocks ----------------------------------------------------

def _parse_value_map(vm: Tag, label: Optional[str]) -> dict:
    chips = []
    for chip in vm.select(".value-chip"):
        val = _txt(chip.select_one(".chip-val")).lstrip("~").rstrip("%").strip()
        chips.append({
            "hex": _bg_color(chip.select_one(".chip-swatch").get("style")
                             if chip.select_one(".chip-swatch") else None) or "",
            "value_pct": int(val) if val.isdigit() else 0,
            "zone_label": _txt(chip.select_one(".chip-label")),
        })
    out: dict = {"chips": chips}
    if label:
        out["label"] = label
    return out


def _parse_method_block(content: Tag) -> Optional[dict]:
    rec = content.select_one(".method-rec-block")
    cards_wrap = content.select_one(".method-cards")
    freckle = content.select_one(".freckle-note")
    if not (rec or cards_wrap or freckle):
        return None
    block: dict = {}
    if rec is not None:
        block["recommendation"] = _inner_html(rec)
    cards = []
    for card in (cards_wrap.select(".method-card") if cards_wrap else []):
        c: dict = {"title": _txt(card.select_one("h4"))}
        p = card.find("p")
        if p is not None:
            c["body"] = _inner_html(p)
        for key, cls in (("pros", "mc-pros"), ("cons", "mc-cons"), ("best", "mc-best")):
            el = card.select_one(f".{cls}")
            if el is not None:
                c[key] = _txt(el)
        if "recommended" in _classes(card):
            c["recommended"] = True
        badge = card.select_one(".method-card-badge")
        if badge is not None:
            c["badge"] = _txt(badge)
        cards.append(c)
    if cards:
        block["cards"] = cards
    if freckle is not None:
        block["freckle_note"] = _inner_html(freckle)
    return block


def _parse_tab(content: Tag, name: str, resolve: PaintResolver,
               report: ImportReport) -> dict:
    dom_id = content.get("id")
    tab: dict = {"name": name, "dom_id": dom_id, "phases": []}

    header = content.select_one(".section-header")
    if header is not None:
        section = {"heading": _txt(header.select_one("h2"))}
        intro = header.find("p")
        if intro is not None:
            section["intro"] = _inner_html(intro)
        tab["section"] = section

    vm = content.select_one(".value-map")
    if vm is not None:
        prev = vm.find_previous_sibling()
        label = _txt(prev) if prev and "phase-label" in _classes(prev) else None
        tab["value_map"] = _parse_value_map(vm, label)

    method = _parse_method_block(content)
    if method is not None:
        tab["method_block"] = method

    subtab_nav = content.select_one(".sub-tabs")
    if subtab_nav is not None:
        subtabs = []
        for i, st in enumerate(subtab_nav.select(".sub-tab")):
            key = _subtab_key(st, dom_id)
            extra = [c for c in _classes(st) if c not in ("sub-tab", "active")]
            sub = {"key": key, "label": _txt(st), "sort_order": i}
            if extra:
                sub["css_class"] = extra[0]
            subtabs.append(sub)
        tab["subtabs"] = subtabs
        for sc in content.select(".sub-content"):
            key = (sc.get("id") or "").removeprefix(f"{dom_id}-")
            tab["phases"].extend(_parse_phases(sc, key, resolve, report))
    else:
        tab["phases"] = _parse_phases(content, None, resolve, report)

    _record_unmapped(content, report, dom_id)
    return tab


def _subtab_key(st: Tag, dom_id: Optional[str]) -> str:
    oc = st.get("onclick") or ""
    m = re.search(r"showSubTab\('[^']*',\s*'([^']*)'", oc)
    if m and dom_id:
        return m.group(1).removeprefix(f"{dom_id}-")
    return _txt(st).lower().split()[0] if _txt(st) else ""


# Direct-child classes the tab walker handles; anything else is a coverage gap.
_KNOWN_TAB_CHILD = {
    "section-header", "phase-label", "value-map", "method-rec-block",
    "method-cards", "freckle-note", "sub-tabs", "sub-content", "step",
}


def _record_unmapped(content: Tag, report: ImportReport, dom_id: Optional[str]) -> None:
    for child in content.find_all(recursive=False):
        classes = set(_classes(child))
        if classes.isdisjoint(_KNOWN_TAB_CHILD):
            label = child.name + (f".{'.'.join(sorted(classes))}" if classes else "")
            report.unmapped_nodes.append(f"#{dom_id} > {label}")


# --- hero / header ---------------------------------------------------------

def _parse_creator_credit(node: Tag) -> Optional[dict]:
    strong = node.select_one("strong")
    a = node.select_one("a")
    if strong is None and a is None:
        return None
    credit: dict = {}
    if strong is not None:
        credit["name"] = _txt(strong)
    if a is not None:
        credit["url"] = a.get("href")
        credit["link_text"] = _txt(a)
    return credit


def _parse_thinning(soup: BeautifulSoup, report: ImportReport) -> Optional[dict]:
    script = soup.find("script", string=re.compile(r"window\.GUIDE_THINNING"))
    if script is None:
        return None
    m = re.search(r"window\.GUIDE_THINNING\s*=\s*(\{.*?\});", script.string or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        report.notes.append("GUIDE_THINNING is a JS literal (not JSON) — not imported")
        return None
    return {
        "airbrush_rows": data.get("airbrushRows") or [],
        "brush_rows": data.get("brushRows") or [],
        "thinning_cards": data.get("thinningCards") or [],
    }


def import_guide_html(html: str, *, slug: str,
                      resolve_paint: PaintResolver) -> tuple[dict, ImportReport]:
    """Parse a legacy guide HTML file into a GuideDraft dict + import report."""
    soup = BeautifulSoup(html, "html.parser")
    report = ImportReport()
    draft: dict = {"slug": slug, "status": "draft"}

    hero = soup.select_one(".hero")
    h1 = hero.select_one("h1") if hero else None
    if h1 is not None:
        draft["title"] = h1.get_text(" ", strip=True)
        span = h1.select_one("span")
        if span is not None:
            draft["title_lead"] = _txt(span)
    if hero is not None:
        if (cat := hero.select_one(".category")) is not None:
            draft["category_label"] = _txt(cat)
        if (sub := hero.select_one(".subtitle")) is not None:
            draft["subtitle"] = _txt(sub)
        if (ref := hero.select_one(".film-ref em")) is not None:
            draft["quote"] = _txt(ref).strip('"')
        if (cc := hero.select_one(".creator-credit")) is not None:
            credit = _parse_creator_credit(cc)
            if credit:
                draft["creator_credit"] = credit

    style = soup.find("style")
    if style is not None and style.string:
        draft["head_style"] = style.string.strip()

    pills = []
    for pill in soup.select(".paint-bar .paint-pill"):
        dot = pill.select_one(".pill-dot")
        color = _bg_color(dot.get("style")) if dot else None
        pills.append({"name": pill.get_text(" ", strip=True), "color": color})
    if pills:
        draft["paint_lines_used"] = pills

    brief = soup.select_one(".char-brief")
    if brief is not None:
        draft["character_brief"] = {"philosophy": _inner_html(brief)}

    thinning = _parse_thinning(soup, report)
    if thinning is not None:
        draft["thinning_config"] = thinning

    # Tab name lookup from the nav buttons (onclick showTab('id', ...)).
    names: dict[str, str] = {}
    for btn in soup.select(".tabs .tab-btn"):
        m = re.search(r"showTab\('([^']*)'", btn.get("onclick") or "")
        if m:
            names[m.group(1)] = btn.get_text(" ", strip=True)

    tabs = []
    for i, content in enumerate(soup.select(".tab-content")):
        dom_id = content.get("id") or ""
        if dom_id in SKILLS_TAB_IDS:
            continue
        tab = _parse_tab(content, names.get(dom_id, dom_id), resolve_paint, report)
        tab["sort_order"] = i
        tabs.append(tab)
    draft["tabs"] = tabs

    return draft, report

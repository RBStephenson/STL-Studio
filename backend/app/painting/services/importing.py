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
from app.painting.services.sanitize import (
    sanitize_css, sanitize_html, sanitize_url,
)

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


_TOKEN_RE = re.compile(r"[a-z0-9]+")

# US/EU spelling variants normalized so 'Warm Gray' matches shelf 'Warm Grey'.
_SPELL = ((r"\bgray\b", "grey"), (r"\bcolour", "color"))

# Common abbreviations used in guide swatch names that differ from shelf names.
# Applied after lowercasing so keys are lowercase.
_ABBREV = (
    (r"\btw\b", "titanium white"),   # 'Bold TW 001' -> 'Bold Titanium White 001'
    (r"\bfw\b", ""),                  # 'FW Crimson Ink' -> 'Crimson Ink' (brand prefix)
)

# Suffixes appended in guide names but absent from shelf paint names.
_SUFFIX_RE = re.compile(r"\s+ink\s*$")


def _canon(s: Optional[str]) -> str:
    s = (s or "").lower()
    for pat, repl in _SPELL:
        s = re.sub(pat, repl, s)
    for pat, repl in _ABBREV:
        s = re.sub(pat, repl, s)
    s = _SUFFIX_RE.sub("", s).strip()
    return s


def _tokens(s: Optional[str]) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(_canon(s)))


def _num_token(s: Optional[str]) -> Optional[str]:
    """A number to key code matching on, leading-zeros stripped: trailing first
    ('AMP-018'/'018'->'18', 'Dark Warm Flesh S08'->'8'); else the number inside a
    leading code-like token ('P-002 Black Primer'->'2', for shorthand codes the
    guide writes ahead of the name). Lets a bare guide number match a prefixed
    shelf code."""
    m = re.search(r"(\d+)\s*$", s or "")
    if not m:
        # e.g. 'P-002 Black Primer' -> the '002' in the leading code token.
        m = re.search(r"\b[A-Za-z]+-?(\d+)\b", s or "")
    if not m:
        return None
    return m.group(1).lstrip("0") or "0"


def _strip_decimal_zeros(s: str) -> str:
    """'77.720' -> '77.72', '77.700' -> '77.7', '17' -> '17'.
    Normalises trailing zeros PaintRack drops on CSV export."""
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def make_db_resolver(db: Session) -> PaintResolver:
    """Resolve a swatch display string ('Coal Black 002' / 'P-002 Black Primer')
    to a Paint id (#334). The name/code split is lossy (spec §9.6), and real
    corpus guides drift from a PaintRack-backed shelf — bare numbers vs prefixed
    codes ('Burnt Umber 018' vs code 'AMP-018'), extra descriptor words
    ('Bold Titanium White 001' vs 'Titanium White'), and brand-name drift
    ('FW Acrylic Ink' vs 'FW Inks'). So we match in layers, first *unambiguous*
    hit wins; ambiguous matches are left unresolved and reported, never guessed.

    The swatch's "brand" is matched against the paint's brand **or line** name
    (#336): a code's number restarts per line, so 'Titanium White 001' is
    ambiguous brand-wide ('Titanium White' MEA-001 in the Expert Acrylics line
    vs MWP-01 in Weathering Pigments) but unique once the swatch's 'Expert
    Acrylics' is read as the line.
    """
    rows = (
        db.query(Paint.id, Paint.name, Paint.code, PaintBrand.name, PaintLine.name)
        .join(PaintLine, Paint.paint_line_id == PaintLine.id)
        .join(PaintBrand, PaintLine.brand_id == PaintBrand.id)
        .all()
    )
    # (id, name, code, brand, line, name-tokens, code-number)
    catalog = [
        (pid, name or "", code or "", bname or "", lname or "",
         _tokens(name), _num_token(code))
        for pid, name, code, bname, lname in rows
    ]

    def _scope(brand: Optional[str]) -> list:
        """Candidates whose brand or line name equals the swatch's brand text
        (case-insensitive). None / no match -> the whole catalog."""
        if not brand:
            return catalog
        b = brand.strip().lower()
        hits = [r for r in catalog if r[3].lower() == b or r[4].lower() == b]
        return hits or catalog

    def _exact(target: str, rows_: list) -> Optional[int]:
        for pid, name, code, _b, _l, _nt, _cn in rows_:
            forms = {
                _canon(f"{name} {code}"), _canon(f"{code} {name}"), _canon(name),
            }
            if target in forms:
                return pid
        return None

    def _smart(gtokens: frozenset[str], gnum: Optional[str], rows_: list) -> Optional[int]:
        """Code-number match AND shelf-name tokens are a subset of the guide
        string's tokens. When several candidates qualify, the most specific —
        the one matching the most name tokens — wins ('Bold Titanium White'
        over generic 'Titanium White'); a tie at the top stays unresolved."""
        if not gnum:
            return None
        hits = [
            (len(ntoks), pid)
            for pid, _n, _c, _b, _l, ntoks, cnum in rows_
            if cnum == gnum and ntoks and ntoks <= gtokens
        ]
        if not hits:
            return None
        top = max(h[0] for h in hits)
        winners = [pid for n, pid in hits if n == top]
        return winners[0] if len(winners) == 1 else None

    def _by_code(ws_tokens: set, rows_: list) -> Optional[int]:
        """Match when the paint's full code appears verbatim as a token in the
        swatch string ('VMC 77.702 Duraluminium' -> code '77.702'). Pure-digit
        codes are excluded — a bare number collides with the per-line numbering
        guides use ('Burnt Umber 018'); a distinctive code (dots/letters) is a
        strong, near-unique key, so this also bridges brand drift like Vallejo
        Metal Color. Requires a unique hit.

        Trailing-zero normalisation: '77.720' in the swatch matches shelf code
        '77.72' (PaintRack strips trailing zeros on import)."""
        norm_tokens = {_strip_decimal_zeros(t) for t in ws_tokens}
        # Leading-zero normalised: swatch '065' -> '65' matches shelf code '65'
        # (PaintRack strips leading zeros on CSV import).
        stripped_tokens = {t.lstrip("0") or "0" for t in norm_tokens}
        hits = set()
        for pid, _n, code, _b, _l, _nt, _cn in rows_:
            if not code:
                continue
            cl = code.lower()
            cn = _strip_decimal_zeros(cl)
            cs = cn.lstrip("0") or "0"
            # Pure-digit codes (e.g. '065') must not match via any token path —
            # a bare number collides with per-line numbering guides use.
            # _exact and _smart still catch them when brand-scoped.
            if code.isdigit():
                continue
            if cl in ws_tokens or cn in norm_tokens or cs in stripped_tokens:
                hits.add(pid)
            elif "-" in cl:
                # 'AMP-017' -> parts ['amp','017']; match if all parts are tokens
                parts = cl.split("-")
                if all(_strip_decimal_zeros(p) in norm_tokens or p in ws_tokens
                       for p in parts):
                    hits.add(pid)
        return next(iter(hits)) if len(hits) == 1 else None

    def resolve(swatch_name: str, brand: Optional[str]) -> Optional[int]:
        if not swatch_name:
            return None
        target = _canon(" ".join(swatch_name.split()))
        gtokens, gnum = _tokens(swatch_name), _num_token(swatch_name)
        # A mix swatch ('X + Y') is two paints — leave it for mix parsing (#271)
        # rather than collapsing it onto whichever component matches first.
        is_mix = "+" in swatch_name
        ws_tokens = set(target.split())
        scoped = _scope(brand)
        # Prefer the brand/line-scoped match, then fall back to the whole
        # catalog (bridges brand drift) — each requires a unique hit.
        for rows_ in (scoped, catalog):
            pid = _exact(target, rows_)
            if pid is not None:
                return pid
            if not is_mix:
                pid = _by_code(ws_tokens, rows_)
                if pid is not None:
                    return pid
                pid = _smart(gtokens, gnum, rows_)
                if pid is not None:
                    return pid
            if rows_ is catalog:
                break
        return None

    return resolve


def _override_key(name: Optional[str], brand: Optional[str]) -> tuple[str, str]:
    """Stable identity for a user override / unresolved swatch (#443): the
    canonicalized (name, brand) pair. A brandless entry keys on '' for the brand
    slot, so it resolves independently of any same-named branded entry."""
    return (_canon(" ".join((name or "").split())), _canon(brand))


def with_overrides(
    resolver: PaintResolver, overrides: list[tuple[str, Optional[str], int]]
) -> PaintResolver:
    """Layer user-supplied resolutions on top of a base resolver (#417, #443).
    Keyed on the canonical (name, brand) identity — the same pair the importer
    passes to resolve and reports as unresolved — so two same-named paints from
    different brands map independently. A user's chosen paint_id wins before
    catalog matching. Empty overrides return the base resolver unchanged."""
    if not overrides:
        return resolver

    canon_map = {_override_key(name, brand): pid for name, brand, pid in overrides}

    def resolve(swatch_name: str, brand: Optional[str]) -> Optional[int]:
        override = canon_map.get(_override_key(swatch_name, brand))
        if override is not None:
            return override
        return resolver(swatch_name, brand)

    return resolve


def _txt(node: Optional[Tag]) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _inner_html(node: Optional[Tag]) -> str:
    """Concatenated inner HTML of a node, sanitized (#440).

    Preserves authored <strong>/<em>/<a> but strips scripts, event handlers,
    unsafe URLs, and inline styles before the value can reach the Guide
    Reader's dangerouslySetInnerHTML sinks.
    """
    if node is None:
        return ""
    raw = "".join(str(c) for c in node.children).strip()
    return sanitize_html(raw)


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


_BARE_RATIO_RE = re.compile(r"\s+\d+(?:\.\d+)?:\d+(?:\.\d+)?$")


def _mix_parts(name: str) -> list[str]:
    """Split a mix swatch name ('Burnt Sienna + Titanium White', '+ Khaki 061
    (2:1)') into component paint strings. Ratio parens and bare trailing ratios
    ('Warm Flesh 073 3:1') are stripped; a single paint returns one part."""
    cleaned = re.sub(r"\([^)]*\)", "", name)  # drop paren content like (2:1) or (S18 sub)
    parts = [p.strip() for p in cleaned.split("+") if p.strip()]
    return [_BARE_RATIO_RE.sub("", p).strip() for p in parts]


_RATIO_RE = re.compile(r"\(\s*([\d.]+(?:\s*:\s*[\d.]+)+)\s*\)\s*$")


def _mix_ratio(name: str) -> Optional[list[float]]:
    """Trailing mix ratio paren -> parts list aligned to the components, e.g.
    'A + B (3:1)' -> [3.0, 1.0]. Returns None when there's no parseable ratio
    (components then default to equal parts)."""
    m = _RATIO_RE.search(name)
    if not m:
        return None
    try:
        parts = [float(x) for x in m.group(1).split(":") if x.strip()]
    except ValueError:
        return None
    return parts or None


def _parse_swatch(node: Tag, resolve: PaintResolver, report: ImportReport,
                  step_title: str) -> tuple[list[dict], list[dict]]:
    """A swatch node -> (swatch dicts, mix-component dicts). A single paint
    yields one swatch; a mix ('A + B (3:1)') yields ordered mix components
    carrying their ratio parts (#339, Option A). Components that don't resolve
    (mediums, back-references — #415) are reported and dropped; an unresolved
    single swatch is reported and yields nothing. Mix swatches don't carry a
    value/role (the blend's value lives in the step's ratio box / body)."""
    name = _txt(node.select_one(".swatch-name"))
    brand = _txt(node.select_one(".swatch-brand")) or None
    dot = node.select_one(".swatch-dot")
    swatch_hex = _bg_color(dot.get("style")) if dot is not None else None
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

    parts = _mix_parts(name)
    if len(parts) > 1:
        ratio = _mix_ratio(name)
        mix: list[dict] = []
        for i, part in enumerate(parts):
            paint_id = resolve(part, brand)
            comp: dict = {
                "parts": ratio[i] if ratio and i < len(ratio) else 1.0,
                "sort_order": i,
            }
            if paint_id is None:
                # Keep the component by name (#425) instead of dropping it, so the
                # mix relationship + ratio still round-trip. Still reported as an
                # inventory gap.
                report.unresolved_paints.append(
                    {"name": part, "brand": brand, "step": step_title, "hex": swatch_hex}
                )
                comp["name"] = part
            else:
                report.resolved_paints += 1
                comp["paint_id"] = paint_id
            mix.append(comp)
        return [], mix

    # Single paint — resolve the cleaned part so a leading-plus continuation
    # ('+ Khaki 061 (2:1)') and trailing ratio parens are handled too.
    single = parts[0] if parts else name
    paint_id = resolve(single, brand)
    sw: dict = {}
    if paint_id is None:
        # Keep the swatch by name (#477) instead of dropping it, so it round-trips.
        # Still reported as an inventory gap.
        report.unresolved_paints.append(
            {"name": single, "brand": brand, "step": step_title, "hex": swatch_hex}
        )
        sw["name"] = single
    else:
        report.resolved_paints += 1
        sw["paint_id"] = paint_id
    if value_pct is not None:
        sw["value_pct"] = value_pct
    if role:
        sw["role_label"] = role
    return [sw], []


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

    swatches: list[dict] = []
    mix_components: list[dict] = []
    for sw_node in node.select(".swatches > .swatch"):
        sws, mix = _parse_swatch(sw_node, resolve, report, title)
        swatches.extend(sws)
        mix_components.extend(mix)
    if swatches:
        step["swatches"] = swatches
    if mix_components:
        step["mix_components"] = mix_components

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


# Direct .tab-content children that are tab-level prose, mapped to a callout
# kind. A bare <p> (intro paragraph) is handled separately by tag name.
_CALLOUT_KIND = {"tip": "tip", "warning": "warning", "warn": "warning"}


def _parse_callouts(content: Tag) -> list[dict]:
    """Tab-level prose nodes directly under .tab-content, in document order:
    intro <p> (kind 'text') + .tip/.warning/.warn callouts (#271). Nodes nested
    inside a step or sub-content are not direct children, so they are excluded."""
    out: list[dict] = []
    for child in content.find_all(recursive=False):
        classes = set(_classes(child))
        kind = next((k for cls, k in _CALLOUT_KIND.items() if cls in classes), None)
        if kind is not None:
            out.append({"kind": kind, "html": _inner_html(child)})
        elif child.name == "p" and not classes:
            out.append({"kind": "text", "html": _inner_html(child)})
    return out


def _parse_tab(content: Tag, name: str, resolve: PaintResolver,
               report: ImportReport) -> dict:
    dom_id = content.get("id")
    tab: dict = {"name": name, "dom_id": dom_id, "phases": []}

    callouts = _parse_callouts(content)
    if callouts:
        tab["callouts"] = callouts

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
        sub_by_key = {s["key"]: s for s in subtabs}
        for sc in content.select(".sub-content"):
            key = (sc.get("id") or "").removeprefix(f"{dom_id}-")
            tab["phases"].extend(_parse_phases(sc, key, resolve, report))
            # tip/warning/intro-<p> nested in a sub-content belong to that subtab,
            # not the tab — capture them so they round-trip (#271 step-1 residual).
            sub_callouts = _parse_callouts(sc)
            if sub_callouts and key in sub_by_key:
                sub_by_key[key]["callouts"] = sub_callouts
    else:
        tab["phases"] = _parse_phases(content, None, resolve, report)

    raw_blocks = _parse_raw_blocks(content)
    if raw_blocks:
        tab["raw_blocks"] = raw_blocks
    return tab


def _subtab_key(st: Tag, dom_id: Optional[str]) -> str:
    oc = st.get("onclick") or ""
    m = re.search(r"showSubTab\('[^']*',\s*'([^']*)'", oc)
    if m and dom_id:
        return m.group(1).removeprefix(f"{dom_id}-")
    return _txt(st).lower().split()[0] if _txt(st) else ""


# Direct-child classes the tab walker handles; anything else is a coverage gap.
# tip/warning/warn are captured as tab-level callouts (#271).
_KNOWN_TAB_CHILD = {
    "section-header", "phase-label", "value-map", "method-rec-block",
    "method-cards", "freckle-note", "sub-tabs", "sub-content", "step",
    "tip", "warning", "warn",
}


def _parse_raw_blocks(content: Tag) -> list[dict]:
    """Capture tab-level blocks the schema doesn't model — wargaming batch-stage /
    tier-card / trouble-grid / resin-callout, and any future unknown block —
    verbatim so they round-trip losslessly (#271; full wargaming type deferred per
    spec §6.6). Direct children that aren't known structural blocks and aren't
    bare-<p>/callouts are stored as {css_class, html} in document order.

    Trade-off: anything unrecognised now becomes an opaque block rather than a
    reported coverage gap. The export→import identity round-trip still guards the
    structured shapes; this only catches the deliberately-unmodelled extras."""
    out: list[dict] = []
    for child in content.find_all(recursive=False):
        # Bare <p> intro paragraphs are captured as 'text' callouts (#271).
        if child.name == "p":
            continue
        classes = set(_classes(child))
        if classes.isdisjoint(_KNOWN_TAB_CHILD):
            css = sorted(classes)[0] if classes else child.name
            out.append({"css_class": css, "html": sanitize_html(str(child))})
    return out


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
        url = sanitize_url(a.get("href"))
        if url is not None:
            credit["url"] = url
        credit["link_text"] = _txt(a)
    return credit


def _js_object_to_json(src: str) -> str:
    """Normalize a JS object literal into JSON (#271). The real corpus writes
    `window.GUIDE_THINNING` as a JS literal — unquoted keys, single-quoted
    strings, trailing commas — which `json.loads` rejects; our own exporter emits
    valid JSON, so this only bridges legacy input.

    A single left-to-right scan that tracks string state, so transformations never
    fire inside string contents (an apostrophe in a value, a `:` in prose):
    single-quoted strings become double-quoted (unescaping \\' , escaping "),
    bareword keys/identifiers get quoted, and trailing commas before } or ] drop.
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '"' or c == "'":
            quote = c
            buf = []
            i += 1
            while i < n and src[i] != quote:
                if src[i] == "\\" and i + 1 < n:
                    nxt = src[i + 1]
                    # \' is only meaningful in JS single-quoted strings — in JSON
                    # it's invalid, so unescape it; keep every other escape as-is.
                    buf.append(nxt if nxt == "'" else src[i] + nxt)
                    i += 2
                    continue
                buf.append('\\"' if src[i] == '"' else src[i])
                i += 1
            i += 1  # closing quote
            out.append('"' + "".join(buf) + '"')
        elif c.isalpha() or c == "_" or c == "$":
            # A bareword: an unquoted key, or a literal (true/false/null). Quote it
            # unless it's a JSON keyword, leaving numbers/structure untouched.
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            word = src[i:j]
            out.append(word if word in ("true", "false", "null") else '"' + word + '"')
            i = j
        elif c in ",":
            # Drop a trailing comma (next non-space is a closer).
            k = i + 1
            while k < n and src[k].isspace():
                k += 1
            if k < n and src[k] in "}]":
                i += 1  # skip the comma
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_series_badge(hero: Tag) -> list[dict]:
    """The hero .series-badge chips, in document order (#271): the active chip is
    a <span class="active"> (current guide, no link); sibling chips are <a> links
    carrying the legacy filename. Captured verbatim so cross-links round-trip."""
    badge = hero.select_one(".series-badge")
    if badge is None:
        return []
    chips: list[dict] = []
    for el in badge.find_all(["a", "span"], recursive=False):
        label = _txt(el)
        if not label:
            continue
        if el.name == "a":
            # Sanitize the href like creator-credit (#440): a relative sibling
            # filename passes; a javascript:/data: href is dropped to a link-less
            # chip so it can never reach the exporter's <a> sink.
            chips.append({"label": label, "filename": sanitize_url(el.get("href")), "active": False})
        else:
            chips.append({"label": label, "active": "active" in _classes(el)})
    return chips


def _parse_thinning(soup: BeautifulSoup, report: ImportReport) -> Optional[dict]:
    script = soup.find("script", string=re.compile(r"window\.GUIDE_THINNING"))
    if script is None:
        return None
    m = re.search(r"window\.GUIDE_THINNING\s*=\s*(\{.*?\});", script.string or "", re.S)
    if not m:
        return None
    raw = m.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Real corpus form is a JS object literal (unquoted keys, single quotes) —
        # normalize and retry before giving up (#271).
        try:
            data = json.loads(_js_object_to_json(raw))
        except (json.JSONDecodeError, ValueError):
            report.notes.append("GUIDE_THINNING couldn't be parsed as JSON or a JS literal — not imported")
            return None
    if not isinstance(data, dict):
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
        badge = _parse_series_badge(hero)
        if badge:
            draft["series_badge"] = badge

    style = soup.find("style")
    if style is not None and style.string:
        head_style = sanitize_css(style.string.strip())
        if head_style:
            draft["head_style"] = head_style

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

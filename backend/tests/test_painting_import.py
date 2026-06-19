"""HTML importer + round-trip golden test (M2, #261).

Two complementary proofs (spec §9.6/§9.7):
- **export → import identity** on a synthetic guide: the exporter (#260) and
  importer are inverses over the schema's domain, so a guide survives the round
  trip. This is the renderer's acceptance test.
- **import over a real corpus guide**: the parser handles the real DOM and
  produces an import report — `unresolved_paints` is the inventory-gap list and
  `unmapped_nodes` the schema-coverage gap list.
"""
from pathlib import Path

import pytest

from bs4 import BeautifulSoup

from app.painting.services.importing import (
    ImportReport, _parse_swatch, import_guide_html, make_db_resolver,
)
from tests.test_painting_guides import mk_paint
from tests.test_painting_guide_schema import presto_body

CORPUS = Path(__file__).resolve().parents[2] / "painting-guides" / "by-category"
PRESTO = CORPUS / "dnd-animated-series" / "presto-magician-dnd-painting-guide.html"


@pytest.fixture
def paint(client):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    line = client.post(
        "/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}
    ).json()
    return mk_paint(client, line["id"])


# ---------------------------------------------------------------------------
# export -> import identity round-trip (the acceptance test)
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def _round_trip(self, client, paint):
        g1 = client.post("/painting/guides", json=presto_body(paint["id"])).json()
        html = client.get(f"/painting/guides/{g1['id']}/export").text
        r = client.post(
            "/painting/guides/import", json={"html": html, "slug": "presto-reimport"}
        )
        assert r.status_code == 201, r.text
        return g1, r.json()

    def test_clean_round_trip_report(self, client, paint):
        _, result = self._round_trip(client, paint)
        report = result["report"]
        # Our own output is fully covered by the schema and fully resolvable.
        assert report["unresolved_paints"] == []
        assert report["unmapped_nodes"] == []

    def test_header_survives(self, client, paint):
        _, result = self._round_trip(client, paint)
        g2 = result["guide"]
        assert g2["title"] == "Presto the Magician"
        assert g2["title_lead"] == "Presto"
        assert g2["subtitle"].startswith("1:6 Scale")
        assert g2["category_label"] == "D&D Animated Series · 1983 Cartoon"
        assert g2["quote"] == "Magic hat, don't fail me now!"
        assert g2["creator_credit"]["link_text"] == "@_toonstudio"
        assert g2["paint_lines_used"][0] == {"name": "Pro Acryl", "color": "#cc4444"}

    def test_tab_structure_survives(self, client, paint):
        _, result = self._round_trip(client, paint)
        tab = result["guide"]["tabs"][0]
        assert tab["dom_id"] == "skin"
        assert tab["section"]["heading"] == "Skin"
        assert "<em>ginger freckling</em>" in tab["section"]["intro"]
        assert tab["value_map"]["label"] == "Value Structure"
        assert [s["key"] for s in tab["subtabs"]] == ["pro", "expert"]

    def test_method_block_survives(self, client, paint):
        _, result = self._round_trip(client, paint)
        mb = result["guide"]["tabs"][0]["method_block"]
        assert mb["cards"][1]["recommended"] is True
        assert mb["cards"][1]["badge"] == "★ Recommended"
        assert mb["cards"][0]["pros"] == "Predictable"
        assert mb["freckle_note"].startswith("<strong>Freckling")

    def test_steps_and_swatches_survive(self, client, paint):
        _, result = self._round_trip(client, paint)
        phases = result["guide"]["tabs"][0]["phases"]
        assert {p["subtab_key"] for p in phases} == {"pro", "expert"}
        pro = next(p for p in phases if p["subtab_key"] == "pro")["steps"][0]
        assert pro["technique_tag"] == "airbrush"
        assert pro["technique_label"] == "Airbrush"
        assert pro["swatches"][0]["paint_id"] == paint["id"]
        assert pro["swatches"][0]["value_pct"] == 5
        assert pro["swatches"][0]["role_label"] == "black prime"
        # role-only swatch (no value pct) survives too
        expert = next(p for p in phases if p["subtab_key"] == "expert")["steps"][0]
        assert expert["swatches"][0]["role_label"] == "shadow"

    def test_inline_html_survives(self, client, paint):
        _, result = self._round_trip(client, paint)
        step = next(
            p for p in result["guide"]["tabs"][0]["phases"] if p["subtab_key"] == "pro"
        )["steps"][0]
        assert step["warning"] == "<strong>⚠ NOTE:</strong> Never thin primer."

    def test_subtab_callouts_survive(self, client, paint):
        # Sub-content-level callouts round-trip on their own subtab (#271 residual).
        _, result = self._round_trip(client, paint)
        expert = next(
            s for s in result["guide"]["tabs"][0]["subtabs"] if s["key"] == "expert"
        )
        assert [c["kind"] for c in expert["callouts"]] == ["tip"]
        assert expert["callouts"][0]["html"].startswith("<strong>✦ TIP:</strong>")
        # the "pro" subtab carries no callouts
        pro = next(s for s in result["guide"]["tabs"][0]["subtabs"] if s["key"] == "pro")
        assert pro.get("callouts", []) == []

    def test_raw_blocks_survive(self, client, paint):
        # Unmodelled tab blocks (#271 step 2) round-trip verbatim.
        _, result = self._round_trip(client, paint)
        blocks = result["guide"]["tabs"][0]["raw_blocks"]
        assert [b["css_class"] for b in blocks] == ["tier-card"]
        assert "Display" in blocks[0]["html"]

    def test_tab_callouts_survive(self, client, paint):
        # Tab-level intro <p> + tip/warning round-trip (#271): captured in
        # document order, regrouped text-above / tip-warning-below by the exporter.
        _, result = self._round_trip(client, paint)
        callouts = result["guide"]["tabs"][0]["callouts"]
        assert [c["kind"] for c in callouts] == ["text", "tip", "warning"]
        assert "<em>largest</em>" in callouts[0]["html"]
        assert callouts[1]["html"].startswith("<strong>✦ TIP:</strong>")


class TestUnlabeledPhase:
    """A run of steps with no .phase-label divider is a legitimate unlabeled
    phase the importer produces (`label: ""`). It must survive create, not 422
    on the schema's old min_length=1 constraint — the cause of the import 500."""

    def test_create_accepts_empty_phase_label(self, client, paint):
        body = presto_body(paint["id"])
        body["tabs"][0]["phases"][0]["label"] = ""
        r = client.post("/painting/guides", json=body)
        assert r.status_code == 201, r.text
        assert r.json()["tabs"][0]["phases"][0]["label"] == ""

    def test_export_omits_empty_phase_divider(self, client, paint):
        body = presto_body(paint["id"])
        body["tabs"][0]["phases"][0]["label"] = ""
        gid = client.post("/painting/guides", json=body).json()["id"]
        html = client.get(f"/painting/guides/{gid}/export").text
        # No blank divider bar left behind for the unlabeled phase.
        assert '<div class="phase-label"></div>' not in html


class TestImportEndpoint:
    def test_unresolved_swatch_dropped_and_reported(self, client):
        # Export a guide, then rewrite a swatch name to one not on the shelf:
        # the draft drops it and the report lists it, but the guide still imports.
        brand = client.post("/painting/brands", json={"name": "X"}).json()
        line = client.post(
            "/painting/lines", json={"brand_id": brand["id"], "name": "L"}
        ).json()
        p = mk_paint(client, line["id"], code="Z9", name="Ghost")
        g = client.post("/painting/guides", json=presto_body(p["id"])).json()
        html = client.get(f"/painting/guides/{g['id']}/export").text
        html = html.replace("Ghost Z9", "Nonexistent Paint NX1")
        r = client.post("/painting/guides/import", json={"html": html, "slug": "imp"})
        assert r.status_code == 201, r.text
        assert r.json()["report"]["unresolved_paints"]


class TestSmartResolver:
    """Swatch->paint resolution against a PaintRack-style shelf (#334): bare
    guide numbers vs prefixed codes, descriptor words, brand drift — first
    unambiguous match wins, ambiguous stays unresolved."""

    @pytest.fixture
    def line_id(self, client):
        brand = client.post("/painting/brands", json={"name": "Pro Acryl"}).json()
        return client.post(
            "/painting/lines", json={"brand_id": brand["id"], "name": "AMP"}
        ).json()["id"]

    def test_exact_combined_string_still_wins(self, client, db, line_id):
        p = mk_paint(client, line_id, code="002", name="Coal Black")
        assert make_db_resolver(db)("Coal Black 002", "Pro Acryl") == p["id"]

    def test_bare_number_matches_prefixed_code(self, client, db, line_id):
        p = mk_paint(client, line_id, code="AMP-018", name="Burnt Umber")
        assert make_db_resolver(db)("Burnt Umber 018", "Pro Acryl") == p["id"]

    def test_descriptor_words_in_guide_name(self, client, db, line_id):
        p = mk_paint(client, line_id, code="MEA-001", name="Titanium White")
        assert make_db_resolver(db)("Bold Titanium White 001", "Pro Acryl") == p["id"]

    def test_specificity_breaks_ties(self, client, db, line_id):
        mk_paint(client, line_id, code="MEA-001", name="Titanium White")
        specific = mk_paint(client, line_id, code="MPA-001", name="Bold Titanium White")
        # both fit, but the longer name-token match is the more specific paint
        assert make_db_resolver(db)("Bold Titanium White 001", "Pro Acryl") == specific["id"]

    def test_unbreakable_tie_left_unresolved(self, client, db, line_id):
        mk_paint(client, line_id, code="A-001", name="Red")
        mk_paint(client, line_id, code="B-001", name="Blue")
        assert make_db_resolver(db)("Red Blue 001", "Pro Acryl") is None

    def test_line_name_disambiguates_same_name_number(self, client, db):
        # A code's number restarts per line, so 'Titanium White 001' exists in
        # two lines of one brand. The swatch's brand text names the LINE (#336).
        brand = client.post("/painting/brands", json={"name": "Pro Acryl"}).json()
        ea = client.post(
            "/painting/lines", json={"brand_id": brand["id"], "name": "Expert Acrylics"}
        ).json()
        wp = client.post(
            "/painting/lines", json={"brand_id": brand["id"], "name": "Weathering Pigments"}
        ).json()
        expert = mk_paint(client, ea["id"], code="MEA-001", name="Titanium White")
        mk_paint(client, wp["id"], code="MWP-01", name="Titanium White")
        resolve = make_db_resolver(db)
        assert resolve("Titanium White 001", "Expert Acrylics") == expert["id"]
        # brand-wide it's genuinely ambiguous -> left unresolved
        assert resolve("Titanium White 001", "Pro Acryl") is None

    def test_full_code_in_swatch_string_resolves(self, client, db):
        # 'VMC 77.702 Duraluminium' carries the exact code mid-string, with brand
        # drift ('Vallejo Metal Color' vs brand Vallejo / line Metal Color) (#336).
        v = client.post("/painting/brands", json={"name": "Vallejo"}).json()
        mc = client.post(
            "/painting/lines", json={"brand_id": v["id"], "name": "Metal Color"}
        ).json()
        ma = client.post(
            "/painting/lines", json={"brand_id": v["id"], "name": "Model Air"}
        ).json()
        dura = mk_paint(client, mc["id"], code="77.702", name="Duraluminium")
        mk_paint(client, ma["id"], code="71.062", name="Aluminium")  # decoy
        assert make_db_resolver(db)(
            "VMC 77.702 Duraluminium", "Vallejo Metal Color"
        ) == dura["id"]

    def test_pure_numeric_code_not_matched_by_token(self, client, db):
        # A bare-number code must not match a guide's per-line number token
        # ('065' the FW code vs '065' written in some other brand's swatch).
        fw = client.post("/painting/brands", json={"name": "FW Inks"}).json()
        line = client.post(
            "/painting/lines", json={"brand_id": fw["id"], "name": "Acrylic"}
        ).json()
        mk_paint(client, line["id"], code="065", name="Payne's Grey")
        assert make_db_resolver(db)("Mystery Colour 065", "Some Other Brand") is None

    def test_mix_swatch_left_unresolved(self, client, db, line_id):
        # 'Satin Black S39 + gloss medium' is a mix; don't collapse it onto the
        # S39 component just because the code token matches (#271 mix parsing).
        mk_paint(client, line_id, code="S39", name="Satin Black")
        assert make_db_resolver(db)("Satin Black S39 + gloss medium", "Pro Acryl") is None

    def test_us_eu_spelling_normalized(self, client, db, line_id):
        # guide 'Gray' (US) matches shelf 'Grey' (EU)
        p = mk_paint(client, line_id, code="074", name="Warm Grey")
        assert make_db_resolver(db)("Warm Gray 074", "Pro Acryl") == p["id"]

    def test_primer_code_shorthand(self, client, db):
        brand = client.post("/painting/brands", json={"name": "Pro Acryl"}).json()
        line = client.post(
            "/painting/lines", json={"brand_id": brand["id"], "name": "PRIME"}
        ).json()
        p = mk_paint(client, line["id"], code="MPAP-002", name="Black")
        # guide writes the shorthand 'P-002'; number inside the leading code token
        assert make_db_resolver(db)("P-002 Black Primer", "Pro Acryl") == p["id"]

    def test_brand_agnostic_fallback_for_brand_drift(self, client, db):
        brand = client.post("/painting/brands", json={"name": "FW Inks"}).json()
        line = client.post(
            "/painting/lines", json={"brand_id": brand["id"], "name": "Ink"}
        ).json()
        p = mk_paint(client, line["id"], code="513", name="FW Crimson Ink")
        # guide says "FW Acrylic Ink"; no brand match, but a unique global hit
        assert make_db_resolver(db)("FW Crimson Ink 513", "FW Acrylic Ink") == p["id"]

    def test_no_number_no_smart_match(self, client, db, line_id):
        mk_paint(client, line_id, code="AMP-018", name="Burnt Umber")
        # no exact hit and no number token -> the heuristic must not guess
        assert make_db_resolver(db)("Burnt Umber Deep", "Pro Acryl") is None


class TestMixExpansion:
    """A mix swatch ('A + B') expands into one swatch per resolvable component
    (#336 Option A); non-paint components (mediums, back-refs) drop + report."""

    def _swatch(self, name, value="~40% value — base", brand="Pro Acryl"):
        html = (f'<div class="swatch"><div class="swatch-name">{name}</div>'
                f'<div class="swatch-brand">{brand}</div>'
                f'<div class="swatch-value">{value}</div></div>')
        return BeautifulSoup(html, "html.parser").select_one(".swatch")

    def test_mix_expands_to_each_component(self):
        resolve = lambda n, b: {"coal black": 1, "warm grey": 2}.get(n.lower())
        rep = ImportReport()
        out = _parse_swatch(self._swatch("Coal Black + Warm Grey"), resolve, rep, "S")
        assert [s["paint_id"] for s in out] == [1, 2]
        assert all(s["value_pct"] == 40 for s in out)  # shared value
        assert rep.resolved_paints == 2

    def test_non_paint_component_dropped_and_reported(self):
        resolve = lambda n, b: {"satin black s39": 5}.get(n.lower())
        rep = ImportReport()
        out = _parse_swatch(
            self._swatch("Satin Black S39 + gloss medium"), resolve, rep, "S")
        assert [s["paint_id"] for s in out] == [5]
        assert any(u["name"] == "gloss medium" for u in rep.unresolved_paints)

    def test_leading_plus_and_ratio_stripped(self):
        resolve = lambda n, b: 7 if n.lower() == "khaki 061" else None
        rep = ImportReport()
        out = _parse_swatch(self._swatch("+ Khaki 061 (2:1)"), resolve, rep, "S")
        assert [s["paint_id"] for s in out] == [7]


# ---------------------------------------------------------------------------
# tab-level callouts (#271): captured, not reported as coverage gaps
# ---------------------------------------------------------------------------

class TestTabCallouts:
    HTML = """
    <div class="tabs">
      <div class="tab-btn" onclick="showTab('skin', this)">Skin</div>
    </div>
    <div class="tab-content" id="skin">
      <div class="section-header"><h2>Skin</h2><p>nested intro</p></div>
      <p>Intro <em>paragraph</em> for the tab.</p>
      <div class="step"><h3>Base</h3><p>do the thing</p></div>
      <div class="tip"><strong>✦ TIP:</strong> work both eyes.</div>
      <div class="warn">old-style warn.</div>
      <div class="warning">⚠ careful.</div>
    </div>
    """

    def _parse(self):
        return import_guide_html(self.HTML, slug="t", resolve_paint=lambda n, b: None)

    def test_callouts_captured_in_order(self):
        draft, _ = self._parse()
        callouts = draft["tabs"][0]["callouts"]
        assert [c["kind"] for c in callouts] == ["text", "tip", "warning", "warning"]
        assert callouts[0]["html"] == "Intro <em>paragraph</em> for the tab."
        assert callouts[1]["html"].startswith("<strong>✦ TIP:</strong>")

    def test_callouts_not_reported_unmapped(self):
        _, report = self._parse()
        assert report.unmapped_nodes == []

    def test_section_header_p_not_captured_as_callout(self):
        # the <p> inside .section-header is the section intro, not a tab callout
        draft, _ = self._parse()
        htmls = [c["html"] for c in draft["tabs"][0]["callouts"]]
        assert "nested intro" not in htmls


# ---------------------------------------------------------------------------
# sub-content callouts (#271 residual): callouts nested in a sub-tabbed
# .sub-content attach to that subtab, not the tab, and aren't coverage gaps
# ---------------------------------------------------------------------------

class TestSubContentCallouts:
    HTML = """
    <div class="tabs">
      <div class="tab-btn" onclick="showTab('skin', this)">Skin</div>
    </div>
    <div class="tab-content" id="skin">
      <div class="sub-tabs">
        <div class="sub-tab" onclick="showSubTab('skin', 'skin-pro', this)">Pro</div>
        <div class="sub-tab expert-tab" onclick="showSubTab('skin', 'skin-expert', this)">Expert</div>
      </div>
      <div class="sub-content" id="skin-pro">
        <div class="step"><h3>Base</h3><p>pro base</p></div>
      </div>
      <div class="sub-content" id="skin-expert">
        <p>Expert <em>intro</em>.</p>
        <div class="step"><h3>Base</h3><p>expert base</p></div>
        <div class="tip"><strong>✦ TIP:</strong> dries matte.</div>
      </div>
    </div>
    """

    def _parse(self):
        return import_guide_html(self.HTML, slug="t", resolve_paint=lambda n, b: None)

    def test_callouts_attached_to_their_subtab(self):
        draft, _ = self._parse()
        subs = {s["key"]: s for s in draft["tabs"][0]["subtabs"]}
        assert [c["kind"] for c in subs["expert"]["callouts"]] == ["text", "tip"]
        assert subs["expert"]["callouts"][0]["html"] == "Expert <em>intro</em>."
        # the pro subtab has no callouts
        assert subs["pro"].get("callouts", []) == []

    def test_subcontent_callouts_not_reported_unmapped(self):
        _, report = self._parse()
        assert report.unmapped_nodes == []


# ---------------------------------------------------------------------------
# raw blocks (#271 step 2): unmodelled tab blocks (wargaming batch-stage /
# tier-card / etc.) captured verbatim, not reported as coverage gaps
# ---------------------------------------------------------------------------

class TestRawBlocks:
    HTML = """
    <div class="tabs">
      <div class="tab-btn" onclick="showTab('build', this)">Build</div>
    </div>
    <div class="tab-content" id="build">
      <div class="section-header"><h2>Build</h2></div>
      <div class="tier-card"><span class="tier-badge">Tier 1</span><h3>Tabletop</h3></div>
      <div class="batch-stage"><div class="batch-num">1</div>
        <div class="batch-stage-body"><strong>Prime all 5</strong></div></div>
    </div>
    """

    def _parse(self):
        return import_guide_html(self.HTML, slug="t", resolve_paint=lambda n, b: None)

    def test_unmodelled_blocks_captured_verbatim(self):
        draft, _ = self._parse()
        blocks = draft["tabs"][0]["raw_blocks"]
        assert [b["css_class"] for b in blocks] == ["tier-card", "batch-stage"]
        assert "Tabletop" in blocks[0]["html"]
        assert '<div class="batch-num">1</div>' in blocks[1]["html"]

    def test_raw_blocks_not_reported_unmapped(self):
        _, report = self._parse()
        assert report.unmapped_nodes == []


# ---------------------------------------------------------------------------
# real corpus parse + import report (schema-coverage / inventory gap lists)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PRESTO.exists(), reason="corpus fixture not present")
class TestRealCorpus:
    def _parse(self):
        html = PRESTO.read_text(encoding="utf-8")
        # No shelf -> every real paint is an inventory gap.
        return import_guide_html(html, slug="presto", resolve_paint=lambda n, b: None)

    def test_parses_hero_without_crashing(self):
        draft, _ = self._parse()
        assert draft["title"] == "Presto the Magician"
        assert draft["title_lead"] == "Presto"
        assert draft["category_label"].startswith("D&D Animated Series")
        assert draft["quote"] == "Magic hat, don't fail me now!"
        assert draft["creator_credit"]["name"] == "Toon Studios"

    def test_data_tabs_extracted_skills_skipped(self):
        draft, _ = self._parse()
        dom_ids = [t["dom_id"] for t in draft["tabs"]]
        assert "skin" in dom_ids and "robe" in dom_ids and "metals" in dom_ids
        # the runtime-injected skills tabs are not guide data
        assert "airbrush-skills" not in dom_ids
        assert "thinning-ref" not in dom_ids

    def test_report_lists_inventory_gaps(self):
        _, report = self._parse()
        # real paints aren't in the (empty) shelf -> all unresolved
        assert report.resolved_paints == 0
        assert len(report.unresolved_paints) > 0
        # unmapped_nodes is the schema-coverage to-do list (may be non-empty)
        assert isinstance(report.unmapped_nodes, list)


@pytest.mark.skipif(not CORPUS.exists(), reason="corpus fixture not present")
def test_tab_level_callouts_gone_from_corpus_unmapped():
    """#271 step 1: across all 40 corpus guides, tab-level tip/warning/warn and
    stray intro <p> are now captured, so they no longer appear in any guide's
    unmapped_nodes (the remaining gaps are wargaming furniture)."""
    closed = (" > div.tip", " > div.warning", " > div.warn", " > p")
    leftover = []
    for path in CORPUS.rglob("*.html"):
        _, report = import_guide_html(
            path.read_text(encoding="utf-8"), slug=path.stem,
            resolve_paint=lambda n, b: None,
        )
        leftover += [n for n in report.unmapped_nodes if n.endswith(closed)]
    assert leftover == []

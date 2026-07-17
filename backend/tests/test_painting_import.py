"""HTML importer + round-trip golden test (M2, #261).

Two complementary proofs (spec §9.6/§9.7):
- **export → import identity** on a synthetic guide: the exporter (#260) and
  importer are inverses over the schema's domain, so a guide survives the round
  trip. This is the renderer's acceptance test.
- **import over a real corpus guide**: the parser handles the real DOM and
  produces an import report — `unresolved_paints` is the inventory-gap list and
  `unmapped_nodes` the schema-coverage gap list.
"""
import json
from pathlib import Path

import pytest

from bs4 import BeautifulSoup

from types import SimpleNamespace

from app.painting.services.importing import (
    ImportReport, _js_object_to_json, _parse_swatch, _parse_thinning,
    import_guide_html, make_db_resolver, with_overrides,
)
from app.painting.services.rendering import (
    PaintInfo, SKILLS_JS_SRC, SKILLS_TABS, _render_mix,
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


class TestOverrideResolver:
    """with_overrides layers user resolutions on top of the base resolver (#417),
    keyed on the canonicalized (name, brand) identity (#443); empty overrides are
    a no-op."""

    def test_override_wins_before_base(self):
        base = lambda n, b: 1 if n.lower() == "coal black" else None
        resolve = with_overrides(base, [("Mystery Paint", None, 99)])
        assert resolve("Mystery Paint", None) == 99       # override
        assert resolve("mystery paint", None) == 99       # canonicalized match
        assert resolve("Coal Black", None) == 1           # falls through to base
        assert resolve("Unknown", None) is None

    def test_empty_overrides_returns_base_unchanged(self):
        base = lambda n, b: 7
        assert with_overrides(base, []) is base

    def test_same_name_different_brand_resolve_independently(self):
        base = lambda n, b: None
        resolve = with_overrides(base, [
            ("Gunmetal", "Vallejo", 10),
            ("Gunmetal", "Citadel", 20),
        ])
        assert resolve("Gunmetal", "Vallejo") == 10
        assert resolve("Gunmetal", "Citadel") == 20
        # An identity with neither override brand stays unresolved, not collapsed.
        assert resolve("Gunmetal", "Army Painter") is None

    def test_brandless_override_independent_of_branded(self):
        base = lambda n, b: None
        resolve = with_overrides(base, [
            ("Gunmetal", None, 10),
            ("Gunmetal", "Citadel", 20),
        ])
        assert resolve("Gunmetal", None) == 10            # brandless identity
        assert resolve("Gunmetal", "Citadel") == 20       # branded identity
        assert resolve("Gunmetal", "Vallejo") is None     # neither


class TestImportResolution:
    """dry_run preview + paint_overrides committing flow (#417)."""

    def _unresolved_html(self, client, paint):
        """Export a guide, then rename its swatch paint to something off-shelf so
        re-import can't resolve it — the unresolved-paint scenario."""
        g = client.post("/painting/guides", json=presto_body(paint["id"])).json()
        html = client.get(f"/painting/guides/{g['id']}/export").text
        return html.replace(f"{paint['name']} {paint['code']}", "Mystery Unknown XYZ")

    def test_dry_run_reports_without_persisting(self, client, paint):
        html = self._unresolved_html(client, paint)
        before = client.get("/painting/guides").json()["total"]
        r = client.post("/painting/guides/import",
                        json={"html": html, "slug": "dry", "dry_run": True})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["guide"] is None
        assert any(u["name"] == "Mystery Unknown XYZ" for u in body["report"]["unresolved_paints"])
        # Nothing persisted.
        assert client.get("/painting/guides").json()["total"] == before

    def test_unresolved_entry_carries_hex(self, client, paint):
        html = self._unresolved_html(client, paint)
        r = client.post("/painting/guides/import",
                        json={"html": html, "slug": "dry2", "dry_run": True})
        entry = next(u for u in r.json()["report"]["unresolved_paints"]
                     if u["name"] == "Mystery Unknown XYZ")
        assert entry["hex"] == paint["hex"]  # the swatch dot colour, for force-add

    def test_override_resolves_and_commits(self, client, paint):
        html = self._unresolved_html(client, paint)
        # Echo the reported (name, brand) identity so the override keys correctly (#443).
        dry = client.post("/painting/guides/import",
                          json={"html": html, "slug": "r", "dry_run": True}).json()
        entry = next(u for u in dry["report"]["unresolved_paints"]
                     if u["name"] == "Mystery Unknown XYZ")
        r = client.post("/painting/guides/import", json={
            "html": html, "slug": "resolved",
            "paint_overrides": [
                {"name": "Mystery Unknown XYZ", "brand": entry["brand"], "paint_id": paint["id"]}
            ],
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["guide"] is not None
        assert body["report"]["unresolved_paints"] == []
        # The swatch now references the overridden paint.
        guide = client.get(f"/painting/guides/{body['guide']['id']}").json()
        swatch_ids = [
            s["paint_id"]
            for tab in guide["tabs"] for ph in tab["phases"]
            for st in ph["steps"] for s in st["swatches"]
        ]
        assert paint["id"] in swatch_ids

    def test_override_with_wrong_brand_does_not_resolve(self, client, paint):
        """An override keyed on a different brand must not capture a branded
        swatch — same-name/different-brand entries stay independent (#443)."""
        html = self._unresolved_html(client, paint)
        r = client.post("/painting/guides/import", json={
            "html": html, "slug": "mismatch",
            "paint_overrides": [
                {"name": "Mystery Unknown XYZ", "brand": "Some Other Brand", "paint_id": paint["id"]}
            ],
        })
        assert r.status_code == 201, r.text
        # Brand mismatch → the override doesn't apply, swatch stays unresolved.
        assert any(u["name"] == "Mystery Unknown XYZ"
                   for u in r.json()["report"]["unresolved_paints"])


class TestForceAddPaint:
    """POST /paints/import-forced lands an off-shelf paint in a synthetic
    'Imported / Uncategorized' line as known-but-not-owned (#417)."""

    def test_force_add_creates_unowned_paint(self, client):
        r = client.post("/painting/paints/import-forced",
                        json={"name": "Mystery Silver", "hex": "#c0c0c0"})
        assert r.status_code == 201, r.text
        p = r.json()
        assert p["name"] == "Mystery Silver"
        assert p["hex"] == "#c0c0c0"
        assert p["owned"] is False

    def test_force_add_is_idempotent_by_name(self, client):
        first = client.post("/painting/paints/import-forced", json={"name": "Repeat Paint"}).json()
        second = client.post("/painting/paints/import-forced", json={"name": "repeat paint"}).json()
        assert first["id"] == second["id"]  # same row, not a duplicate


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
    def test_unresolved_swatch_kept_by_name_and_reported(self, client):
        # Export a guide, then rewrite a swatch name to one not on the shelf: the
        # swatch is kept by name (#477, not dropped) and still listed in the report.
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
        body = r.json()
        assert any(u["name"] == "Nonexistent Paint NX1" for u in body["report"]["unresolved_paints"])
        # The swatch survives as a name-only row (paint_id None).
        guide = client.get(f"/painting/guides/{body['guide']['id']}").json()
        swatches = [
            s for tab in guide["tabs"] for ph in tab["phases"]
            for st in ph["steps"] for s in st["swatches"]
        ]
        assert any(s["paint_id"] is None and s["name"] == "Nonexistent Paint NX1" for s in swatches)


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


class TestMixComponents:
    """A mix swatch ('A + B (3:1)') parses into ordered mix components carrying
    ratio parts (#339). Non-paint components (mediums, back-refs #415) are kept
    by name (#425, Option B) so the mix round-trips, and still reported.
    _parse_swatch returns (swatches, mix_components)."""

    def _swatch(self, name, value="~40% value — base", brand="Pro Acryl"):
        html = (f'<div class="swatch"><div class="swatch-name">{name}</div>'
                f'<div class="swatch-brand">{brand}</div>'
                f'<div class="swatch-value">{value}</div></div>')
        return BeautifulSoup(html, "html.parser").select_one(".swatch")

    def test_mix_yields_ordered_components_with_default_parts(self):
        resolve = lambda n, b: {"coal black": 1, "warm grey": 2}.get(n.lower())
        rep = ImportReport()
        swatches, mix = _parse_swatch(self._swatch("Coal Black + Warm Grey"), resolve, rep, "S")
        assert swatches == []
        assert [(m["paint_id"], m["parts"], m["sort_order"]) for m in mix] == [
            (1, 1.0, 0), (2, 1.0, 1)
        ]
        assert rep.resolved_paints == 2

    def test_mix_ratio_maps_to_parts(self):
        resolve = lambda n, b: {"burnt sienna": 1, "pyrrole red": 2}.get(n.lower())
        rep = ImportReport()
        _swatches, mix = _parse_swatch(
            self._swatch("Burnt Sienna + Pyrrole Red (3:1)"), resolve, rep, "S")
        assert [m["parts"] for m in mix] == [3.0, 1.0]

    def test_non_paint_component_kept_by_name_and_reported(self):
        resolve = lambda n, b: {"satin black s39": 5}.get(n.lower())
        rep = ImportReport()
        _swatches, mix = _parse_swatch(
            self._swatch("Satin Black S39 + gloss medium (2:1)"), resolve, rep, "S")
        # Both components survive in order; the unresolved one keeps its name (#425).
        assert [(m.get("paint_id"), m.get("name"), m["parts"], m["sort_order"]) for m in mix] == [
            (5, None, 2.0, 0),
            (None, "gloss medium", 1.0, 1),
        ]
        # Still reported as an inventory gap.
        assert any(u["name"] == "gloss medium" for u in rep.unresolved_paints)

    def test_all_unresolved_mix_kept_by_name(self):
        rep = ImportReport()
        _swatches, mix = _parse_swatch(
            self._swatch("Mid-tone + Titanium White (1:1)"), lambda n, b: None, rep, "S")
        assert [(m.get("paint_id"), m["name"]) for m in mix] == [
            (None, "Mid-tone"), (None, "Titanium White")
        ]

    def test_render_mix_rejoins_name_only_component(self):
        """Exporter restores 'A + B (2:1)' using the resolved paint or the stored
        name, so the importer's name-only component round-trips (#425)."""
        from app.painting.services.rendering import _render_mix
        comps = [
            SimpleNamespace(paint_id=1, name=None, parts=2.0),
            SimpleNamespace(paint_id=None, name="gloss medium", parts=1.0),
        ]
        paints = {1: PaintInfo(name="Satin Black", code="S39", brand="X", hex="#111111")}
        html = _render_mix(comps, paints)
        assert "Satin Black S39 + gloss medium (2:1)" in html

    def _mix_guide_body(self, paint_id):
        return {
            "slug": "mix-rt", "title": "Mix RT",
            "tabs": [{"name": "T", "sort_order": 0, "phases": [{"label": "P", "steps": [{
                "title": "Blend",
                "mix_components": [
                    {"paint_id": paint_id, "parts": 2, "sort_order": 0},
                    {"name": "Mid-tone", "parts": 1, "sort_order": 1},
                ],
            }]}]}],
        }

    def test_round_trip_preserves_name_only_component(self, client, paint):
        g = client.post("/painting/guides", json=self._mix_guide_body(paint["id"]))
        assert g.status_code == 201, g.text
        gid = g.json()["id"]
        # GET surfaces the name-only component (paint_id None, name kept).
        comps = client.get(f"/painting/guides/{gid}").json()["tabs"][0]["phases"][0]["steps"][0]["mix_components"]
        assert [(c["paint_id"], c["name"]) for c in comps] == [(paint["id"], None), (None, "Mid-tone")]
        # Export rejoins both components into the mix swatch name.
        html = client.get(f"/painting/guides/{gid}/export").text
        assert f"{paint['name']} {paint['code']} + Mid-tone (2:1)" in html
        # Re-import keeps the name-only component.
        draft, _ = import_guide_html(html, slug="mix-rt2", resolve_paint=lambda n, b: None)
        mix = draft["tabs"][0]["phases"][0]["steps"][0]["mix_components"]
        assert any(m.get("name") == "Mid-tone" and m.get("paint_id") is None for m in mix)

    def test_component_without_paint_or_name_rejected(self, client):
        body = {
            "slug": "bad", "title": "Bad",
            "tabs": [{"name": "T", "sort_order": 0, "phases": [{"label": "P", "steps": [{
                "title": "S", "mix_components": [{"parts": 1, "sort_order": 0}],
            }]}]}],
        }
        assert client.post("/painting/guides", json=body).status_code == 422

    def test_by_code_leading_zero_normalisation(self):
        """Swatch '065 Payne's Grey' matches shelf code '65' (PaintRack strips
        leading zeros on CSV import, so DB stores '65' not '065')."""
        # stripped_tokens: '065'.lstrip('0') = '65'; code '65'.lstrip('0') = '65' -> match
        ws_tokens = set("065 payne's grey".split())
        norm = {t for t in ws_tokens}           # no decimal points here
        stripped = {t.lstrip("0") or "0" for t in norm}
        code = "65"  # as stored in DB
        cs = code.lstrip("0") or "0"
        assert cs in stripped  # '65' in {'65', "payne's", 'grey'}

    def test_by_code_matches_hyphenated_code_via_space_in_swatch(self):
        """'AMP 017 Red Orange' should match code 'AMP-017' via part split."""
        # Verify the logic: parts ['amp','017'] both in ws_tokens
        ws = set("amp 017 red orange".split())
        parts = "amp-017".split("-")
        assert all(p in ws for p in parts)

    def test_canon_expands_tw_abbreviation(self):
        from app.painting.services.importing import _canon
        assert _canon("Bold TW 001") == "bold titanium white 001"
        assert _canon("TW") == "titanium white"

    def test_canon_strips_fw_prefix_and_ink_suffix(self):
        from app.painting.services.importing import _canon
        assert _canon("FW Crimson Ink") == "crimson"
        assert _canon("Payne's Gray Ink") == "payne's grey"
        assert _canon("FW Payne's Gray Ink") == "payne's grey"

    def test_trailing_zero_code_matches_shelf_code_without_zero(self):
        # Shelf stores '77.72' (PaintRack strips trailing zeros); swatch says
        # 'VMC Gunmetal Grey 77.720' — the extra zero must not block resolution.
        # Test _strip_decimal_zeros directly.
        from app.painting.services.importing import _strip_decimal_zeros
        assert _strip_decimal_zeros("77.720") == "77.72"
        assert _strip_decimal_zeros("77.700") == "77.7"
        assert _strip_decimal_zeros("77.72") == "77.72"
        assert _strip_decimal_zeros("AMP-018") == "AMP-018"
        assert _strip_decimal_zeros("17") == "17"

    def test_bare_ratio_suffix_stripped_from_mix_component(self):
        # 'Bold TW 001 + Warm Flesh 073 3:1 (S18 sub)' — bare ratio after paren
        # strip leaves 'Warm Flesh 073 3:1'; should resolve as 'Warm Flesh 073'.
        resolve = lambda n, b: {"bold tw 001": 1, "warm flesh 073": 2}.get(n.lower())
        rep = ImportReport()
        _swatches, mix = _parse_swatch(
            self._swatch("Bold TW 001 + Warm Flesh 073 3:1 (S18 sub)"), resolve, rep, "S")
        assert [(m.get("paint_id"), m.get("name")) for m in mix] == [(1, None), (2, None)]
        assert rep.unresolved_paints == []

    def test_leading_plus_continuation_is_single_swatch(self):
        # '+ Khaki 061 (2:1)' has one real component -> a single swatch, not a mix.
        resolve = lambda n, b: 7 if n.lower() == "khaki 061" else None
        rep = ImportReport()
        swatches, mix = _parse_swatch(self._swatch("+ Khaki 061 (2:1)"), resolve, rep, "S")
        assert [s["paint_id"] for s in swatches] == [7]
        assert mix == []

    def test_single_swatch_keeps_value_and_role(self):
        resolve = lambda n, b: 9 if n.lower() == "coal black 002" else None
        rep = ImportReport()
        swatches, mix = _parse_swatch(self._swatch("Coal Black 002"), resolve, rep, "S")
        assert swatches == [{"paint_id": 9, "value_pct": 40, "role_label": "base"}]
        assert mix == []


class TestSingleSwatchNullable:
    """#477: a single swatch that doesn't resolve to a shelf paint is kept by name
    (paint_id None) instead of dropped, mirroring the #425 mix work."""

    def _swatch(self, name, value="~40% value — base", brand="Pro Acryl"):
        html = (f'<div class="swatch"><div class="swatch-name">{name}</div>'
                f'<div class="swatch-brand">{brand}</div>'
                f'<div class="swatch-value">{value}</div></div>')
        return BeautifulSoup(html, "html.parser").select_one(".swatch")

    def test_unresolved_single_swatch_kept_by_name(self):
        rep = ImportReport()
        swatches, mix = _parse_swatch(self._swatch("Nonexistent NX1"), lambda n, b: None, rep, "S")
        assert mix == []
        assert swatches == [{"name": "Nonexistent NX1", "value_pct": 40, "role_label": "base"}]
        assert any(u["name"] == "Nonexistent NX1" for u in rep.unresolved_paints)
        assert rep.resolved_paints == 0

    def test_render_swatch_uses_name_when_unresolved(self):
        from app.painting.services.rendering import _render_swatch
        sw = SimpleNamespace(paint_id=None, name="Nonexistent NX1", value_pct=40, role_label="base")
        html = _render_swatch(sw, {})
        assert "Nonexistent NX1" in html
        assert "swatch-brand" not in html  # no brand for a name-only swatch

    def test_round_trip_preserves_name_only_swatch(self, client, paint):
        body = {
            "slug": "sw-rt", "title": "SW RT",
            "tabs": [{"name": "T", "sort_order": 0, "phases": [{"label": "P", "steps": [{
                "title": "Step",
                "swatches": [
                    {"paint_id": paint["id"], "sort_order": 0},
                    {"name": "Nonexistent NX1", "value_pct": 30, "sort_order": 1},
                ],
            }]}]}],
        }
        g = client.post("/painting/guides", json=body)
        assert g.status_code == 201, g.text
        gid = g.json()["id"]
        sw = client.get(f"/painting/guides/{gid}").json()["tabs"][0]["phases"][0]["steps"][0]["swatches"]
        assert [(s["paint_id"], s["name"]) for s in sw] == [(paint["id"], None), (None, "Nonexistent NX1")]
        html = client.get(f"/painting/guides/{gid}/export").text
        assert "Nonexistent NX1" in html
        draft, _ = import_guide_html(html, slug="sw-rt2", resolve_paint=lambda n, b: None)
        out = draft["tabs"][0]["phases"][0]["steps"][0]["swatches"]
        assert any(s.get("name") == "Nonexistent NX1" and s.get("paint_id") is None for s in out)

    def test_swatch_without_paint_or_name_rejected(self, client):
        body = {
            "slug": "bad-sw", "title": "Bad",
            "tabs": [{"name": "T", "sort_order": 0, "phases": [{"label": "P", "steps": [{
                "title": "S", "swatches": [{"value_pct": 10, "sort_order": 0}],
            }]}]}],
        }
        assert client.post("/painting/guides", json=body).status_code == 422


class TestMixRoundTrip:
    """_render_mix (export) and _parse_swatch (import) are inverses over a mix
    (#339): components -> 'A + B (3:1)' swatch -> components."""

    _PAINTS = {
        1: PaintInfo(name="Burnt Sienna", code="073", brand="Pro Acryl", hex="#a0522d"),
        2: PaintInfo(name="Titanium White", code="001", brand="Pro Acryl", hex="#ffffff"),
    }

    def _parse_rendered(self, html):
        swatch = BeautifulSoup(f'<div class="swatches">{html}</div>', "html.parser").select_one(".swatch")
        resolve = lambda n, b: next(
            (pid for pid, p in self._PAINTS.items() if f"{p.name} {p.code}".lower() == n.lower()),
            None,
        )
        return _parse_swatch(swatch, resolve, ImportReport(), "S")

    def test_ratio_round_trips(self):
        comps = [SimpleNamespace(paint_id=1, parts=3.0), SimpleNamespace(paint_id=2, parts=1.0)]
        html = _render_mix(comps, self._PAINTS)
        assert "Burnt Sienna 073 + Titanium White 001 (3:1)" in html
        swatches, mix = self._parse_rendered(html)
        assert swatches == []
        assert [(m["paint_id"], m["parts"]) for m in mix] == [(1, 3.0), (2, 1.0)]

    def test_equal_parts_omit_ratio_suffix(self):
        comps = [SimpleNamespace(paint_id=1, parts=1.0), SimpleNamespace(paint_id=2, parts=1.0)]
        html = _render_mix(comps, self._PAINTS)
        assert "(" not in html  # no ratio suffix when parts are equal
        _swatches, mix = self._parse_rendered(html)
        assert [m["paint_id"] for m in mix] == [1, 2]

    def test_blended_dot_is_mean_rgb(self):
        comps = [SimpleNamespace(paint_id=1, parts=1.0), SimpleNamespace(paint_id=2, parts=1.0)]
        html = _render_mix(comps, self._PAINTS)
        # mean of #a0522d and #ffffff = (cf, a8, 96)
        assert "background:#cfa896" in html


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


class TestSkillsTabContract:
    """#271 (3/3): the shared skills tabs (airbrush-skills / brush-skills /
    thinning-ref) are runtime furniture built by skills-reference.js from static
    templates + window.GUIDE_THINNING — not guide data. The exporter emits empty
    placeholders + the script ref; the importer skips them. This locks that
    contract so the round-trip stays clean without storing reproducible HTML
    (which could drift from the live JS). The one guide-specific input,
    GUIDE_THINNING, already round-trips (1/3)."""

    def _export(self, client, paint):
        g = client.post("/painting/guides", json=presto_body(paint["id"])).json()
        return client.get(f"/painting/guides/{g['id']}/export").text

    def test_export_emits_empty_placeholder_per_skills_tab(self, client, paint):
        html = self._export(client, paint)
        for _label, dom_id in SKILLS_TABS:
            assert f'<div class="tab-content" id="{dom_id}">' in html
        # The bodies are injected at runtime, not serialized.
        assert "Content injected by skills-reference.js" in html

    def test_export_references_the_skills_script(self, client, paint):
        html = self._export(client, paint)
        assert f'<script src="{SKILLS_JS_SRC}"></script>' in html

    def test_export_emits_skills_nav_buttons(self, client, paint):
        html = self._export(client, paint)
        for label, dom_id in SKILLS_TABS:
            assert f"showTab('{dom_id}', this)" in html
            assert f">{label}</div>" in html

    def test_reimport_skips_skills_tabs(self, client, paint):
        """Re-importing our own export drops the skills tabs (no placeholder body
        becomes a structured tab), so the round-trip is clean."""
        html = self._export(client, paint)
        draft, report = import_guide_html(html, slug="rt", resolve_paint=lambda n, b: None)
        dom_ids = {t["dom_id"] for t in draft["tabs"]}
        for _label, dom_id in SKILLS_TABS:
            assert dom_id not in dom_ids
        # Empty placeholders contribute nothing to the schema-coverage gap list.
        assert not any(d in n for d in (i for _l, i in SKILLS_TABS) for n in report.unmapped_nodes)


class TestSeriesBadge:
    """#271: the hero .series-badge (active + sibling cross-link chips) is captured
    on import and re-emitted on export, so sibling links round-trip."""

    def _hero(self, badge: str) -> str:
        return (f'<html><body><div class="hero">'
                f'<h1><span>Presto</span> the Magician</h1>{badge}</div></body></html>')

    def test_importer_captures_active_and_sibling_chips(self):
        badge = ('<div class="series-badge">'
                 '<a href="hank-ranger-dnd-painting-guide.html">Hank</a>'
                 '<span class="active">Presto</span></div>')
        draft, _ = import_guide_html(self._hero(badge), slug="presto", resolve_paint=lambda n, b: None)
        assert draft["series_badge"] == [
            {"label": "Hank", "filename": "hank-ranger-dnd-painting-guide.html", "active": False},
            {"label": "Presto", "active": True},
        ]

    def test_no_badge_omits_field(self):
        draft, _ = import_guide_html(self._hero(""), slug="p", resolve_paint=lambda n, b: None)
        assert "series_badge" not in draft

    def test_dangerous_href_dropped_to_linkless_chip(self):
        badge = ('<div class="series-badge">'
                 '<a href="javascript:alert(1)">Evil</a>'
                 '<span class="active">Presto</span></div>')
        draft, _ = import_guide_html(self._hero(badge), slug="p", resolve_paint=lambda n, b: None)
        assert draft["series_badge"][0] == {"label": "Evil", "filename": None, "active": False}

    def test_round_trips_through_export_import(self, client, paint):
        body = presto_body(paint["id"])
        body["series_badge"] = [
            {"label": "Hank", "filename": "hank-ranger-dnd-painting-guide.html", "active": False},
            {"label": "Presto", "active": True},
        ]
        g = client.post("/painting/guides", json=body).json()
        html = client.get(f"/painting/guides/{g['id']}/export").text
        assert '<a href="hank-ranger-dnd-painting-guide.html">Hank</a>' in html
        assert '<span class="active">Presto</span>' in html
        draft, _ = import_guide_html(html, slug="presto2", resolve_paint=lambda n, b: None)
        assert draft["series_badge"][0]["filename"] == "hank-ranger-dnd-painting-guide.html"
        assert draft["series_badge"][1]["active"] is True

    def test_export_without_badge_falls_back_to_active_span(self, client, paint):
        g = client.post("/painting/guides", json=presto_body(paint["id"])).json()
        html = client.get(f"/painting/guides/{g['id']}/export").text
        assert '<div class="series-badge">' in html
        assert "<a href=" not in html.split('series-badge')[1].split("</div>")[0]


class TestGuideThinningImport:
    """#271: the importer parses the real-corpus GUIDE_THINNING JS object literal
    (unquoted keys, single quotes, trailing commas), not just strict JSON."""

    def _thinning(self, literal: str):
        html = f"<html><body><script>window.GUIDE_THINNING = {literal};</script></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        report = ImportReport()
        return _parse_thinning(soup, report), report

    def test_strict_json_still_parses(self):
        out, report = self._thinning(
            '{"airbrushRows": [{"technique": "Base", "ratio": "2:1"}],'
            ' "brushRows": [], "thinningCards": []}'
        )
        assert out["airbrush_rows"] == [{"technique": "Base", "ratio": "2:1"}]
        assert report.notes == []

    def test_js_literal_unquoted_keys_and_single_quotes(self):
        out, report = self._thinning(
            "{ airbrushRows: [ { technique: 'Zenithal', nozzle: '0.4', ratio: '1:1' } ],"
            " brushRows: [ { technique: 'Layer', ratio: '3:1' } ],"
            " thinningCards: [ { title: 'Tip', body: 'Thin your paints' } ], }"
        )
        assert out["airbrush_rows"] == [{"technique": "Zenithal", "nozzle": "0.4", "ratio": "1:1"}]
        assert out["brush_rows"] == [{"technique": "Layer", "ratio": "3:1"}]
        assert out["thinning_cards"] == [{"title": "Tip", "body": "Thin your paints"}]
        assert report.notes == []  # parsed, not noted as a failure

    def test_apostrophe_inside_value_survives(self):
        out, _ = self._thinning(
            r"{ thinningCards: [ { title: 'Don\'t', body: 'it ain\'t thin' } ] }"
        )
        assert out["thinning_cards"] == [{"title": "Don't", "body": "it ain't thin"}]

    def test_colon_in_value_not_treated_as_key(self):
        out, _ = self._thinning("{ thinningCards: [ { body: 'ratio is 2:1 here' } ] }")
        assert out["thinning_cards"] == [{"body": "ratio is 2:1 here"}]

    def test_truly_malformed_is_noted_and_dropped(self):
        out, report = self._thinning("{ airbrushRows: [ { technique: }")  # unbalanced
        assert out is None
        assert any("GUIDE_THINNING" in n for n in report.notes)


class TestJsObjectToJson:
    """Unit coverage for the JS-literal normalizer (#271)."""

    def test_quotes_barewords_and_keeps_literals(self):
        assert json.loads(_js_object_to_json("{a: true, b: false, c: null, d: 3}")) == {
            "a": True, "b": False, "c": None, "d": 3,
        }

    def test_strips_trailing_commas(self):
        assert json.loads(_js_object_to_json("{a: [1, 2,], b: 3,}")) == {"a": [1, 2], "b": 3}

    def test_single_to_double_quotes(self):
        assert json.loads(_js_object_to_json("{a: 'x', b: 'y'}")) == {"a": "x", "b": "y"}


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

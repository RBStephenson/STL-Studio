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

from app.painting.services.importing import import_guide_html, make_db_resolver
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

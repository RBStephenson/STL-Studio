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

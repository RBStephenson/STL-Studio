"""M2 #268 — guide schema extended to cover the real corpus DOM.

Drives the field set off the latest exemplar (Presto / Vigilante): authored tab
`dom_id`, sub-tabs with phase grouping, section headers, structured method
cards, step technique labels, paint-bar pill colors, and the hero/header
furniture (title_lead, subtitle, category_label, quote, head_style). Asserts
the whole tree round-trips through create -> read intact.
"""
import pytest

from tests.test_painting_guides import mk_paint


@pytest.fixture
def paint(client):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    line = client.post(
        "/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}
    ).json()
    return mk_paint(client, line["id"])


def presto_body(paint_id, **over):
    """A guide shaped like the real Presto/Vigilante DOM."""
    body = {
        "slug": "presto-magician",
        "title": "Presto the Magician",
        "title_lead": "Presto",
        "subtitle": "1:6 Scale · Young spellcaster · green robe · cool blue magic OSL",
        "category_label": "D&D Animated Series · 1983 Cartoon",
        "scale": "1:6",
        "quote": "Magic hat, don't fail me now!",
        "creator_credit": {
            "name": "Toon Studios",
            "url": "https://www.instagram.com/_toonstudio",
            "link_text": "@_toonstudio",
        },
        "paint_lines_used": [
            {"name": "Pro Acryl", "color": "#cc4444"},
            {"name": "Citadel (Nuln Oil)", "color": "#1a1a1a"},
        ],
        "technique_tags": ["OSL"],
        "character_brief": {"philosophy": "value first, warm key + cool OSL"},
        "head_style": ":root{--accent:#3f8a45}\n.sub-tab.folk-art-tab.active{color:#a8cc66}",
        "tabs": [
            {
                "name": "Skin",
                "dom_id": "skin",
                "sort_order": 0,
                "has_expert_subtab": True,
                "section": {
                    "heading": "Skin",
                    "intro": "Fair, warm, youthful complexion with <em>ginger freckling</em>.",
                },
                "value_map": {
                    "label": "Value Structure",
                    "chips": [
                        {"hex": "#5a2e22", "value_pct": 25, "zone_label": "Deep Shadow"},
                        {"hex": "#f4e0cc", "value_pct": 92, "zone_label": "Specular"},
                    ],
                },
                "method_block": {
                    "recommendation": "<strong>Method 2A — Pinkle (recommended).</strong>",
                    "cards": [
                        {
                            "title": "Method 1 — Basic",
                            "body": "Classic layering.",
                            "pros": "Predictable",
                            "cons": "Can read flat",
                            "best": "First-time painters",
                        },
                        {
                            "title": "Method 2A — Pinkle",
                            "body": "Black prime → white zenithal → magenta.",
                            "pros": "Luminous",
                            "cons": "Zenithal-dependent",
                            "best": "Heroic figures",
                            "recommended": True,
                            "badge": "★ Recommended",
                        },
                    ],
                    "freckle_note": "<strong>Freckling:</strong> Presto is a ginger.",
                },
                "subtabs": [
                    {"key": "pro", "label": "Pro Acryl", "sort_order": 0},
                    {"key": "expert", "label": "✦ Expert Acrylics — Brush Only",
                     "css_class": "expert-tab", "sort_order": 1,
                     # Sub-content-level prose (#271 residual): belongs to this
                     # subtab, round-trips inside its .sub-content.
                     "callouts": [
                         {"kind": "tip",
                          "html": "<strong>✦ TIP:</strong> Expert Acrylics dry matte."},
                     ]},
                ],
                # Tab-level prose (#271): intro <p> renders above the content,
                # tip/warning below the steps — order matches the exporter's split.
                "callouts": [
                    {"kind": "text",
                     "html": "Skin is the <em>largest</em> exposed area — invest here."},
                    {"kind": "tip",
                     "html": "<strong>✦ TIP:</strong> Photograph and desaturate to check value."},
                    {"kind": "warning",
                     "html": "<strong>⚠ NOTE:</strong> Thin glazes, never flood recesses."},
                ],
                # Unmodelled block captured verbatim (#271 step 2) — round-trips
                # without a dedicated schema.
                "raw_blocks": [
                    {"css_class": "tier-card",
                     "html": '<div class="tier-card"><h3>Display</h3></div>'},
                ],
                "phases": [
                    {
                        "label": "Foundation",
                        "subtab_key": "pro",
                        "sort_order": 0,
                        "steps": [
                            {
                                "title": "Black Prime",
                                "technique_tag": "airbrush",
                                "technique_label": "Airbrush",
                                "body": "P-002 Black Primer — undiluted.",
                                "warning": "<strong>⚠ NOTE:</strong> Never thin primer.",
                                "swatches": [
                                    {"paint_id": paint_id, "value_pct": 5,
                                     "role_label": "black prime"},
                                ],
                            },
                        ],
                    },
                    {
                        "label": "Foundation",
                        "subtab_key": "expert",
                        "sort_order": 1,
                        "steps": [
                            {
                                "title": "Shadow Base",
                                "technique_tag": "brush",
                                "technique_label": "Brush — Wet Blend",
                                "body": "Burnt Umber + Carbon Black.",
                                "swatches": [
                                    {"paint_id": paint_id, "role_label": "shadow"},
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    }
    body.update(over)
    return body


def _create(client, paint_id, **over):
    r = client.post("/painting/guides", json=presto_body(paint_id, **over))
    assert r.status_code == 201, r.text
    return r.json()


class TestHeaderFurniture:
    def test_hero_fields_round_trip(self, client, paint):
        g = _create(client, paint["id"])
        assert g["title_lead"] == "Presto"
        assert g["subtitle"].startswith("1:6 Scale")
        assert g["category_label"] == "D&D Animated Series · 1983 Cartoon"
        assert g["quote"] == "Magic hat, don't fail me now!"
        assert g["head_style"].startswith(":root{--accent:#3f8a45}")

    def test_creator_credit_link_text(self, client, paint):
        g = _create(client, paint["id"])
        assert g["creator_credit"]["link_text"] == "@_toonstudio"
        assert g["creator_credit"]["name"] == "Toon Studios"

    def test_paint_bar_pills_with_colors(self, client, paint):
        g = _create(client, paint["id"])
        pills = g["paint_lines_used"]
        assert pills[0] == {"name": "Pro Acryl", "color": "#cc4444"}
        assert pills[1]["name"] == "Citadel (Nuln Oil)"

    def test_get_by_id_returns_same_header(self, client, paint):
        g = _create(client, paint["id"])
        got = client.get(f"/painting/guides/{g['id']}").json()
        assert got["title_lead"] == "Presto"
        assert got["head_style"] == g["head_style"]


class TestTabStructure:
    def test_tab_dom_id_and_section(self, client, paint):
        tab = _create(client, paint["id"])["tabs"][0]
        assert tab["dom_id"] == "skin"
        assert tab["section"]["heading"] == "Skin"
        assert "<em>ginger freckling</em>" in tab["section"]["intro"]

    def test_value_map_label(self, client, paint):
        tab = _create(client, paint["id"])["tabs"][0]
        assert tab["value_map"]["label"] == "Value Structure"
        assert len(tab["value_map"]["chips"]) == 2

    def test_subtabs_defined_in_order(self, client, paint):
        tab = _create(client, paint["id"])["tabs"][0]
        keys = [s["key"] for s in tab["subtabs"]]
        assert keys == ["pro", "expert"]
        assert tab["subtabs"][1]["css_class"] == "expert-tab"

    def test_method_block_cards(self, client, paint):
        tab = _create(client, paint["id"])["tabs"][0]
        mb = tab["method_block"]
        assert "<strong>" in mb["recommendation"]
        assert mb["cards"][1]["recommended"] is True
        assert mb["cards"][1]["badge"] == "★ Recommended"
        assert mb["cards"][0]["pros"] == "Predictable"
        assert mb["freckle_note"].startswith("<strong>Freckling")

    def test_tab_callouts_survive_create(self, client, paint):
        tab = _create(client, paint["id"])["tabs"][0]
        kinds = [c["kind"] for c in tab["callouts"]]
        assert kinds == ["text", "tip", "warning"]
        assert "<em>largest</em>" in tab["callouts"][0]["html"]

    def test_tab_callouts_default_empty(self, client, paint):
        body = presto_body(paint["id"])
        del body["tabs"][0]["callouts"]
        tab = client.post("/painting/guides", json=body).json()["tabs"][0]
        assert tab["callouts"] == []

    def test_callout_rejects_unknown_kind(self, client, paint):
        body = presto_body(paint["id"])
        body["tabs"][0]["callouts"] = [{"kind": "note", "html": "x"}]
        r = client.post("/painting/guides", json=body)
        assert r.status_code == 422


class TestStepAndPhaseGrouping:
    def test_phase_subtab_key_and_step_technique_label(self, client, paint):
        tab = _create(client, paint["id"])["tabs"][0]
        phases = tab["phases"]
        assert {p["subtab_key"] for p in phases} == {"pro", "expert"}
        pro_step = next(p for p in phases if p["subtab_key"] == "pro")["steps"][0]
        assert pro_step["technique_label"] == "Airbrush"
        expert_step = next(p for p in phases if p["subtab_key"] == "expert")["steps"][0]
        assert expert_step["technique_label"] == "Brush — Wet Blend"

    def test_step_warning_preserves_inline_html(self, client, paint):
        tab = _create(client, paint["id"])["tabs"][0]
        step = tab["phases"][0]["steps"][0]
        assert step["warning"] == "<strong>⚠ NOTE:</strong> Never thin primer."

    def test_swatch_still_validates_paint_ref(self, client, paint):
        # The relational spine still rejects unknown paint ids (422).
        bad = presto_body(paint["id"])
        bad["tabs"][0]["phases"][0]["steps"][0]["swatches"][0]["paint_id"] = 999999
        r = client.post("/painting/guides", json=bad)
        assert r.status_code == 422


class TestBackwardCompatAndPatch:
    def test_minimal_guide_still_works(self, client, paint):
        # New fields are all optional — a bare guide still creates.
        r = client.post("/painting/guides", json={"slug": "min", "title": "Min"})
        assert r.status_code == 201, r.text
        g = r.json()
        assert g["title_lead"] is None
        assert g["paint_lines_used"] == []
        assert g["tabs"] == []

    def test_patch_clears_nullable_header_field(self, client, paint):
        g = _create(client, paint["id"])
        r = client.patch(f"/painting/guides/{g['id']}", json={"subtitle": None})
        assert r.status_code == 200
        assert r.json()["subtitle"] is None

    def test_patch_replaces_paint_bar(self, client, paint):
        g = _create(client, paint["id"])
        r = client.patch(
            f"/painting/guides/{g['id']}",
            json={"paint_lines_used": [{"name": "Vallejo", "color": "#222222"}]},
        )
        assert r.status_code == 200
        assert r.json()["paint_lines_used"] == [{"name": "Vallejo", "color": "#222222"}]

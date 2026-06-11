"""Static-HTML exporter (M2, #260): serialize a stored guide to the real
legacy DOM (`painting-guides/by-category/**/*.html`), anchored on Presto.

These tests pin the real corpus class names / structure — the contract the
importer (#261) round-trips against.
"""
import re

import pytest

from tests.test_painting_guides import mk_paint
from tests.test_painting_guide_schema import presto_body


@pytest.fixture
def paint(client):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    line = client.post(
        "/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}
    ).json()
    return mk_paint(client, line["id"])


def _export(client, paint_id, **over):
    g = client.post("/painting/guides", json=presto_body(paint_id, **over)).json()
    r = client.get(f"/painting/guides/{g['id']}/export")
    assert r.status_code == 200, r.text
    return r


class TestEndpoint:
    def test_unknown_guide_404(self, client):
        assert client.get("/painting/guides/999/export").status_code == 404

    def test_download_headers(self, client, paint):
        r = _export(client, paint["id"])
        assert r.headers["content-type"].startswith("text/html")
        assert 'filename="presto-magician.html"' in r.headers["content-disposition"]

    def test_document_shell(self, client, paint):
        html = _export(client, paint["id"]).text
        assert html.startswith("<!DOCTYPE html>")
        assert '<html lang="en">' in html
        assert "<title>Presto the Magician — 1:6 Scale Painting Guide</title>" in html
        assert 'href="../../assets/guide.css"' in html
        assert 'href="../../assets/print.css" media="print"' in html

    def test_head_style_block(self, client, paint):
        html = _export(client, paint["id"]).text
        assert "<style>" in html
        assert "--accent:#3f8a45" in html
        assert ".sub-tab.folk-art-tab.active{color:#a8cc66}" in html

    def test_guide_nav_boilerplate(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<nav class="guide-nav">' in html
        assert "← All Guides" in html


class TestHero:
    def test_category_and_h1_lead_span(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="category">D&amp;D Animated Series · 1983 Cartoon</div>' in html
        assert "<h1><span>Presto</span> the Magician</h1>" in html

    def test_subtitle_and_quote(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="subtitle">1:6 Scale' in html
        assert '<em>"Magic hat, don\'t fail me now!"</em>' in html

    def test_series_badge_active_chip(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="series-badge">' in html
        assert '<span class="active">Presto</span>' in html

    def test_creator_credit_with_link_text(self, client, paint):
        html = _export(client, paint["id"]).text
        assert "Figure by <strong>Toon Studios</strong>" in html
        assert '<a href="https://www.instagram.com/_toonstudio" target="_blank">@_toonstudio</a>' in html


class TestPaintBarAndBrief:
    def test_paint_bar_pills(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<span class="paint-bar-label">Paint Lines Used</span>' in html
        assert '<span class="pill-dot" style="background:#cc4444;"></span>Pro Acryl' in html
        assert "Citadel (Nuln Oil)" in html

    def test_char_brief_preserves_inline_html(self, client, paint):
        html = _export(
            client, paint["id"],
            character_brief={"philosophy": "Value first with a <strong>green robe</strong>."},
        ).text
        assert '<div class="char-brief">Value first with a <strong>green robe</strong>.</div>' in html


class TestTabsAndContent:
    def test_tab_nav_plus_skills_tabs(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="tab tab-btn active" onclick="showTab(\'skin\', this)">Skin</div>' in html
        assert "showTab('airbrush-skills', this)" in html
        assert "showTab('brush-skills', this)" in html
        assert "showTab('thinning-ref', this)" in html

    def test_section_header(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="tab-content active" id="skin">' in html
        assert '<div class="section-header">' in html
        assert "<h2>Skin</h2>" in html
        assert "<em>ginger freckling</em>" in html

    def test_value_map(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="phase-label">Value Structure</div>' in html
        assert '<div class="chip-swatch" style="background:#5a2e22;"></div>' in html
        assert '<div class="chip-val">~25%</div>' in html
        assert '<div class="chip-label">Deep Shadow</div>' in html

    def test_method_block(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="phase-label">Method Selection</div>' in html
        assert '<div class="method-rec-block"><strong>Method 2A — Pinkle (recommended).</strong></div>' in html
        assert '<div class="method-card recommended">' in html
        assert '<span class="method-card-badge">★ Recommended</span>' in html
        assert '<span class="mc-pros">Predictable</span>' in html
        assert '<div class="freckle-note"><strong>Freckling:</strong> Presto is a ginger.</div>' in html


class TestSubTabsAndSteps:
    def test_sub_tabs_and_sub_content(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="phase-label">Step-by-Step</div>' in html
        assert "showSubTab('skin', 'skin-pro', this)" in html
        assert '<div class="sub-content active" id="skin-pro">' in html
        assert '<div class="sub-content" id="skin-expert">' in html

    def test_step_number_and_swatch(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<span class="step-number airbrush">Step 1 · Airbrush</span>' in html
        # nested swatch-info structure
        assert '<div class="swatch-dot" style="background:#2A2A2A"></div>' in html
        assert '<div class="swatch-info"><div class="swatch-name">Coal Black 002</div>' in html
        assert '<div class="swatch-brand">Monument Hobbies</div>' in html

    def test_step_numbering_resets_per_subcontent(self, client, paint):
        html = _export(client, paint["id"]).text
        # both the pro and expert sub-contents start at Step 1
        assert html.count(">Step 1 · ") == 2
        assert '<span class="step-number brush">Step 1 · Brush — Wet Blend</span>' in html

    def test_warning_html_verbatim(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="warning"><strong>⚠ NOTE:</strong> Never thin primer.</div>' in html


class TestBoilerplateAndThinning:
    def test_skills_tab_placeholders(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<div class="tab-content" id="airbrush-skills">' in html
        assert "Content injected by skills-reference.js" in html

    def test_footer_modal_backtotop(self, client, paint):
        html = _export(client, paint["id"]).text
        assert '<footer class="guide-footer">' in html
        assert 'id="refModal"' in html
        assert 'id="backToTop"' in html

    def test_guide_thinning_block_and_scripts(self, client, paint):
        html = _export(
            client, paint["id"],
            thinning_config={
                "airbrush_rows": [{"technique": "Base", "nozzle": "0.3mm", "ratio": "1:3"}],
                "brush_rows": [], "thinning_cards": [],
            },
        ).text
        m = re.search(r"window\.GUIDE_THINNING = (\{.*?\});", html, re.S)
        assert m and '"airbrushRows"' in m.group(1) and '"thinningCards"' in m.group(1)
        assert 'src="../../assets/guide.js"' in html
        assert 'src="../../assets/skills-reference.js"' in html
        assert "function showSubTab(" in html


class TestEscapingAndStability:
    def test_plain_text_escaped(self, client, paint):
        html = _export(client, paint["id"], title="Presto<script>x</script>",
                       title_lead="Presto").text
        assert "<script>x</script>" not in html.split("</title>")[0] + html.split("</head>")[1]
        assert "Presto&lt;script&gt;x&lt;/script&gt;" in html

    def test_deterministic(self, client, paint):
        a = _export(client, paint["id"], slug="det-1").text
        b = _export(client, paint["id"], slug="det-2").text
        assert a.replace("det-1", "X") == b.replace("det-2", "X")

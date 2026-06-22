"""PDF export (M3, #320): guide -> inlined-asset HTML -> Chromium -> PDF.

Two layers:
- The inlined-HTML builder (`render_guide_pdf_html`) is pure and always runs —
  it pins that the four corpus assets get inlined and no external asset
  references survive (Chromium would fail to load them otherwise).
- The end-to-end render through Playwright/Chromium is skipped when the browser
  isn't installed, so the slim local-CI image (no Chromium) stays green while
  hosted CI and Docker — which install it — exercise the real path.
"""
import asyncio

import pytest

from app.painting.models import Guide, GuideSeries
from app.painting.services.pdf import (
    EmptySeriesError,
    StampConfig,
    _cover_html,
    _series_guides,
    render_guide_pdf_html,
    render_series_pdf,
)
from app.painting.services.rendering import (
    GUIDE_CSS_HREF, GUIDE_JS_SRC, PRINT_CSS_HREF, SKILLS_JS_SRC,
)

from tests.test_painting_guides import mk_paint
from tests.test_painting_guide_schema import presto_body


@pytest.fixture
def paint(client):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    line = client.post(
        "/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}
    ).json()
    return mk_paint(client, line["id"])


def _make_guide(client, db, paint_id, **over):
    gid = client.post("/painting/guides", json=presto_body(paint_id, **over)).json()["id"]
    return db.get(Guide, gid)


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


requires_chromium = pytest.mark.skipif(
    not _chromium_available(), reason="Playwright Chromium not installed"
)


class TestInlinedHtml:
    def test_assets_are_inlined(self, client, db, paint):
        guide = _make_guide(client, db, paint["id"])
        html = render_guide_pdf_html(db, guide)
        # The whole point: no external asset references remain for Chromium to
        # fail to resolve.
        for href in (GUIDE_CSS_HREF, PRINT_CSS_HREF, GUIDE_JS_SRC, SKILLS_JS_SRC):
            assert href not in html
        # Asset bodies are present inline (sentinels from the real corpus files).
        assert "<style>" in html
        assert '<style media="print">' in html
        assert "showTab" in html  # guide.js
        assert "GUIDE_THINNING" in html  # skills-reference.js consumes this

    def test_preserves_guide_content(self, client, db, paint):
        guide = _make_guide(client, db, paint["id"])
        html = render_guide_pdf_html(db, guide)
        assert "<!DOCTYPE html>" in html
        assert 'class="paint-bar"' in html

    def test_print_css_is_dark_and_forces_colour(self, client, db, paint):
        # #418: print/PDF keeps the dark page background (white-on-paper was
        # unreadable) and must force browsers to paint backgrounds.
        guide = _make_guide(client, db, paint["id"])
        html = render_guide_pdf_html(db, guide)
        print_block = html.split('<style media="print">', 1)[1].split("</style>", 1)[0]
        assert "background: #1a1a1a !important" in print_block
        assert "print-color-adjust: exact !important" in print_block
        assert "color: #e8e8e8 !important" in print_block


class TestStamping:
    def test_footer_on_by_default(self, client, db, paint):
        guide = _make_guide(client, db, paint["id"])
        html = render_guide_pdf_html(db, guide, StampConfig())
        assert "pdf-stamp-footer" in html
        assert "Patreon-exclusive" in html
        # Watermark is opt-in.
        assert "pdf-stamp-watermark" not in html

    def test_no_stamp_when_omitted(self, client, db, paint):
        guide = _make_guide(client, db, paint["id"])
        html = render_guide_pdf_html(db, guide)
        assert "pdf-stamp-footer" not in html
        assert "pdf-stamp-watermark" not in html

    def test_tier_label_appended_to_footer(self, client, db, paint):
        guide = _make_guide(client, db, paint["id"])
        html = render_guide_pdf_html(db, guide, StampConfig(tier_label="Hero Tier"))
        assert "Hero Tier" in html

    def test_watermark_opt_in(self, client, db, paint):
        guide = _make_guide(client, db, paint["id"])
        html = render_guide_pdf_html(
            db, guide, StampConfig(footer=False, watermark=True)
        )
        assert "pdf-stamp-watermark" in html
        assert "pdf-stamp-footer" not in html

    def test_stamp_text_is_escaped(self, client, db, paint):
        guide = _make_guide(client, db, paint["id"])
        html = render_guide_pdf_html(
            db, guide, StampConfig(tier_label="<script>x</script>")
        )
        assert "<script>x</script>" not in html
        assert "&lt;script&gt;" in html


def _publish_in_series(db, guide, series_id):
    guide.series_id = series_id
    guide.status = "published"
    db.add(guide)
    db.commit()


class TestSeriesBundle:
    def test_collects_only_published_in_id_order(self, client, db, paint):
        series = GuideSeries(slug="dnd-toons", display_name="D&D Toons")
        db.add(series)
        db.commit()
        g1 = _make_guide(client, db, paint["id"], slug="presto-1", title="Presto One")
        g2 = _make_guide(client, db, paint["id"], slug="presto-2", title="Presto Two")
        draft = _make_guide(client, db, paint["id"], slug="presto-3", title="Draft")
        _publish_in_series(db, g1, series.id)
        _publish_in_series(db, g2, series.id)
        # draft stays draft + out of series
        guides = _series_guides(db, series)
        assert [g.id for g in guides] == [g1.id, g2.id]
        assert draft.id not in {g.id for g in guides}

    def test_cover_html_lists_guides(self, client, db, paint):
        series = GuideSeries(slug="dnd-toons", display_name="D&D Toons")
        db.add(series)
        db.commit()
        g1 = _make_guide(client, db, paint["id"], slug="presto-1", title="Presto One")
        _publish_in_series(db, g1, series.id)
        html = _cover_html(series, [g1])
        assert "D&amp;D Toons" in html
        assert "Presto One" in html

    def test_empty_series_raises(self, client, db):
        series = GuideSeries(slug="empty", display_name="Empty")
        db.add(series)
        db.commit()
        with pytest.raises(EmptySeriesError):
            asyncio.run(render_series_pdf(db, series))


class TestEndpoint:
    def test_unknown_guide_404(self, client):
        assert client.get("/painting/guides/999/export/pdf").status_code == 404

    def test_unknown_series_404(self, client):
        assert client.get("/painting/series/999/export/pdf").status_code == 404

    def test_empty_series_404(self, client, db):
        series = GuideSeries(slug="empty-ep", display_name="Empty EP")
        db.add(series)
        db.commit()
        assert client.get(f"/painting/series/{series.id}/export/pdf").status_code == 404

    @requires_chromium
    def test_renders_pdf(self, client, paint):
        gid = client.post(
            "/painting/guides", json=presto_body(paint["id"])
        ).json()["id"]
        r = client.get(f"/painting/guides/{gid}/export/pdf")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert 'filename="presto-magician.pdf"' in r.headers["content-disposition"]
        assert r.content[:5] == b"%PDF-"

    @requires_chromium
    def test_renders_series_bundle(self, client, db, paint):
        series = GuideSeries(slug="dnd-toons", display_name="D&D Toons")
        db.add(series)
        db.commit()
        g1 = _make_guide(client, db, paint["id"], slug="presto-1", title="Presto One")
        g2 = _make_guide(client, db, paint["id"], slug="presto-2", title="Presto Two")
        _publish_in_series(db, g1, series.id)
        _publish_in_series(db, g2, series.id)
        r = client.get(f"/painting/series/{series.id}/export/pdf")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert 'filename="dnd-toons-bundle.pdf"' in r.headers["content-disposition"]
        assert r.content[:5] == b"%PDF-"

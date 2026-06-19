"""PDF export (M3, #320): guide -> inlined-asset HTML -> Chromium -> PDF.

Two layers:
- The inlined-HTML builder (`render_guide_pdf_html`) is pure and always runs —
  it pins that the four corpus assets get inlined and no external asset
  references survive (Chromium would fail to load them otherwise).
- The end-to-end render through Playwright/Chromium is skipped when the browser
  isn't installed, so the slim local-CI image (no Chromium) stays green while
  hosted CI and Docker — which install it — exercise the real path.
"""
import pytest

from app.painting.models import Guide
from app.painting.services.pdf import render_guide_pdf_html
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


class TestEndpoint:
    def test_unknown_guide_404(self, client):
        assert client.get("/painting/guides/999/export/pdf").status_code == 404

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

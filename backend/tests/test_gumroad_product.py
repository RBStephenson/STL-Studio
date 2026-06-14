"""
Regression tests for the single-product Gumroad scraper (issue #317).

Gumroad's Inertia app emits Open Graph tags with a `value=` attribute on
og:title / og:description (and `content=` on og:image). The scraper's `og()`
helper previously read `content` only, so title/description/thumbnail came back
None and product enrichment fell through. These tests pin the `value=`/`content=`
parsing against a trimmed capture of a real product page.
"""
from pathlib import Path

from app.services.scrapers import gumroad

_FIXTURE = Path(__file__).parent / "fixtures" / "gumroad_qb01_product.html"
_URL = "https://francisquez.gumroad.com/l/qb01jshark"


def test_parses_value_attribute_og_tags():
    model = gumroad._parse(_FIXTURE.read_text(encoding="utf-8"), _URL)

    assert model is not None
    assert model.title == "QB01: J. Shark - 3D printing model"
    assert model.description.startswith("Hi!Q- Bestiary #01: J. Shark")
    # og:image uses content=, and seeds the image list / thumbnail.
    assert model.thumbnail_url == "https://public-files.gumroad.com/89u6yjpug60ndgc6ms9zf1z0fmut"
    assert model.source_site == "gumroad"
    assert model.external_id == "qb01jshark"


def test_og_reads_content_attribute_too():
    """Legacy `content=` OG markup must still parse (back-compat)."""
    html = (
        '<html><head>'
        '<meta property="og:title" content="Legacy Title">'
        '<meta property="og:description" content="Legacy description">'
        '<meta property="og:image" content="https://example.com/x.png">'
        '</head><body></body></html>'
    )
    model = gumroad._parse(html, "https://creator.gumroad.com/l/legacy1")

    assert model is not None
    assert model.title == "Legacy Title"
    assert model.description == "Legacy description"
    assert model.thumbnail_url == "https://example.com/x.png"

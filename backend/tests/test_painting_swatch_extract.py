"""Vector PDF swatch extraction — synthetic-fixture coverage (STUDIO-331).

Fixtures are built programmatically via PyMuPDF's own drawing API rather than
bundling real manufacturer chart PDFs (Pro Acryl's "Hues" chart, Army
Painter's "Practical Colour Name Chart") into the repo — both are
proprietary chart art, not something to ship in an MIT-licensed public repo.
The extraction logic itself was developed and hand-validated against those
real files; these fixtures reproduce the specific structural patterns that
mattered (halo+fill circle pairs, a jittered duplicate text layer, tight row
spacing, decorative non-swatch vector shapes, embedded-image-only pages)
without the art.
"""
from __future__ import annotations

import fitz
import pytest

from app.painting.services.swatch_extract import extract_vector_swatches

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _new_page(width: float = 300, height: float = 300) -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    return doc, page


def _draw_swatch(
    page: fitz.Page,
    cx: float,
    cy: float,
    radius: float,
    fill: tuple[float, float, float],
    *,
    halo: bool = True,
) -> None:
    """One swatch: an optional white halo circle, then the real color circle —
    reproducing Hues.pdf's halo+fill pair pattern."""
    if halo:
        page.draw_circle((cx, cy), radius + 2, fill=(1, 1, 1), color=None)
    page.draw_circle((cx, cy), radius, fill=fill, color=None)


def _insert_label(
    page: fitz.Page, cx: float, cy: float, lines: list[str], *, fontsize: float = 7
) -> None:
    """Stack label lines vertically, centered near (cx, cy) — reproducing
    Hues.pdf's name(+code) text laid out inside the swatch shape itself."""
    line_height = fontsize * 1.3
    top = cy - (len(lines) - 1) * line_height / 2
    for i, text in enumerate(lines):
        x = cx - len(text) * fontsize * 0.32
        y = top + i * line_height
        page.insert_text((x, y), text, fontsize=fontsize)


def _pdf_bytes(doc: fitz.Document) -> bytes:
    data = doc.tobytes()
    doc.close()
    return data


def _embed_image(page: fitz.Page, x0: float, y0: float, size: float, rgb) -> None:
    px = round(size)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, px, px), False)
    pix.set_rect(pix.irect, rgb)
    page.insert_image(fitz.Rect(x0, y0, x0 + size, y0 + size), pixmap=pix)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestBasicExtraction:
    def test_extracts_name_code_hex_from_halo_pair(self):
        doc, page = _new_page()
        _draw_swatch(page, 100, 100, 28, (0.8, 0.2, 0.2))
        _insert_label(page, 100, 100, ["Bold Red", "010"])

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert result.needs_fallback is False
        assert len(result.swatches) == 1
        swatch = result.swatches[0]
        assert swatch.name == "Bold Red"
        assert swatch.code == "010"
        assert swatch.hex == "#CC3333"

    def test_picks_non_white_fill_not_halo(self):
        """Regression: the halo circle (white, drawn first) must never be
        mistaken for the swatch's real color."""
        doc, page = _new_page()
        _draw_swatch(page, 100, 100, 28, (0.1, 0.6, 0.2))
        _insert_label(page, 100, 100, ["Forest"])

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert len(result.swatches) == 1
        assert result.swatches[0].hex != "#FFFFFF"
        assert result.swatches[0].hex == "#1A9933"

    def test_swatch_without_code_still_extracts_name(self):
        doc, page = _new_page()
        _draw_swatch(page, 100, 100, 28, (0.2, 0.3, 0.8))
        _insert_label(page, 100, 100, ["Ultramarine"])

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert len(result.swatches) == 1
        assert result.swatches[0].name == "Ultramarine"
        assert result.swatches[0].code is None

    @pytest.mark.parametrize("code", ["009", "511", "S20", "E001", "F06"])
    def test_recognizes_numeric_and_letter_prefixed_codes(self, code):
        doc, page = _new_page()
        _draw_swatch(page, 100, 100, 28, (0.5, 0.4, 0.1))
        _insert_label(page, 100, 100, ["Sample Name", code])

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert result.swatches[0].code == code
        assert code not in result.swatches[0].name

    def test_multi_swatch_page(self):
        doc, page = _new_page(width=400, height=200)
        _draw_swatch(page, 80, 100, 28, (0.9, 0.1, 0.1))
        _insert_label(page, 80, 100, ["Red"])
        _draw_swatch(page, 220, 100, 28, (0.1, 0.9, 0.1))
        _insert_label(page, 220, 100, ["Green"])
        _draw_swatch(page, 340, 100, 28, (0.1, 0.1, 0.9))
        _insert_label(page, 340, 100, ["Blue"])

        result = extract_vector_swatches(_pdf_bytes(doc))

        names = {s.name for s in result.swatches}
        assert names == {"Red", "Green", "Blue"}


# ---------------------------------------------------------------------------
# Regressions found against the real Hues.pdf reference chart
# ---------------------------------------------------------------------------


class TestLabelIsolation:
    def test_tight_row_spacing_does_not_bleed_between_swatches(self):
        """Regression: a radius-based label search corrupted names in
        Hues.pdf's densely-packed rows by pulling in the neighboring
        swatch's words. Containment-in-bbox must isolate each swatch's
        3-line wrapped label even when rows sit close together."""
        doc, page = _new_page(width=200, height=300)
        _draw_swatch(page, 100, 90, 28, (0.9, 0.8, 0.2))
        _insert_label(page, 100, 90, ["Bright", "Yellow", "020"])
        _draw_swatch(page, 100, 200, 28, (0.1, 0.3, 0.6))
        _insert_label(page, 100, 200, ["Dark", "Blue", "030"])

        result = extract_vector_swatches(_pdf_bytes(doc))

        by_code = {s.code: s for s in result.swatches}
        assert by_code["020"].name == "Bright Yellow"
        assert by_code["030"].name == "Dark Blue"
        # neither label may contain a word belonging to the other swatch
        assert "Blue" not in by_code["020"].name
        assert "Yellow" not in by_code["030"].name

    def test_jittered_duplicate_text_layer_does_not_double_words(self):
        """Regression: Hues.pdf renders every label via two overlapping text
        objects offset by ~0.01-0.06pt, not pixel-identical — a naive
        rounding-hash dedup missed some pairs depending on where the jitter
        fell relative to the rounding boundary, corrupting names with a
        repeated word."""
        doc, page = _new_page()
        _draw_swatch(page, 100, 100, 28, (0.3, 0.3, 0.3))
        _insert_label(page, 100, 100, ["Storm Grey"])
        # a second, sub-pixel-offset copy at the same position _insert_label
        # used for its single "Storm Grey" line (cx=100, fontsize=7 ->
        # x = 100 - 10*7*0.32 = 77.6, y = 100), jittered by ~0.03pt.
        page.insert_text((77.63, 100.02), "Storm Grey", fontsize=7)

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert len(result.swatches) == 1
        assert result.swatches[0].name == "Storm Grey"


class TestNonSwatchShapesExcluded:
    def test_ignores_full_page_background_rect(self):
        doc, page = _new_page()
        page.draw_rect(page.rect, fill=(0.9, 0.9, 0.7), color=None)
        _draw_swatch(page, 100, 100, 28, (0.4, 0.1, 0.6))
        _insert_label(page, 100, 100, ["Violet"])

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert len(result.swatches) == 1
        assert result.swatches[0].name == "Violet"

    def test_ignores_elongated_decorative_shapes(self):
        """Regression: a real chart's ribbon-shaped category header banners
        and wide background column panels (~4:1 aspect, well within the area
        floor) were misread as swatches before an aspect-ratio bound was
        added — this covers both."""
        doc, page = _new_page(width=400, height=300)
        # a wide, panel-sized white background block (~4:1 aspect)
        page.draw_rect(fitz.Rect(0, 0, 400, 60), fill=(1, 1, 1), color=None)
        # a wide, ribbon-sized dark banner fragment (~4.3:1 aspect)
        page.draw_rect(fitz.Rect(20, 20, 150, 50), fill=(0.5, 0.1, 0.1), color=None)
        _draw_swatch(page, 200, 200, 28, (0.2, 0.6, 0.6))
        _insert_label(page, 200, 200, ["Teal"])

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert len(result.swatches) == 1
        assert result.swatches[0].name == "Teal"

    def test_ignores_solo_white_shape(self):
        """A lone white filled shape (no paired real-color member in its
        cluster) is a background/placeholder artifact, never a swatch."""
        doc, page = _new_page()
        page.draw_circle((100, 100), 28, fill=(1, 1, 1), color=None)

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert result.swatches == []


# ---------------------------------------------------------------------------
# Fallback signaling (STUDIO-332 routing)
# ---------------------------------------------------------------------------


class TestFallbackSignal:
    def test_falls_back_with_embedded_image_count_when_no_vector_swatches(self):
        """Regression: a chart whose swatches are individually-embedded
        raster images (the real Army Painter case) must not be silently
        treated as empty — it should signal fallback with a nonzero
        embedded-image count so STUDIO-332 can route to its cheaper
        embedded-image sub-path."""
        doc, page = _new_page(width=300, height=300)
        for i in range(4):
            _embed_image(page, 20 + i * 60, 20, 40, (200, 50, 50))

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert result.needs_fallback is True
        assert result.embedded_image_count == 4
        assert result.swatches == []

    def test_falls_back_with_zero_count_when_genuinely_empty(self):
        doc, page = _new_page()

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert result.needs_fallback is True
        assert result.embedded_image_count == 0
        assert result.swatches == []

    def test_large_logo_sized_images_not_counted_as_swatches(self):
        """A large embedded image (e.g. a logo/footer graphic, like Hues.pdf's
        own ~106x106pt images) sits outside the swatch-chip size band and
        must not inflate the embedded-image signal."""
        doc, page = _new_page(width=300, height=300)
        _embed_image(page, 20, 20, 200, (10, 10, 10))

        result = extract_vector_swatches(_pdf_bytes(doc))

        assert result.needs_fallback is True
        assert result.embedded_image_count == 0

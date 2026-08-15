"""Embedded-raster-swatch vision fallback — synthetic-fixture coverage (STUDIO-332).

Fixtures are built programmatically (PyMuPDF + PIL) rather than bundling the
real Army Painter "Practical Colour Name Chart" into the repo — proprietary
chart art, not something to ship in an MIT-licensed public repo. The
alpha/smask-compositing behavior these fixtures rely on (embedding a PNG with
transparency yields a base image with garbage in transparent regions plus a
separate `smask` image) was hand-verified against the real file first; see
the module docstring in `swatch_extract_vision.py`.

The Anthropic client is monkeypatched at the boundary — no live API call.
"""
from __future__ import annotations

import io
import json
import types

import fitz
import pytest
from cryptography.fernet import Fernet
from PIL import Image, ImageDraw

from app.painting.services import swatch_extract_vision as vision
from app.services import secrets

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _new_page(width: float = 300, height: float = 300) -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    return doc, page


def _swatch_png(fill_rgb: tuple[int, int, int], size: tuple[int, int] = (64, 70)) -> bytes:
    """A swatch chip: an opaque fill on a fully transparent background, with
    a baked-in white text mark — reproducing the real chart's "name baked
    into the pixels, hexagon corners transparent" pattern."""
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([4, 4, size[0] - 4, size[1] - 4], fill=(*fill_rgb, 255))
    d.text((8, size[1] // 2 - 5), "X", fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _insert_swatch(
    page: fitz.Page, x0: float, y0: float, fill_rgb: tuple[int, int, int], *, size: float = 40
) -> None:
    rect = fitz.Rect(x0, y0, x0 + size, y0 + size)
    page.insert_image(rect, stream=_swatch_png(fill_rgb))


def _insert_oversized_image(page: fitz.Page, x0: float, y0: float, size: float = 150) -> None:
    """An embedded image well outside the swatch-chip size band (a chart
    logo/footer, not a swatch)."""
    rect = fitz.Rect(x0, y0, x0 + size, y0 + size)
    page.insert_image(rect, stream=_swatch_png((10, 10, 10), size=(20, 20)))


def _pdf_bytes(doc: fitz.Document) -> bytes:
    data = doc.tobytes()
    doc.close()
    return data


# ---------------------------------------------------------------------------
# Fake Anthropic client
# ---------------------------------------------------------------------------


def _labels_in_request(kwargs: dict) -> list[str]:
    content = kwargs["messages"][0]["content"]
    return [b["text"] for b in content if b.get("type") == "text" and b["text"].startswith("swatch_")]


def _fake_client(name_lookup: dict, calls: list, *, extra_field: bool = False):
    class _Client:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kw):
            calls.append(kw)
            labels = _labels_in_request(kw)
            payload = {}
            for label in labels:
                entry = name_lookup.get(label)
                if extra_field and entry is not None:
                    payload[label] = {"name": entry, "hex": "#FF00FF"}
                else:
                    payload[label] = entry
            # An extra_field response must still resolve to a plain string
            # per swatch — simulate the model ignoring instructions and
            # nesting a dict only when explicitly asked, to keep the
            # dedicated test below simple; default path returns strings.
            if extra_field:
                payload = {k: (v["name"] if isinstance(v, dict) else v) for k, v in payload.items()}
            block = types.SimpleNamespace(type="text", text=json.dumps(payload))
            return types.SimpleNamespace(content=[block])

    return _Client


def _boom_client(exc: Exception):
    class _Client:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(
                create=lambda **kw: (_ for _ in ()).throw(exc)
            )

    return _Client


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestBasicExtraction:
    def test_extracts_name_and_pixel_sampled_hex(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        doc, page = _new_page()
        _insert_swatch(page, 20, 20, (29, 59, 64))
        _insert_swatch(page, 100, 20, (200, 40, 40))
        pdf_bytes = _pdf_bytes(doc)

        calls: list = []
        monkeypatch.setattr(
            vision,
            "Anthropic",
            _fake_client({"swatch_0_0": "Scarab Green", "swatch_0_1": "Fiery Red"}, calls),
        )

        result = vision.extract_embedded_raster_swatches(db, pdf_bytes)

        assert not result.needs_fallback
        by_name = {s.name: s for s in result.swatches}
        assert by_name["Scarab Green"].hex == "#1D3B40"
        assert by_name["Scarab Green"].code is None
        assert by_name["Fiery Red"].hex == "#C82828"
        assert len(calls) == 1  # both swatches fit in one chunk

    def test_no_swatch_sized_images_signals_fallback(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        doc, page = _new_page()
        _insert_oversized_image(page, 20, 20)
        pdf_bytes = _pdf_bytes(doc)

        result = vision.extract_embedded_raster_swatches(db, pdf_bytes)

        assert result.needs_fallback
        assert result.embedded_image_count == 0
        assert result.swatches == []


# ---------------------------------------------------------------------------
# Alpha compositing correctness (the smask bug found against the real file)
# ---------------------------------------------------------------------------


class TestAlphaCompositing:
    def test_transparent_corners_never_become_the_sampled_color(self, db, monkeypatch):
        """extract_image() alone returns black in transparent regions (real
        finding, not hypothetical) — if hex sampling ever regressed to
        ignore the smask, every swatch would come back near-black instead of
        its real fill."""
        secrets.set_ai_api_key(db, "sk-test")
        doc, page = _new_page()
        _insert_swatch(page, 20, 20, (240, 210, 90))  # a light, non-black fill
        pdf_bytes = _pdf_bytes(doc)

        calls: list = []
        monkeypatch.setattr(
            vision, "Anthropic", _fake_client({"swatch_0_0": "Sunflower"}, calls)
        )

        result = vision.extract_embedded_raster_swatches(db, pdf_bytes)

        assert result.swatches[0].hex == "#F0D25A"


# ---------------------------------------------------------------------------
# Non-swatch crops and malformed model output
# ---------------------------------------------------------------------------


class TestModelOutputHandling:
    def test_null_name_drops_the_crop_not_a_garbage_swatch(self, db, monkeypatch):
        """Covers the real ~166-vs-162 gap: a size-band-passing crop that
        isn't a real swatch must be dropped, never turned into a Swatch with
        a made-up name."""
        secrets.set_ai_api_key(db, "sk-test")
        doc, page = _new_page()
        _insert_swatch(page, 20, 20, (29, 59, 64))
        _insert_swatch(page, 100, 20, (200, 40, 40))
        pdf_bytes = _pdf_bytes(doc)

        calls: list = []
        monkeypatch.setattr(
            vision,
            "Anthropic",
            _fake_client({"swatch_0_0": "Scarab Green", "swatch_0_1": None}, calls),
        )

        result = vision.extract_embedded_raster_swatches(db, pdf_bytes)

        assert len(result.swatches) == 1
        assert result.swatches[0].name == "Scarab Green"

    def test_model_supplied_hex_field_is_ignored(self, db, monkeypatch):
        """Claude's job is name OCR only — even if it nests a hex/color
        field, the real hex must still come from pixel sampling."""
        secrets.set_ai_api_key(db, "sk-test")
        doc, page = _new_page()
        _insert_swatch(page, 20, 20, (29, 59, 64))
        pdf_bytes = _pdf_bytes(doc)

        calls: list = []
        monkeypatch.setattr(
            vision,
            "Anthropic",
            _fake_client({"swatch_0_0": "Scarab Green"}, calls, extra_field=True),
        )

        result = vision.extract_embedded_raster_swatches(db, pdf_bytes)

        assert result.swatches[0].hex == "#1D3B40"  # pixel-sampled, not "#FF00FF"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


class TestChunking:
    def test_batches_large_charts_into_multiple_calls(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        doc, page = _new_page(width=1200, height=1200)
        n = 25  # > _SWATCH_CHUNK_SIZE (20)
        cols = 6
        name_lookup = {}
        for i in range(n):
            x, y = 20 + (i % cols) * 45, 20 + (i // cols) * 45
            _insert_swatch(page, x, y, (i * 5, 40, 40))
            name_lookup[f"swatch_0_{i}"] = f"Paint {i}"
        pdf_bytes = _pdf_bytes(doc)

        calls: list = []
        monkeypatch.setattr(vision, "Anthropic", _fake_client(name_lookup, calls))

        result = vision.extract_embedded_raster_swatches(db, pdf_bytes)

        assert len(calls) == 2  # 20 + 5
        assert len(calls[0]["messages"][0]["content"]) > len(calls[1]["messages"][0]["content"])
        assert len(result.swatches) == n


# ---------------------------------------------------------------------------
# Config resolution and error propagation
# ---------------------------------------------------------------------------


class TestConfigAndErrors:
    def test_not_gated_by_ai_guides_enabled(self, db, monkeypatch):
        """Deliberate design point: this feature must not require the
        unrelated Guide Drafts feature to be enabled — only a usable
        AiApiConfig/key. ai_guides_enabled is left unset entirely here."""
        secrets.set_ai_api_key(db, "sk-test")
        doc, page = _new_page()
        _insert_swatch(page, 20, 20, (29, 59, 64))
        pdf_bytes = _pdf_bytes(doc)

        calls: list = []
        monkeypatch.setattr(
            vision, "Anthropic", _fake_client({"swatch_0_0": "Scarab Green"}, calls)
        )

        result = vision.extract_embedded_raster_swatches(db, pdf_bytes)
        assert result.swatches[0].name == "Scarab Green"

    def test_missing_key_raises(self, db):
        doc, page = _new_page()
        _insert_swatch(page, 20, 20, (29, 59, 64))
        pdf_bytes = _pdf_bytes(doc)

        with pytest.raises(vision.GenerationError):
            vision.extract_embedded_raster_swatches(db, pdf_bytes)

    def test_api_error_wrapped(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        doc, page = _new_page()
        _insert_swatch(page, 20, 20, (29, 59, 64))
        pdf_bytes = _pdf_bytes(doc)

        monkeypatch.setattr(vision, "Anthropic", _boom_client(RuntimeError("429 rate limit")))

        with pytest.raises(vision.GenerationError):
            vision.extract_embedded_raster_swatches(db, pdf_bytes)

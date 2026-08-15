"""Photo / scanned-page vision fallback — synthetic-fixture coverage (STUDIO-381).

No real reference photo/scan exists for this sub-case (unlike STUDIO-331/332,
both verified against a real manufacturer chart) — fixtures here are
synthetic PIL-drawn images and PyMuPDF-built PDFs. The Anthropic client is
monkeypatched at the boundary — no live API call.
"""
from __future__ import annotations

import io
import json
import types

import fitz
import pytest
from cryptography.fernet import Fernet
from PIL import Image, ImageDraw

from app.painting.services import swatch_extract_photo as photo
from app.services import secrets

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _photo_bytes(size=(400, 300), *, fmt="PNG") -> bytes:
    """A flat RGB image with a couple of distinct color patches — stands in
    for a photo of two paint swatches at known pixel locations."""
    im = Image.new("RGB", size, (240, 240, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, 140, 140], fill=(29, 59, 64))   # left patch
    d.rectangle([260, 40, 360, 140], fill=(78, 60, 57))  # right patch
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


def _blank_pdf_bytes(width: float = 300, height: float = 300) -> bytes:
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    data = doc.tobytes()
    doc.close()
    return data


def _bbox_pct(x0, y0, x1, y1, size=(400, 300)) -> list[float]:
    w, h = size
    return [x0 / w, y0 / h, x1 / w, y1 / h]


# ---------------------------------------------------------------------------
# Fake Anthropic client
# ---------------------------------------------------------------------------


def _fake_client(swatches: list, calls: list):
    """Returns a fixed {"swatches": [...]} payload regardless of image
    content — the point of these tests is the bbox/hex plumbing around the
    call, not the vision call itself."""
    class _Client:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kw):
            calls.append(kw)
            block = types.SimpleNamespace(type="text", text=json.dumps({"swatches": swatches}))
            return types.SimpleNamespace(content=[block])

    return _Client


def _boom_client(exc: Exception):
    class _Client:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kw):
            raise exc

    return _Client


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


# ---------------------------------------------------------------------------
# Photo upload: happy path + pixel-sampled hex
# ---------------------------------------------------------------------------


class TestPhotoExtraction:
    def test_extracts_name_and_pixel_sampled_hex_not_model_supplied(self, db, monkeypatch):
        """The model's response includes a `hex` field — it must be ignored;
        the returned hex must come from the fixture's actual pixels."""
        secrets.set_ai_api_key(db, "sk-test")
        calls: list = []
        monkeypatch.setattr(photo, "Anthropic", _fake_client(
            [{
                "name": "Mahogany",
                "bbox_pct": _bbox_pct(40, 40, 140, 140),
                "hex": "#FFFFFF",  # deliberately wrong — must be discarded
            }],
            calls,
        ))

        result = photo.extract_photo_swatches(db, _photo_bytes())

        assert result.needs_fallback is False
        assert len(result.swatches) == 1
        assert result.swatches[0].name == "Mahogany"
        assert result.swatches[0].code is None
        assert result.swatches[0].hex == "#1D3B40"
        assert len(calls) == 1  # one image, one call

    def test_multiple_swatches_in_one_image(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        monkeypatch.setattr(photo, "Anthropic", _fake_client(
            [
                {"name": "Mahogany", "bbox_pct": _bbox_pct(40, 40, 140, 140)},
                {"name": "Coal Black", "bbox_pct": _bbox_pct(260, 40, 360, 140)},
            ],
            [],
        ))

        result = photo.extract_photo_swatches(db, _photo_bytes())

        names = {s.name: s.hex for s in result.swatches}
        assert names == {"Mahogany": "#1D3B40", "Coal Black": "#4E3C39"}

    def test_null_name_entry_is_dropped(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        monkeypatch.setattr(photo, "Anthropic", _fake_client(
            [{"name": None, "bbox_pct": _bbox_pct(40, 40, 140, 140)}], [],
        ))

        result = photo.extract_photo_swatches(db, _photo_bytes())
        assert result.swatches == []

    def test_zero_swatches_found_is_a_clean_empty_result_not_needs_fallback(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        monkeypatch.setattr(photo, "Anthropic", _fake_client([], []))

        result = photo.extract_photo_swatches(db, _photo_bytes())
        assert result.swatches == []
        assert result.needs_fallback is False

    def test_malformed_bbox_shapes_are_skipped_not_fatal(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        monkeypatch.setattr(photo, "Anthropic", _fake_client(
            [
                {"name": "No bbox at all"},
                {"name": "Wrong length", "bbox_pct": [0.1, 0.1, 0.2]},
                {"name": "Non-numeric", "bbox_pct": ["a", "b", "c", "d"]},
                "not even a dict",
                {"name": "Good one", "bbox_pct": _bbox_pct(40, 40, 140, 140)},
            ],
            [],
        ))

        result = photo.extract_photo_swatches(db, _photo_bytes())
        assert [s.name for s in result.swatches] == ["Good one"]

    def test_out_of_range_bbox_is_clamped_not_dropped(self, db, monkeypatch):
        """A model returning a slightly out-of-[0,1] or flipped box shouldn't
        be treated as a hard failure — clamp and sample what's left."""
        secrets.set_ai_api_key(db, "sk-test")
        monkeypatch.setattr(photo, "Anthropic", _fake_client(
            [{"name": "Flipped/out-of-range", "bbox_pct": [0.35, 1.2, -0.1, 0.1333]}], [],
        ))

        result = photo.extract_photo_swatches(db, _photo_bytes())
        assert len(result.swatches) == 1
        assert result.swatches[0].name == "Flipped/out-of-range"

    def test_degenerate_point_bbox_never_crashes_on_an_empty_crop(self, db, monkeypatch):
        """A zero-width/height box still floors to a minimal 1x1px crop
        rather than slicing an empty numpy array — the point of this test is
        that it doesn't raise, not that the resulting hex is meaningful."""
        secrets.set_ai_api_key(db, "sk-test")
        monkeypatch.setattr(photo, "Anthropic", _fake_client(
            [{"name": "Point, not a box", "bbox_pct": [0.5, 0.5, 0.5, 0.5]}], [],
        ))

        result = photo.extract_photo_swatches(db, _photo_bytes())
        assert len(result.swatches) == 1


# ---------------------------------------------------------------------------
# Undecodable / oversized input
# ---------------------------------------------------------------------------


class TestUndecodableInput:
    def test_garbage_bytes_signal_needs_fallback_without_calling_ai(self, db, monkeypatch):
        calls: list = []
        monkeypatch.setattr(photo, "Anthropic", _fake_client([], calls))

        result = photo.extract_photo_swatches(db, b"not an image at all")

        assert result.needs_fallback is True
        assert result.swatches == []
        assert calls == []  # never even resolved an AI config

    def test_oversized_upload_signals_needs_fallback(self, db, monkeypatch):
        calls: list = []
        monkeypatch.setattr(photo, "Anthropic", _fake_client([], calls))
        monkeypatch.setattr(photo, "_MAX_BYTES", 10)

        result = photo.extract_photo_swatches(db, _photo_bytes())

        assert result.needs_fallback is True
        assert calls == []

    def test_empty_bytes_signal_needs_fallback(self, db):
        result = photo.extract_photo_swatches(db, b"")
        assert result.needs_fallback is True


# ---------------------------------------------------------------------------
# PDF page rasterization
# ---------------------------------------------------------------------------


class TestPdfPagePhotos:
    def test_rasterizes_a_blank_page_and_runs_extraction(self, db, monkeypatch):
        """A genuinely blank scanned page: rasterizes fine, the vision call
        runs, and finding nothing is a legitimate empty result."""
        secrets.set_ai_api_key(db, "sk-test")
        calls: list = []
        monkeypatch.setattr(photo, "Anthropic", _fake_client([], calls))

        result = photo.extract_pdf_page_photos(db, _blank_pdf_bytes())

        assert result.needs_fallback is False
        assert result.swatches == []
        assert len(calls) == 1  # one page, one call

    def test_extracts_swatches_from_a_rasterized_page(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        # Draw directly on a PDF page (a vector shape here just stands in for
        # "some content the rasterizer needs to render"), then rasterize it.
        doc = fitz.open()
        page = doc.new_page(width=300, height=300)
        page.draw_rect(fitz.Rect(20, 20, 120, 120), fill=(0.1, 0.6, 0.2), color=None)
        pdf_bytes = doc.tobytes()
        doc.close()

        # Full-image box — resolution-independent, so the actual rasterized
        # pixel size (a function of _RASTER_DPI, not asserted here) doesn't matter.
        monkeypatch.setattr(photo, "Anthropic", _fake_client(
            [{"name": "Rasterized Swatch", "bbox_pct": [0.0, 0.0, 1.0, 1.0]}],
            [],
        ))

        result = photo.extract_pdf_page_photos(db, pdf_bytes)
        assert [s.name for s in result.swatches] == ["Rasterized Swatch"]

    def test_garbage_pdf_bytes_signal_needs_fallback(self, db):
        result = photo.extract_pdf_page_photos(db, b"not a pdf")
        assert result.needs_fallback is True


# ---------------------------------------------------------------------------
# API-key / request-failure propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_missing_key_raises(self, db):
        with pytest.raises(photo.GenerationError):
            photo.extract_photo_swatches(db, _photo_bytes())

    def test_api_error_wrapped(self, db, monkeypatch):
        secrets.set_ai_api_key(db, "sk-test")
        monkeypatch.setattr(photo, "Anthropic", _boom_client(RuntimeError("429 rate limit")))

        with pytest.raises(photo.GenerationError):
            photo.extract_photo_swatches(db, _photo_bytes())

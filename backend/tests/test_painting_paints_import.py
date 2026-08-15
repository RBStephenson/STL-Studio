"""Swatch-chart import endpoints — extract-colors and bulk-import (STUDIO-333).

Both endpoints are gated by the `paint_swatch_import_enabled` app setting,
default off. PDF fixtures are built the same way as
test_painting_swatch_extract.py / test_painting_swatch_extract_vision.py —
synthetic PyMuPDF/PIL-built charts, no proprietary art.
"""
from __future__ import annotations

import io
import json
import types

import fitz
import pytest
from cryptography.fernet import Fernet
from PIL import Image, ImageDraw

from app.models import AppSetting
from app.painting.models import PaintBrand, PaintLine
from app.painting.services import swatch_extract_vision as vision
from app.services import secrets


def _enable_import(db):
    db.add(AppSetting(key="paint_swatch_import_enabled", value=True))
    db.commit()


def _make_line(db, code_pattern=None):
    brand = PaintBrand(name="Monument Hobbies")
    db.add(brand)
    db.flush()
    line = PaintLine(brand_id=brand.id, name="Pro Acryl Standard", code_pattern=code_pattern)
    db.add(line)
    db.commit()
    return line


# ---------------------------------------------------------------------------
# PDF fixture builders (vector path)
# ---------------------------------------------------------------------------


def _vector_pdf_bytes() -> bytes:
    """One halo+fill swatch circle with its label centered inside the
    swatch's own bbox — same layout swatch_extract.py's label-assignment
    (bbox-containment) actually requires; see test_painting_swatch_extract.py."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.draw_circle((60, 60), 22, fill=(1, 1, 1), color=None)
    page.draw_circle((60, 60), 20, fill=(0.1, 0.6, 0.2), color=None)
    for i, text in enumerate(["Coal Black", "009"]):
        y = 60 - 4.55 + i * 9.1
        x = 60 - len(text) * 7 * 0.32
        page.insert_text((x, y), text, fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


# ---------------------------------------------------------------------------
# PDF fixture builders (embedded-raster path — STUDIO-332)
# ---------------------------------------------------------------------------


def _swatch_png(fill_rgb, size=(64, 70)) -> bytes:
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([4, 4, size[0] - 4, size[1] - 4], fill=(*fill_rgb, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _embedded_raster_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(fitz.Rect(20, 20, 60, 60), stream=_swatch_png((29, 59, 64)))
    data = doc.tobytes()
    doc.close()
    return data


def _empty_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    data = doc.tobytes()
    doc.close()
    return data


def _fake_vision_client(name_lookup: dict):
    class _Client:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kw):
            content = kw["messages"][0]["content"]
            labels = [
                b["text"] for b in content
                if b.get("type") == "text" and b["text"].startswith("swatch_")
            ]
            payload = {label: name_lookup.get(label) for label in labels}
            block = types.SimpleNamespace(type="text", text=json.dumps(payload))
            return types.SimpleNamespace(content=[block])

    return _Client


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


def _upload(client, data: bytes, filename="chart.pdf"):
    return client.post(
        "/painting/paints/extract-colors",
        files={"file": (filename, data, "application/pdf")},
    )


# ---------------------------------------------------------------------------
# extract-colors: feature flag
# ---------------------------------------------------------------------------


class TestExtractColorsFlag:
    def test_403_when_flag_off(self, client, db):
        r = _upload(client, _vector_pdf_bytes())
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# extract-colors: dispatch
# ---------------------------------------------------------------------------


class TestExtractColorsDispatch:
    def test_vector_swatches_returned_directly(self, client, db):
        _enable_import(db)
        r = _upload(client, _vector_pdf_bytes())
        assert r.status_code == 200
        body = r.json()
        assert body["unsupported_reason"] is None
        assert body["swatches"] == [{"name": "Coal Black", "code": "009", "hex": "#1A9933"}]

    def test_embedded_raster_falls_back_to_vision(self, client, db, monkeypatch):
        _enable_import(db)
        secrets.set_ai_api_key(db, "sk-test")
        monkeypatch.setattr(
            vision, "Anthropic", _fake_vision_client({"swatch_0_0": "Scarab Green"})
        )
        r = _upload(client, _embedded_raster_pdf_bytes())
        assert r.status_code == 200
        body = r.json()
        assert body["unsupported_reason"] is None
        assert body["swatches"] == [{"name": "Scarab Green", "code": None, "hex": "#1D3B40"}]

    def test_not_a_pdf_returns_unsupported_reason(self, client, db):
        _enable_import(db)
        r = client.post(
            "/painting/paints/extract-colors",
            files={"file": ("photo.jpg", b"not a pdf at all", "image/jpeg")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["swatches"] == []
        assert body["unsupported_reason"] is not None

    def test_pdf_with_no_swatches_at_all_returns_unsupported_reason(self, client, db):
        _enable_import(db)
        r = _upload(client, _empty_pdf_bytes())
        assert r.status_code == 200
        body = r.json()
        assert body["swatches"] == []
        assert body["unsupported_reason"] is not None

    def test_vision_finds_zero_real_swatches_is_a_clean_empty_result(self, client, db, monkeypatch):
        """Embedded images were found (routes into the vision path) but every
        crop OCR'd as a non-swatch — a legitimate empty result, not an error."""
        _enable_import(db)
        secrets.set_ai_api_key(db, "sk-test")
        monkeypatch.setattr(vision, "Anthropic", _fake_vision_client({"swatch_0_0": None}))
        r = _upload(client, _embedded_raster_pdf_bytes())
        assert r.status_code == 200
        body = r.json()
        assert body["swatches"] == []
        assert body["unsupported_reason"] is None

    def test_missing_ai_key_maps_to_503(self, client, db):
        _enable_import(db)
        # No AI key configured at all.
        r = _upload(client, _embedded_raster_pdf_bytes())
        assert r.status_code == 503

    def test_ai_request_failure_maps_to_502(self, client, db, monkeypatch):
        _enable_import(db)
        secrets.set_ai_api_key(db, "sk-test")

        class _Boom:
            def __init__(self, *a, **k):
                self.messages = types.SimpleNamespace(
                    create=lambda **kw: (_ for _ in ()).throw(RuntimeError("429"))
                )

        monkeypatch.setattr(vision, "Anthropic", _Boom)
        r = _upload(client, _embedded_raster_pdf_bytes())
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# bulk-import: feature flag
# ---------------------------------------------------------------------------


class TestBulkImportFlag:
    def test_403_when_flag_off(self, client, db):
        line = _make_line(db)
        r = client.post("/painting/paints/bulk-import", json={
            "paint_line_id": line.id,
            "items": [{"name": "Coal Black", "code": "009", "hex": "#199933"}],
        })
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# bulk-import: creation, defaults, partial success
# ---------------------------------------------------------------------------


class TestBulkImport:
    def test_creates_paints_with_defaults(self, client, db):
        _enable_import(db)
        line = _make_line(db)
        r = client.post("/painting/paints/bulk-import", json={
            "paint_line_id": line.id,
            "items": [{"name": "Coal Black", "code": "009", "hex": "#199933"}],
        })
        assert r.status_code == 200
        body = r.json()
        assert len(body["created"]) == 1
        created = body["created"][0]
        assert created["code"] == "009"
        assert created["finish"] == "matte"
        assert created["matchable"] is True
        assert created["owned"] is True
        assert body["skipped"] == []

    def test_missing_code_falls_back_to_name(self, client, db):
        _enable_import(db)
        line = _make_line(db)
        r = client.post("/painting/paints/bulk-import", json={
            "paint_line_id": line.id,
            "items": [{"name": "Scarab Green", "hex": "#1D3B40"}],
        })
        assert r.status_code == 200
        assert r.json()["created"][0]["code"] == "Scarab Green"

    def test_invalid_code_pattern_is_skipped_not_fatal(self, client, db):
        _enable_import(db)
        line = _make_line(db, code_pattern=r"^\d{3}$")
        r = client.post("/painting/paints/bulk-import", json={
            "paint_line_id": line.id,
            "items": [
                {"name": "Coal Black", "code": "009"},
                {"name": "Bad Code", "code": "not-numeric"},
            ],
        })
        assert r.status_code == 200
        body = r.json()
        assert len(body["created"]) == 1
        assert body["created"][0]["name"] == "Coal Black"
        assert len(body["skipped"]) == 1
        assert body["skipped"][0]["name"] == "Bad Code"

    def test_duplicate_code_within_batch_is_skipped(self, client, db):
        _enable_import(db)
        line = _make_line(db)
        r = client.post("/painting/paints/bulk-import", json={
            "paint_line_id": line.id,
            "items": [
                {"name": "Coal Black", "code": "009"},
                {"name": "Coal Black Again", "code": "009"},
            ],
        })
        assert r.status_code == 200
        body = r.json()
        assert len(body["created"]) == 1
        assert len(body["skipped"]) == 1
        assert "batch" in body["skipped"][0]["reason"]

    def test_duplicate_code_against_existing_paint_is_skipped(self, client, db):
        _enable_import(db)
        line = _make_line(db)
        client.post("/painting/paints/bulk-import", json={
            "paint_line_id": line.id,
            "items": [{"name": "Coal Black", "code": "009"}],
        })
        r = client.post("/painting/paints/bulk-import", json={
            "paint_line_id": line.id,
            "items": [{"name": "Coal Black Reimported", "code": "009"}],
        })
        body = r.json()
        assert body["created"] == []
        assert len(body["skipped"]) == 1
        assert "already exists" in body["skipped"][0]["reason"]

    def test_unknown_line_404s(self, client, db):
        _enable_import(db)
        r = client.post("/painting/paints/bulk-import", json={
            "paint_line_id": 999999,
            "items": [{"name": "Coal Black", "code": "009"}],
        })
        assert r.status_code == 404

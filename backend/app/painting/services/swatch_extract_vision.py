"""Embedded-raster-swatch vision fallback (STUDIO-332, epic STUDIO-329).

Handles the sub-case of Paint Shelf's swatch-chart import where a chart's
swatches aren't real vector shapes (STUDIO-331's job) but individually
embedded raster images, each with the paint name baked directly into its
pixels — verified 2026-08-15 against the real Army Painter Warpaints Fanatic
"Practical Colour Name Chart" (162 hexagon swatches, no paint codes). PyMuPDF
already gives the exact bounding box and xref of every such image, so no
photo-style localization is needed here — that's STUDIO-381's job, for a
physical-rack photo or scanned page where no PDF structure exists at all.
Claude vision's only role in this module is OCR: reading the printed name off
each small crop. Hex is always pixel-sampled from the crop itself, never
trusted from the model.

Compositing note (verified against the real file, not assumed):
`Document.extract_image()` does **not** composite an image's soft mask — the
returned RGB has garbage (observed: pure black) in transparent regions, not
white and not alpha. Real per-pixel transparency lives in a second image at
`extract_image(xref)["smask"]`. Pixel sampling here gates on that alpha
channel, never on a near-white color heuristic — a color-based filter would
misread the black-corner artifact as real fill, and would wrongly exclude any
paint whose true color is genuinely dark.

A chart's "practical name" text (a second, human-friendly name Army Painter
prints beside each swatch, positioned outside the swatch image and not to be
confused with the paint name) is never read at all by this module — the paint
name comes only from OCR-ing the swatch image itself, so there is no code path
that could pick the practical name up by mistake.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import fitz  # pymupdf — AGPL-3.0, see repo NOTICE
import numpy as np
from anthropic import Anthropic
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.painting.services.generation import (
    GenerationError,
    parse_json_object,
    resolve_anthropic_config,
    text_from_response,
)
from app.painting.services.swatch_extract import ExtractionResult, Swatch

# --- Tuning constants -------------------------------------------------------
# Same swatch-chip size band as swatch_extract.py's _EMBEDDED_SWATCH_MIN_PT /
# _EMBEDDED_SWATCH_MAX_PT (duplicated, not cross-imported — private to that
# module, and re-deriving it here would be a worse coupling than repeating
# two numbers). Verified against the real Army Painter chart: 166 embedded
# images pass this band against 162 real swatches — a handful of non-swatch
# near-misses are expected and are dropped downstream by OCR returning null
# for them, not filtered here by count.
_EMBEDDED_SWATCH_MIN_PT = 15.0
_EMBEDDED_SWATCH_MAX_PT = 90.0

# Pixels at/above this alpha are treated as the swatch's real fill; below is
# a transparent/antialiased edge. Not a near-white color test — see module
# docstring for why color-based background exclusion is wrong here.
_ALPHA_OPAQUE_THRESHOLD = 128

# Crops per Claude vision call. A single request holding all ~166 crops of a
# full chart risks an undocumented per-request image-count/payload ceiling;
# this is a conservative bound chosen without needing to find that ceiling,
# not a measured maximum.
_SWATCH_CHUNK_SIZE = 20

# Small: a chunk's reply is a compact JSON object of label -> short name.
_OCR_MAX_TOKENS = 2048

_FEATURE_LABEL = "Paint Shelf swatch import"
_AI_API_SETTING_KEY = "ai_guides_api"

_OCR_INSTRUCTIONS = (
    "Each image below is a small cropped swatch chip from a hobby paint color "
    "chart. The paint's name is printed directly on the swatch as baked-in "
    "text. For every swatch, read the printed name exactly as printed, "
    "correcting only obvious OCR noise. Respond with ONLY a JSON object "
    "mapping each swatch's label (given as a text block immediately before "
    'its image) to the name you read, e.g. {"swatch_0_3": "Scarab Green"}. '
    "If a labeled image is not actually a paint swatch (a decorative "
    "fragment, a logo, blank, etc.), map its label to null instead of "
    "guessing a name. Do not include a color/hex field — color is not your "
    "job."
)


@dataclass
class _Crop:
    label: str
    rgba: np.ndarray  # (h, w, 4) uint8, alpha already composited from smask


def extract_embedded_raster_swatches(db: Session, pdf_bytes: bytes) -> ExtractionResult:
    """Extract {name, code, hex} suggestions from a PDF whose swatches are
    individually embedded raster images.

    `code` is always None — this chart format carries no paint codes.
    `needs_fallback=True, embedded_image_count=0` signals "no swatch-sized
    embedded images found here at all" — most likely a photo or scanned page,
    which is STUDIO-381's job, not this module's.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        crops: list[_Crop] = []
        for page in doc:
            crops.extend(_page_swatch_crops(doc, page))
    finally:
        doc.close()

    if not crops:
        return ExtractionResult(needs_fallback=True, embedded_image_count=0)

    names = _ocr_names(db, crops)
    swatches = [
        Swatch(name=names[c.label], code=None, hex=_dominant_hex(c.rgba))
        for c in crops
        if c.label in names
    ]
    return ExtractionResult(swatches=swatches)


def _page_swatch_crops(doc: fitz.Document, page: fitz.Page) -> list[_Crop]:
    crops: list[_Crop] = []
    for i, info in enumerate(page.get_image_info(xrefs=True)):
        x0, y0, x1, y1 = info["bbox"]
        w, h = x1 - x0, y1 - y0
        if not (
            _EMBEDDED_SWATCH_MIN_PT <= w <= _EMBEDDED_SWATCH_MAX_PT
            and _EMBEDDED_SWATCH_MIN_PT <= h <= _EMBEDDED_SWATCH_MAX_PT
        ):
            continue
        rgba = _extract_rgba(doc, info["xref"])
        if rgba is None:
            continue
        crops.append(_Crop(label=f"swatch_{page.number}_{i}", rgba=rgba))
    return crops


def _extract_rgba(doc: fitz.Document, xref: int) -> np.ndarray | None:
    """Composite an embedded image with its soft mask into an (h, w, 4) uint8
    RGBA array. Returns None for a candidate PyMuPDF/PIL can't actually
    decode (untrusted PDF content — verified against the real Army Painter
    file, which has one image-info entry passing the size band whose xref
    PyMuPDF itself rejects as "bad xref") rather than aborting the whole
    extraction over one bad crop."""
    try:
        img = doc.extract_image(xref)
    except (ValueError, RuntimeError):
        return None
    try:
        base = Image.open(io.BytesIO(img["image"])).convert("RGB")
    except (UnidentifiedImageError, OSError):
        return None

    smask_xref = img.get("smask")
    if smask_xref:
        try:
            smask_img = doc.extract_image(smask_xref)
            alpha = Image.open(io.BytesIO(smask_img["image"])).convert("L")
        except (ValueError, RuntimeError, UnidentifiedImageError, OSError):
            alpha = Image.new("L", base.size, 255)
        if alpha.size != base.size:
            alpha = alpha.resize(base.size)
    else:
        alpha = Image.new("L", base.size, 255)

    rgba = Image.merge("RGBA", (*base.split(), alpha))
    return np.asarray(rgba, dtype=np.uint8)


def _dominant_hex(rgba: np.ndarray) -> str:
    """The crop's most common color among opaque pixels.

    Verified against the real "Scarab Green" swatch: its true fill is ~64%
    of opaque pixels, comfortably outvoting the smaller baked-in white-text
    area — so plain mode-over-opaque-pixels is enough, with no separate
    near-white exclusion needed (and none wanted: that would misfire on a
    genuinely near-white paint's own true color).
    """
    opaque = rgba[rgba[..., 3] >= _ALPHA_OPAQUE_THRESHOLD][:, :3]
    if len(opaque) == 0:
        opaque = rgba[..., :3].reshape(-1, 3)
    colors, counts = np.unique(opaque, axis=0, return_counts=True)
    r, g, b = colors[counts.argmax()]
    return f"#{int(r):02X}{int(g):02X}{int(b):02X}"


def _chunked(items: list[_Crop], size: int) -> list[list[_Crop]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _ocr_names(db: Session, crops: list[_Crop]) -> dict[str, str]:
    cfg = resolve_anthropic_config(
        db, setting_key=_AI_API_SETTING_KEY, feature_label=_FEATURE_LABEL
    )
    client = Anthropic(api_key=cfg.api_key)
    names: dict[str, str] = {}
    for chunk in _chunked(crops, _SWATCH_CHUNK_SIZE):
        names.update(_ocr_chunk(client, cfg.model, chunk))
    return names


def _ocr_chunk(client: Anthropic, model: str, chunk: list[_Crop]) -> dict[str, str]:
    content: list[dict] = [{"type": "text", "text": _OCR_INSTRUCTIONS}]
    for crop in chunk:
        content.append({"type": "text", "text": crop.label})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(_png_bytes(crop.rgba)).decode("ascii"),
                },
            }
        )
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=_OCR_MAX_TOKENS,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:  # anthropic.APIError and friends
        raise GenerationError(f"AI request failed: {exc}") from exc

    data = parse_json_object(text_from_response(resp))
    # Claude's job is name OCR only — discard a hex/color field even if the
    # model supplies one anyway, and drop any non-string/blank name (the
    # documented null-for-non-swatch case, or a stray falsy value).
    return {
        label: name
        for label, name in data.items()
        if isinstance(name, str) and name.strip()
    }


def _png_bytes(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()

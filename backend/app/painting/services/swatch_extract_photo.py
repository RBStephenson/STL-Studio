"""Photo / scanned-page vision fallback (STUDIO-381, epic STUDIO-329).

The last-resort extraction tier of Paint Shelf's swatch-chart importer, for
the one case with no PDF structure to lean on at all: a photo of a physical
paint rack, or a true image-only PDF page (a scan with no vector drawings and
no swatch-sized embedded images — STUDIO-331/332's job when either exists).
Unlike STUDIO-332's embedded-raster case, PyMuPDF can't hand us a swatch's
bounding box for free here, so Claude vision has to do both jobs at once:
find where each swatch is, and read its printed name. Color is never taken
from the model either way — every returned box is pixel-sampled from the
same raster the model saw, same trust boundary as STUDIO-332.

There is no real reference chart/photo for this sub-case (unlike
STUDIO-331/332, both verified against a real manufacturer file) — tests here
are necessarily synthetic-only until a real one turns up.
"""
from __future__ import annotations

import base64
import io

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

# Generous enough for a phone photo (typically 2-8MB); still bounded so a
# huge upload can't be decoded into memory unchecked. Checked before PIL ever
# touches the bytes, same order as colormatch.py's _decode_lab_grid.
_MAX_BYTES = 15 * 1024 * 1024

# Print/scan resolution for rasterizing an image-only PDF page. A fixed DPI
# (not "fit to N px") keeps text at a legible, predictable size regardless of
# the page's physical dimensions.
_RASTER_DPI = 150

# Downscale cap applied after decode/rasterize, before the vision call. Much
# higher than colormatch.py's 200px k-means target — reading printed text
# needs real resolution, k-means color sampling doesn't (see that module's
# _DOWNSAMPLE_MAX_DIM). Not a measured platform ceiling, a conservative bound
# chosen the same way STUDIO-332 picked its chunk size.
_MAX_DIMENSION = 1600

# One localization+OCR call per image (a photo or PDF page), not chunked —
# Claude sees the whole image at once here, unlike STUDIO-332's per-crop OCR
# chunks. Sized for a rack photo with a few dozen paints.
_LOCALIZATION_MAX_TOKENS = 4096

_FEATURE_LABEL = "Paint Shelf swatch import"
_AI_API_SETTING_KEY = "ai_guides_api"

_LOCALIZATION_INSTRUCTIONS = (
    "This image shows one or more hobby paint swatches — a photo of a "
    "physical paint rack/bottles, or a scanned/printed swatch chart. Find "
    "every individual paint swatch (a distinct colored patch, cap, or "
    "labeled bottle) and read its printed name exactly as printed, "
    "correcting only obvious OCR noise. Respond with ONLY a JSON object of "
    'the form {"swatches": [{"name": "...", "bbox_pct": [x0, y0, x1, y1]}]}, '
    "one entry per swatch, where bbox_pct is a tight bounding box around the "
    "swatch's own color patch (not any label text) as fractions of the "
    "image's width/height measured from the top-left corner, each in "
    "[0.0, 1.0]. Do not include a color/hex field — color is not your job. "
    'If you can\'t confidently identify any real paint swatches, respond '
    'with {"swatches": []}.'
)


def extract_photo_swatches(db: Session, image_bytes: bytes) -> ExtractionResult:
    """A raw image upload — most likely a photo of a physical paint rack."""
    image = _decode_image(image_bytes)
    if image is None:
        return ExtractionResult(needs_fallback=True)
    return _extract_from_images(db, [image])


def extract_pdf_page_photos(db: Session, pdf_bytes: bytes) -> ExtractionResult:
    """A PDF with no vector swatches and no swatch-sized embedded images —
    an image-only page (scanned/photographed). Rasterizes every page and
    treats each like a photo."""
    images = _rasterize_pdf(pdf_bytes)
    if not images:
        return ExtractionResult(needs_fallback=True)
    return _extract_from_images(db, images)


def _decode_image(raw: bytes) -> Image.Image | None:
    if not raw or len(raw) > _MAX_BYTES:
        return None
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError):
        return None
    image = image.convert("RGB")
    image.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION))
    return image


def _rasterize_pdf(pdf_bytes: bytes) -> list[Image.Image]:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except RuntimeError:
        return []
    try:
        images: list[Image.Image] = []
        for page in doc:
            pix = page.get_pixmap(dpi=_RASTER_DPI)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            image.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION))
            images.append(image)
        return images
    finally:
        doc.close()


def _extract_from_images(db: Session, images: list[Image.Image]) -> ExtractionResult:
    cfg = resolve_anthropic_config(
        db, setting_key=_AI_API_SETTING_KEY, feature_label=_FEATURE_LABEL
    )
    client = Anthropic(api_key=cfg.api_key)
    swatches: list[Swatch] = []
    for image in images:
        swatches.extend(_extract_from_one_image(client, cfg.model, image))
    return ExtractionResult(swatches=swatches)


def _extract_from_one_image(client: Anthropic, model: str, image: Image.Image) -> list[Swatch]:
    rgb = np.asarray(image, dtype=np.uint8)
    content = [
        {"type": "text", "text": _LOCALIZATION_INSTRUCTIONS},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.standard_b64encode(_png_bytes(image)).decode("ascii"),
            },
        },
    ]
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=_LOCALIZATION_MAX_TOKENS,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:  # anthropic.APIError and friends
        raise GenerationError(f"AI request failed: {exc}") from exc

    data = parse_json_object(text_from_response(resp))
    entries = data.get("swatches")
    if not isinstance(entries, list):
        return []
    return [s for entry in entries if (s := _swatch_from_entry(rgb, entry)) is not None]


def _swatch_from_entry(rgb: np.ndarray, entry: object) -> Swatch | None:
    """Build one Swatch from a model-reported entry, pixel-sampling its hex
    from `rgb` (the exact raster the model saw) — never from any hex/color
    field the model might have included anyway. Returns None for anything
    malformed rather than guessing: a degenerate or out-of-range box is a
    sign the model's localization missed, not something to salvage."""
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    bbox = entry.get("bbox_pct")
    if not (isinstance(bbox, list) and len(bbox) == 4):
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None

    h, w = rgb.shape[:2]
    x0, x1 = sorted((_clamp01(x0), _clamp01(x1)))
    y0, y1 = sorted((_clamp01(y0), _clamp01(y1)))
    px0, px1 = int(x0 * w), max(int(x0 * w) + 1, int(x1 * w))
    py0, py1 = int(y0 * h), max(int(y0 * h) + 1, int(y1 * h))
    crop = rgb[py0:py1, px0:px1]
    if crop.size == 0:
        return None
    return Swatch(name=name.strip(), code=None, hex=_dominant_hex(crop))


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _dominant_hex(rgb_crop: np.ndarray) -> str:
    """The crop's most common color — a plain mode over every pixel. No
    alpha channel to gate on here (unlike STUDIO-332's embedded images), and
    no reference photo exists yet to validate a fancier background-exclusion
    heuristic against, so this stays as simple as swatch_extract_vision.py's
    own fallback branch for a crop with no opaque pixels."""
    pixels = rgb_crop.reshape(-1, 3)
    colors, counts = np.unique(pixels, axis=0, return_counts=True)
    r, g, b = colors[counts.argmax()]
    return f"#{int(r):02X}{int(g):02X}{int(b):02X}"


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()

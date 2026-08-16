"""Vector PDF swatch-chart extraction (STUDIO-331, epic STUDIO-329).

Deterministic, no-LLM color extraction for PDFs whose swatches are real
filled vector shapes — the "vector PDF" path of the Paint Shelf swatch-chart
importer. Verified 2026-08-15 against the real Pro Acryl "Hues" chart:
swatches there are a *pair* of overlapping filled circles (a white halo
drawn first, the real color circle on top), not the single filled rectangle
the epic originally assumed. This module handles that pattern generically
(cluster filled shapes sharing a center, pick the non-white fill) rather than
assuming rectangles or exactly one shape per swatch.

Verified 2026-08-16 against the real Army Painter Speedpaint "Practical
Naming Chart": its swatches stack a shared gray template shape *underneath*
the real color, both fully opaque and the same rect, so picking a cluster's
*topmost* (last-drawn) non-white fill rather than its first is what actually
matches the visible color (see `_cluster_hex`).

Charts with no real vector swatches — scanned/photographed pages, or (per
the real Army Painter "Practical Colour Name Chart" fixture investigated for
STUDIO-332) swatches that are themselves small embedded raster images with
the name baked into their pixels — fall through to the vision path
(STUDIO-332). `extract_vector_swatches` signals that case via
`ExtractionResult.needs_fallback` rather than raising; a genuinely
unreadable/corrupt PDF is the only thing that raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz  # pymupdf — AGPL-3.0, see repo NOTICE

# --- Tuning constants -------------------------------------------------------
# Real swatch circles in the Hues.pdf reference chart are ~11,000pt² each;
# the many small decorative stroke-only paths near each swatch top out around
# 150pt². This floor sits well below real swatches and well above the noise.
_MIN_SWATCH_AREA = 400.0

# A filled shape covering most of the page is a background rect (Hues.pdf has
# one at ~100% page area), never a swatch.
_BACKGROUND_AREA_FRACTION = 0.5

# Real swatches (circles, hexagons, squares) are roughly as tall as they are
# wide. Verified against the Army Painter "Practical Colour Name Chart" —
# whose swatches are raster images this module never sees, but whose *other*
# vector decoration (white column-background panels at ~4:1, dark ribbon
# fragments behind category headers at ~4.3:1) would otherwise pass the area
# filter above and be misread as real swatches. An aspect-ratio band this
# generous still admits Hues.pdf's circles (aspect 1.0) while excluding both.
_MIN_ASPECT_RATIO = 0.5
_MAX_ASPECT_RATIO = 2.0

# Halo+fill circle pairs in Hues.pdf share centers within ~1pt of each other.
# A generous multiple of that keeps pairing robust to minor authoring jitter
# without merging genuinely distinct nearby swatches.
_CLUSTER_CENTER_EPSILON = 8.0

# A fill this close to pure white is treated as a halo/background layer, not
# the swatch's real color, when another fill exists in the same cluster.
_WHITE_THRESHOLD = 0.92

# Padding added to a swatch's own bbox when deciding whether a word is its
# label. Hues.pdf centers name+code text *inside* the swatch shape itself
# (verified: a 3-line-wrapped name's words all fall within their swatch's
# ~105pt-tall bbox, with 11-32pt of slack top/bottom in the tightest rows
# observed) — so containment-in-bbox, not a fixed search radius, is what
# actually matches the chart's real design. A radius search was tried first
# and discarded: rows can sit only ~20pt apart in dense sections, so any
# radius wide enough to catch a 3-line wrapped name also reached into the
# next row's label, corrupting names with the neighboring swatch's words.
_LABEL_BBOX_PADDING = 6.0

# Paint SKU codes observed in Hues.pdf are either plain 2-4 digit numbers
# ("009", "059", "511") or a 1-2 letter sub-line prefix directly against 2-3
# digits, no separator ("S20", "E001", "F06" — Speedpaint/Extra/Fluor
# sub-lines) — never hex (hex is derived from the fill itself, not text).
_CODE_PATTERN = re.compile(r"^(?:\d{2,4}|[A-Z]{1,2}\d{2,3})$")

# Embedded images in this size range are candidate swatch chips when no
# vector swatches were found (the Army Painter case, STUDIO-332). Hues.pdf's
# own logo/footer images (~106x106pt placed) sit well outside this range, so
# they don't get miscounted as swatches on an otherwise-vector chart.
_EMBEDDED_SWATCH_MIN_PT = 15.0
_EMBEDDED_SWATCH_MAX_PT = 90.0


@dataclass(frozen=True)
class Swatch:
    """One extracted paint suggestion, pre-review by the user (STUDIO-333)."""

    name: str
    code: str | None
    hex: str


@dataclass(frozen=True)
class ExtractionResult:
    swatches: list[Swatch] = field(default_factory=list)
    needs_fallback: bool = False
    # Set only when needs_fallback: how many embedded images look like swatch
    # chips, so STUDIO-332 can route into its cheaper embedded-image sub-path
    # instead of the general photo/OCR-localization one. 0 means "no vector
    # swatches and no embedded-image signal either" — most likely a
    # scanned/photographed page.
    embedded_image_count: int = 0


def extract_vector_swatches(pdf_bytes: bytes) -> ExtractionResult:
    """Extract {name, code, hex} suggestions from a vector swatch-chart PDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        swatches: list[Swatch] = []
        for page in doc:
            swatches.extend(_extract_page_swatches(page))

        if swatches:
            return ExtractionResult(swatches=swatches)

        embedded_count = sum(_count_swatch_sized_images(page) for page in doc)
        return ExtractionResult(
            needs_fallback=True, embedded_image_count=embedded_count
        )
    finally:
        doc.close()


@dataclass
class _ShapeInfo:
    rect: fitz.Rect
    fill: tuple[float, float, float]


def _extract_page_swatches(page: fitz.Page) -> list[Swatch]:
    clusters = _cluster_filled_shapes(page)
    if not clusters:
        return []

    # A cluster where every member is near-white is a background/panel
    # fragment, not a swatch — real swatches always have a genuine color fill
    # somewhere in the cluster (Hues.pdf's own white halo is *paired* with a
    # real color circle; a solo white shape never is).
    clusters = [c for c in clusters if any(not _is_near_white(s.fill) for s in c)]
    if not clusters:
        return []

    words = _dedupe_words(page.get_text("words"))
    labels = _assign_labels(clusters, words)

    out: list[Swatch] = []
    for i, cluster in enumerate(clusters):
        name, code = labels[i]
        if name:
            out.append(Swatch(name=name, code=code, hex=_cluster_hex(cluster)))
    return out


def _filled_swatch_shapes(page: fitz.Page) -> list[_ShapeInfo]:
    page_area = page.rect.width * page.rect.height
    shapes: list[_ShapeInfo] = []
    for d in page.get_drawings():
        fill = d.get("fill")
        if fill is None:
            continue
        rect = d["rect"]
        if not rect.width or not rect.height:
            continue
        area = rect.width * rect.height
        if area < _MIN_SWATCH_AREA:
            continue
        if page_area and area / page_area > _BACKGROUND_AREA_FRACTION:
            continue
        aspect = rect.width / rect.height
        if not (_MIN_ASPECT_RATIO <= aspect <= _MAX_ASPECT_RATIO):
            continue
        shapes.append(_ShapeInfo(rect=rect, fill=fill))
    return shapes


def _cluster_filled_shapes(page: fitz.Page) -> list[list[_ShapeInfo]]:
    """Group filled shapes sharing (nearly) the same center into one swatch.

    Handles the halo+color-circle pair pattern (two shapes, same center) and
    a plain single-shape-per-swatch chart alike, without assuming either
    shape count up front.
    """
    clusters: list[list[_ShapeInfo]] = []
    for shape in _filled_swatch_shapes(page):
        cx, cy = _center(shape.rect)
        for cluster in clusters:
            ox, oy = _center(cluster[0].rect)
            if (
                abs(cx - ox) <= _CLUSTER_CENTER_EPSILON
                and abs(cy - oy) <= _CLUSTER_CENTER_EPSILON
            ):
                cluster.append(shape)
                break
        else:
            clusters.append([shape])
    return clusters


def _center(rect: fitz.Rect) -> tuple[float, float]:
    return ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def _cluster_bbox(cluster: list[_ShapeInfo]) -> fitz.Rect:
    return fitz.Rect(
        min(s.rect.x0 for s in cluster),
        min(s.rect.y0 for s in cluster),
        max(s.rect.x1 for s in cluster),
        max(s.rect.y1 for s in cluster),
    )


def _cluster_hex(cluster: list[_ShapeInfo]) -> str:
    """The cluster's real swatch color: the topmost non-white fill, if any.

    A halo+color-circle pair (Hues.pdf) always has exactly one near-white
    member, so "first" vs "last" non-white doesn't matter there. But the real
    Speedpaint "Practical Naming Chart" draws a shared gray template swatch
    *underneath* the real color, both fully opaque and the exact same rect —
    picking the first (bottom, hidden) non-white fill returned that template
    gray for ~2/3 of its swatches instead of the real color. Shapes are
    already in paint order (from `page.get_drawings()`), so the *last*
    non-white fill is what's actually visible: later opaque layers occlude
    earlier ones at the same position.
    """
    non_white = [shape for shape in cluster if not _is_near_white(shape.fill)]
    if non_white:
        return _to_hex(non_white[-1].fill)
    return _to_hex(cluster[0].fill)


def _is_near_white(rgb: tuple[float, float, float]) -> bool:
    return all(c >= _WHITE_THRESHOLD for c in rgb)


def _to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02X}" for c in rgb)


_DUPLICATE_WORD_DISTANCE = 1.5


def _dedupe_words(words: list[tuple]) -> list[tuple]:
    """Collapse near-duplicate word entries.

    Hues.pdf renders every label via two overlapping text objects (a
    print-production artifact, not meaningful duplication) — but they aren't
    pixel-identical, sitting only ~0.01-0.06pt apart. Rounding-hash dedup
    (tried first at 1 decimal, then at whole points) was discarded: no fixed
    rounding precision is safe, since the jitter can straddle *any* rounding
    boundary by chance (observed on both a 1-decimal and a whole-point key,
    each time corrupting a different swatch's name with a repeated word).
    Comparing actual bbox-center distance has no such boundary — two words
    are the same duplicate-layer artifact if they share text and sit within
    `_DUPLICATE_WORD_DISTANCE` of each other, full stop.
    """
    kept: list[tuple] = []
    for w in words:
        wcx, wcy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        is_dup = False
        for k in kept:
            if k[4] != w[4]:
                continue
            kcx, kcy = (k[0] + k[2]) / 2, (k[1] + k[3]) / 2
            if abs(wcx - kcx) <= _DUPLICATE_WORD_DISTANCE and abs(
                wcy - kcy
            ) <= _DUPLICATE_WORD_DISTANCE:
                is_dup = True
                break
        if not is_dup:
            kept.append(w)
    return kept


def _assign_labels(
    clusters: list[list[_ShapeInfo]], words: list[tuple]
) -> dict[int, tuple[str | None, str | None]]:
    """Assign each swatch's label words, then split them into (name, code).

    A word counts as a swatch's label only if its center falls inside that
    swatch's own (padded) bbox — matching the chart's real design, where
    name+code text is laid out inside the swatch shape itself. A word inside
    more than one padded bbox (shapes close enough to overlap slightly) picks
    whichever center it's actually nearer to; a word inside none is dropped,
    not force-assigned to a distant "nearest" swatch — that's what previously
    let one swatch's label bleed into an unrelated word from an adjacent row.
    """
    bboxes = [_cluster_bbox(c) for c in clusters]
    centers = [_center(b) for b in bboxes]
    words_by_cluster: dict[int, list[tuple[float, float, str]]] = {
        i: [] for i in range(len(clusters))
    }

    for w in words:
        wx0, wy0, wx1, wy1, text = w[0], w[1], w[2], w[3], w[4]
        wcx, wcy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
        best_i, best_dist = None, None
        for i, b in enumerate(bboxes):
            if not (
                b.x0 - _LABEL_BBOX_PADDING <= wcx <= b.x1 + _LABEL_BBOX_PADDING
                and b.y0 - _LABEL_BBOX_PADDING <= wcy <= b.y1 + _LABEL_BBOX_PADDING
            ):
                continue
            ccx, ccy = centers[i]
            dist = ((wcx - ccx) ** 2 + (wcy - ccy) ** 2) ** 0.5
            if best_dist is None or dist < best_dist:
                best_i, best_dist = i, dist
        if best_i is not None:
            words_by_cluster[best_i].append((wy0, wx0, text))

    labels: dict[int, tuple[str | None, str | None]] = {}
    for i, entries in words_by_cluster.items():
        entries.sort(key=lambda e: (e[0], e[1]))  # reading order: top-to-bottom, then left-to-right
        code = None
        name_tokens = []
        for _, _, text in entries:
            if code is None and _CODE_PATTERN.match(text):
                code = text
                continue
            name_tokens.append(text)
        name = " ".join(name_tokens).strip()
        labels[i] = (name or None, code)
    return labels


def _count_swatch_sized_images(page: fitz.Page) -> int:
    count = 0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        w, h = x1 - x0, y1 - y0
        if (
            _EMBEDDED_SWATCH_MIN_PT <= w <= _EMBEDDED_SWATCH_MAX_PT
            and _EMBEDDED_SWATCH_MIN_PT <= h <= _EMBEDDED_SWATCH_MAX_PT
        ):
            count += 1
    return count

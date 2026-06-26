"""Reference-image color matching: Lab conversion, CIEDE2000, k-means sampling.

Spec §8.6 — honest by design. The studio samples a reference image into a small
palette (k-means in CIE Lab) and, per sampled region, suggests owned paints two
ways:

* **value-only** (absolute ΔL*) — the lead lens, because value is the one thing a flat
  swatch hex represents honestly, even for metallics;
* **hue** (CIEDE2000) — secondary, run only over owned AND `matchable` paints
  (opaque color paints). Inks/washes are surfaced separately as labelled glaze
  options, never ranked as if they were a flat-colour hit.

Everything here is *suggest-and-confirm-by-eye* (spec Q6): inventory hexes are
approximate, results carry a ΔE band plus a standing caveat, and nothing is ever
auto-assigned.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, UnidentifiedImageError
from skimage.color import deltaE_ciede2000, lab2rgb, rgb2lab
from sqlalchemy.orm import Session, joinedload

from app.painting.models import Paint, PaintLine

# Finishes whose owned paints are offered as labelled glaze/shade options
# (transparent — final colour depends on what's beneath) rather than hue-ranked.
_GLAZE_FINISHES = frozenset({"ink", "wash"})

# Standing caveat attached to every result (spec §8.6 honesty contract).
CAVEAT = (
    "Inventory hexes are approximate. These are suggestions to confirm by eye "
    "under your bench light — never an auto-applied answer."
)

# ΔE2000 / ΔL* confidence bands (spec §8.6).
_BAND_VERY_CLOSE = 2.0
_BAND_CLOSE = 5.0
_BAND_FAMILY = 10.0

# Bounds. Upload cap mirrors images.py; downsample keeps k-means cheap and
# averages out sensor noise without losing the regions that matter.
_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_K = 5
_MAX_K = 12
_DEFAULT_CANDIDATES = 5
_DOWNSAMPLE_MAX_DIM = 200
_KMEANS_ITERS = 25
_KMEANS_SEED = 0  # fixed → deterministic palette for a given image

# Value-match hue gate. The value ranking is value-first (spec §8.6), but a paint
# from a wildly different hue at the same L* is a misleading "value match" (a red
# offered for a green region). So chromatic paints are gated to the region's hue
# family; the genuinely hue-less ones are kept regardless:
#   * metallics — value-only by design (their hex hue is meaningless);
#   * near-neutrals (low chroma) — greys/black/white are universal value refs;
#   * any paint when the region itself is near-neutral — hue is meaningless there.
_NEUTRAL_CHROMA = 12.0      # C* below this = treat as neutral (hue unreliable)
_VALUE_HUE_TOL_DEG = 40.0   # max hue-angle gap for a chromatic value match

# Value ladder (#569): the hue-family pool is split into a shadow → mid →
# highlight ramp around the sampled anchor, so suggestions read as a cohesive
# recipe (Dark Camo Green → Green → Bright Yellow-Green) rather than a flat list.
_LADDER_MID_BAND = 8.0      # |ΔL*| within this of the anchor = the mid slot
_LADDER_TARGET_STEP = 22.0  # preferred ΔL* for a shadow / highlight step
_LADDER_STEP_W = 0.4        # weight of value-step fit vs hue cohesion in ranking

# Background exclusion for the auto palette: the backdrop is the single largest
# area in most product shots and would otherwise eat a region. Estimate it from
# the image corners and drop pixels close to it before clustering.
_BG_CORNER_FRAC = 0.06      # fraction of each side sampled at each corner
_BG_EXCLUDE_DE = 12.0       # drop pixels within this ΔE2000 of the backdrop
_BG_MIN_KEEP_FRAC = 0.05    # if exclusion leaves fewer than this, skip it

# Point ("eyedropper") sampling: average a small square patch around the click
# so a single noisy pixel doesn't drive the match.
_POINT_PATCH_FRAC = 0.02    # patch half-size as a fraction of the short side


class ColorMatchError(ValueError):
    """The supplied image was missing, too large, or not a readable image."""


@dataclass(frozen=True)
class Candidate:
    """One suggested paint for a sampled region."""

    paint_id: int
    code: str
    name: str
    brand: str
    line: str
    hex: str | None
    finish: str
    delta_l: float           # |ΔL*| vs the region (always present)
    delta_e: float | None    # CIEDE2000 vs the region; None for value-only/glaze
    band: str                # very_close | close | family | loose


@dataclass(frozen=True)
class ValueLadder:
    """A hue-cohesive value ramp around the sampled anchor (#569)."""

    shadow: list[Candidate] = field(default_factory=list)
    mid: list[Candidate] = field(default_factory=list)      # closest to the anchor
    highlight: list[Candidate] = field(default_factory=list)


@dataclass(frozen=True)
class RegionMatch:
    """One k-means region of the reference image with its paint suggestions."""

    hex: str                       # centroid rendered back to sRGB, for display
    lab: tuple[float, float, float]
    value_l: float                 # L* of the region (0..100)
    weight: float                  # fraction of sampled pixels in this cluster
    ladder: ValueLadder = field(default_factory=ValueLadder)
    hue_candidates: list[Candidate] = field(default_factory=list)
    glaze_options: list[Candidate] = field(default_factory=list)


@dataclass(frozen=True)
class ColorMatchResult:
    regions: list[RegionMatch]
    caveat: str = CAVEAT


# ---------------------------------------------------------------------------
# Colour conversions
# ---------------------------------------------------------------------------

def _hex_to_lab(hex_str: str) -> tuple[float, float, float] | None:
    """Convert '#RRGGBB' to CIE Lab (D65). Returns None for malformed input."""
    s = hex_str.lstrip("#")
    if len(s) != 6:
        return None
    try:
        rgb = np.array([int(s[i : i + 2], 16) for i in (0, 2, 4)], dtype=float) / 255.0
    except ValueError:
        return None
    lab = rgb2lab(rgb.reshape(1, 1, 3)).reshape(3)
    return float(lab[0]), float(lab[1]), float(lab[2])


def _lab_to_hex(lab: np.ndarray) -> str:
    rgb = np.clip(lab2rgb(lab.reshape(1, 1, 3)).reshape(3), 0.0, 1.0)
    r, g, b = (int(round(c * 255)) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _chroma(lab) -> float:
    """CIE C* — distance from the neutral axis in the a*/b* plane."""
    return float(np.hypot(lab[1], lab[2]))


def _hue_deg(lab) -> float:
    """CIE hue angle h° (0–360) from a*/b*."""
    return float(np.degrees(np.arctan2(lab[2], lab[1])) % 360.0)


def _in_value_family(region_lab, paint_lab, finish: str) -> bool:
    """Whether `paint_lab` is a non-misleading value match for `region_lab`.

    Metallics and near-neutrals (on either side) always qualify — their hue is
    meaningless. Otherwise the paint's hue must sit within `_VALUE_HUE_TOL_DEG`
    of the region's, so we never offer a red as a value match for a green.
    """
    if finish == "metallic":
        return True
    if _chroma(region_lab) < _NEUTRAL_CHROMA or _chroma(paint_lab) < _NEUTRAL_CHROMA:
        return True
    dh = abs(_hue_deg(region_lab) - _hue_deg(paint_lab))
    return min(dh, 360.0 - dh) <= _VALUE_HUE_TOL_DEG


def _band(distance: float) -> str:
    if distance < _BAND_VERY_CLOSE:
        return "very_close"
    if distance < _BAND_CLOSE:
        return "close"
    if distance < _BAND_FAMILY:
        return "family"
    return "loose"


# ---------------------------------------------------------------------------
# k-means in Lab (no sklearn dependency; deterministic via a fixed seed)
# ---------------------------------------------------------------------------

def _kmeans(pixels: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Cluster (N, 3) Lab pixels. Returns (centroids (k, 3), counts (k,)).

    k-means++ seeding with a fixed RNG, then Lloyd iterations. Empty clusters
    are dropped, so the returned arrays may have fewer than k rows.
    """
    rng = np.random.default_rng(_KMEANS_SEED)
    n = len(pixels)
    k = max(1, min(k, n))

    # k-means++ init.
    centroids = pixels[rng.integers(n)][None, :]
    for _ in range(1, k):
        d2 = np.min(((pixels[:, None, :] - centroids[None, :, :]) ** 2).sum(-1), axis=1)
        total = d2.sum()
        probs = np.full(n, 1.0 / n) if total == 0 else d2 / total
        centroids = np.vstack([centroids, pixels[rng.choice(n, p=probs)]])

    labels = np.zeros(n, dtype=int)
    for _ in range(_KMEANS_ITERS):
        dists = ((pixels[:, None, :] - centroids[None, :, :]) ** 2).sum(-1)
        new_labels = dists.argmin(axis=1)
        if np.array_equal(new_labels, labels):
            labels = new_labels
            break
        labels = new_labels
        for ci in range(len(centroids)):
            members = pixels[labels == ci]
            if len(members):
                centroids[ci] = members.mean(axis=0)

    counts = np.bincount(labels, minlength=len(centroids))
    keep = counts > 0
    return centroids[keep], counts[keep]


def _decode_lab_grid(raw: bytes) -> np.ndarray:
    """Decode + downsample an upload to an (H, W, 3) CIE Lab grid.

    Shared by the palette and point-sample paths. Raises ColorMatchError on a
    missing/oversize/unreadable image.
    """
    if not raw:
        raise ColorMatchError("The uploaded file is empty.")
    if len(raw) > _MAX_BYTES:
        raise ColorMatchError(
            f"Image is too large ({len(raw) // 1024} KB); the limit is "
            f"{_MAX_BYTES // (1024 * 1024)} MB."
        )
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ColorMatchError("The uploaded file is not a readable image.") from exc

    image = image.convert("RGB")
    image.thumbnail((_DOWNSAMPLE_MAX_DIM, _DOWNSAMPLE_MAX_DIM))
    rgb = np.asarray(image, dtype=float) / 255.0
    return rgb2lab(rgb)


def _without_background(grid: np.ndarray) -> np.ndarray:
    """Flatten an (H, W, 3) Lab grid to (N, 3), dropping backdrop pixels.

    The backdrop is estimated from the four corners; pixels within
    `_BG_EXCLUDE_DE` of it are removed so the studio backdrop doesn't claim a
    region. Falls back to keeping everything if exclusion would gut the image
    (e.g. the figure fills the frame, or the corners aren't background).
    """
    h, w, _ = grid.shape
    flat = grid.reshape(-1, 3)
    p = max(1, int(min(h, w) * _BG_CORNER_FRAC))
    corners = np.concatenate([
        grid[:p, :p].reshape(-1, 3), grid[:p, -p:].reshape(-1, 3),
        grid[-p:, :p].reshape(-1, 3), grid[-p:, -p:].reshape(-1, 3),
    ])
    backdrop = corners.mean(axis=0)
    de = deltaE_ciede2000(flat, np.broadcast_to(backdrop, flat.shape))
    kept = flat[de >= _BG_EXCLUDE_DE]
    if len(kept) < max(1, int(len(flat) * _BG_MIN_KEEP_FRAC)):
        return flat
    return kept


def _sample_palette(raw: bytes, k: int) -> list[tuple[np.ndarray, float]]:
    """Decode, drop the background, and k-means into (lab_centroid, weight) pairs.

    Averaging happens in Lab space (perceptually correct). Pairs are returned
    sorted by weight descending.
    """
    lab = _without_background(_decode_lab_grid(raw))
    centroids, counts = _kmeans(lab, k)
    total = float(counts.sum())
    pairs = [(centroids[i], float(counts[i]) / total) for i in range(len(centroids))]
    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs


# ---------------------------------------------------------------------------
# Candidate ranking
# ---------------------------------------------------------------------------

def _candidate(paint: Paint, region_lab: np.ndarray, paint_lab, *, hue: bool) -> Candidate:
    delta_l = abs(float(region_lab[0]) - paint_lab[0])
    delta_e: float | None = None
    if hue:
        delta_e = float(
            deltaE_ciede2000(region_lab.reshape(1, 3), np.array(paint_lab).reshape(1, 3))[0]
        )
        band = _band(delta_e)
    else:
        band = _band(delta_l)
    return Candidate(
        paint_id=paint.id,
        code=paint.code,
        name=paint.name,
        brand=paint.line.brand.name,
        line=paint.line.name,
        hex=paint.hex,
        finish=paint.finish,
        delta_l=round(delta_l, 2),
        delta_e=None if delta_e is None else round(delta_e, 2),
        band=band,
    )


def _hue_dist(a, b) -> float:
    """Circular hue-angle gap (degrees) between two Lab colours."""
    d = abs(_hue_deg(a) - _hue_deg(b))
    return min(d, 360.0 - d)


def _value_ladder(
    anchor: np.ndarray,
    paints_lab: list[tuple[Paint, tuple[float, float, float]]],
    top_n: int,
) -> ValueLadder:
    """Build a shadow → mid → highlight ramp from the hue-family pool (#569).

    The pool is the same hue-gated set as the flat value match (so metallics and
    neutrals stay in), but split by L* around the anchor: paints darker than the
    sample feed the shadow slot, lighter ones the highlight, and those near it
    the mid. Shadow/highlight are ranked for hue cohesion first (a near-neutral
    fits any family) then for a clean value step; the mid by closeness (ΔE).
    """
    anchor_neutral = _chroma(anchor) < _NEUTRAL_CHROMA

    def cohesion(lab) -> float:
        # Neutrals read as in-family at any hue, so don't penalise them.
        if anchor_neutral or _chroma(lab) < _NEUTRAL_CHROMA:
            return 0.0
        return _hue_dist(anchor, lab)

    a_l = float(anchor[0])
    shadow: list[tuple[Candidate, float]] = []
    mid: list[tuple[Candidate, float]] = []
    high: list[tuple[Candidate, float]] = []
    for p, lab in paints_lab:
        if not _in_value_family(anchor, lab, p.finish):
            continue
        dl = float(lab[0]) - a_l
        cand = _candidate(p, anchor, lab, hue=True)
        step_fit = abs(abs(dl) - _LADDER_TARGET_STEP)
        rank = cohesion(lab) + _LADDER_STEP_W * step_fit
        if dl < -_LADDER_MID_BAND:
            shadow.append((cand, rank))
        elif dl > _LADDER_MID_BAND:
            high.append((cand, rank))
        else:
            mid.append((cand, cand.delta_e if cand.delta_e is not None else 0.0))

    shadow.sort(key=lambda x: x[1])
    high.sort(key=lambda x: x[1])
    mid.sort(key=lambda x: x[1])
    take = lambda lst: [c for c, _ in lst[:top_n]]
    return ValueLadder(shadow=take(shadow), mid=take(mid), highlight=take(high))


def _rank_region(
    region_lab: np.ndarray,
    paints_lab: list[tuple[Paint, tuple[float, float, float]]],
    glazes_lab: list[tuple[Paint, tuple[float, float, float]]],
    top_n: int,
) -> tuple[ValueLadder, list[Candidate], list[Candidate]]:
    ladder = _value_ladder(region_lab, paints_lab, top_n)

    # Hue: owned AND matchable only, ranked by CIEDE2000.
    hue = [
        _candidate(p, region_lab, lab, hue=True)
        for p, lab in paints_lab
        if p.matchable
    ]
    hue.sort(key=lambda c: c.delta_e)

    # Glazes/shades: labelled secondary list, sorted by hue distance for utility
    # but never presented as a flat-colour hit.
    glaze = [_candidate(p, region_lab, lab, hue=True) for p, lab in glazes_lab]
    glaze.sort(key=lambda c: c.delta_e)

    return ladder, hue[:top_n], glaze[:top_n]


PaintPool = tuple[
    list[tuple[Paint, tuple[float, float, float]]],
    list[tuple[Paint, tuple[float, float, float]]],
]


def _load_pools(db: Session) -> PaintPool:
    """Owned paints split into (value/hue pool, glaze pool), hexes pre-converted.

    Brand/line are eager-loaded so candidate building issues no per-paint query.
    Paints without a usable hex are skipped; inks/washes form the glaze pool.
    """
    owned = (
        db.query(Paint)
        .options(joinedload(Paint.line).joinedload(PaintLine.brand))
        .filter(Paint.owned.is_(True))
        .all()
    )
    paints_lab: list[tuple[Paint, tuple[float, float, float]]] = []
    glazes_lab: list[tuple[Paint, tuple[float, float, float]]] = []
    for paint in owned:
        if not paint.hex:
            continue
        lab = _hex_to_lab(paint.hex)
        if lab is None:
            continue
        (glazes_lab if paint.finish in _GLAZE_FINISHES else paints_lab).append((paint, lab))
    return paints_lab, glazes_lab


def _region_from_lab(
    centroid: np.ndarray, weight: float, pools: PaintPool, top_n: int,
) -> RegionMatch:
    paints_lab, glazes_lab = pools
    ladder, hue, glaze = _rank_region(centroid, paints_lab, glazes_lab, top_n)
    return RegionMatch(
        hex=_lab_to_hex(centroid),
        lab=(round(float(centroid[0]), 2), round(float(centroid[1]), 2),
             round(float(centroid[2]), 2)),
        value_l=round(float(centroid[0]), 2),
        weight=round(weight, 4),
        ladder=ladder,
        hue_candidates=hue,
        glaze_options=glaze,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def match_image(
    db: Session,
    raw: bytes,
    *,
    k: int = _DEFAULT_K,
    candidates_per_region: int = _DEFAULT_CANDIDATES,
) -> ColorMatchResult:
    """Sample an uploaded reference image and suggest owned paints per region.

    `k` palette regions (clamped to 1..MAX_K, background excluded), each with
    value-first and hue candidate lists plus labelled glaze options. Raises
    ColorMatchError on a missing/oversize/unreadable image.
    """
    k = max(1, min(int(k), _MAX_K))
    top_n = max(1, int(candidates_per_region))
    pools = _load_pools(db)
    pairs = _sample_palette(raw, k)
    return ColorMatchResult(
        regions=[_region_from_lab(c, w, pools, top_n) for c, w in pairs]
    )


def match_point(
    db: Session,
    raw: bytes,
    x: float,
    y: float,
    *,
    candidates_per_region: int = _DEFAULT_CANDIDATES,
) -> ColorMatchResult:
    """Suggest paints for a single point ("eyedropper") on the image.

    `x`/`y` are normalized [0, 1] from the image's top-left. A small patch
    around the point is averaged in Lab so one noisy pixel doesn't drive the
    match — giving per-component control (sample the skin, then the hair, …).
    Returns a single-region result. Raises ColorMatchError on a bad image.
    """
    top_n = max(1, int(candidates_per_region))
    grid = _decode_lab_grid(raw)
    h, w, _ = grid.shape

    cx = min(w - 1, max(0, int(round(min(1.0, max(0.0, x)) * (w - 1)))))
    cy = min(h - 1, max(0, int(round(min(1.0, max(0.0, y)) * (h - 1)))))
    r = max(1, int(round(min(h, w) * _POINT_PATCH_FRAC)))
    patch = grid[max(0, cy - r):cy + r + 1, max(0, cx - r):cx + r + 1].reshape(-1, 3)
    centroid = patch.mean(axis=0)

    pools = _load_pools(db)
    return ColorMatchResult(regions=[_region_from_lab(centroid, 1.0, pools, top_n)])

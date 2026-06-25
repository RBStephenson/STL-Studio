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
class RegionMatch:
    """One k-means region of the reference image with its paint suggestions."""

    hex: str                       # centroid rendered back to sRGB, for display
    lab: tuple[float, float, float]
    value_l: float                 # L* of the region (0..100)
    weight: float                  # fraction of sampled pixels in this cluster
    value_candidates: list[Candidate] = field(default_factory=list)
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


def _sample_palette(raw: bytes, k: int) -> list[tuple[np.ndarray, float]]:
    """Decode image, downsample, and k-means into (lab_centroid, weight) pairs.

    Averaging happens in Lab space (perceptually correct). Pairs are returned
    sorted by weight descending.
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
    rgb = np.asarray(image, dtype=float).reshape(-1, 3) / 255.0
    lab = rgb2lab(rgb.reshape(1, -1, 3)).reshape(-1, 3)

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


def _rank_region(
    region_lab: np.ndarray,
    paints_lab: list[tuple[Paint, tuple[float, float, float]]],
    glazes_lab: list[tuple[Paint, tuple[float, float, float]]],
    top_n: int,
) -> tuple[list[Candidate], list[Candidate], list[Candidate]]:
    # Value: every paint with a value signal, ranked by |ΔL*| (metallics included).
    value = [_candidate(p, region_lab, lab, hue=False) for p, lab in paints_lab]
    value.sort(key=lambda c: c.delta_l)

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

    return value[:top_n], hue[:top_n], glaze[:top_n]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def match_image(
    db: Session,
    raw: bytes,
    *,
    k: int = _DEFAULT_K,
    candidates_per_region: int = _DEFAULT_CANDIDATES,
) -> ColorMatchResult:
    """Sample an uploaded reference image and suggest owned paints per region.

    `k` palette regions (clamped to 1..MAX_K), each with value-first and hue
    candidate lists plus labelled glaze options. Raises ColorMatchError on a
    missing/oversize/unreadable image.
    """
    k = max(1, min(int(k), _MAX_K))
    top_n = max(1, int(candidates_per_region))

    pairs = _sample_palette(raw, k)

    # Load the owned inventory once, with brand/line eager so candidate building
    # doesn't issue per-paint queries.
    owned = (
        db.query(Paint)
        .options(joinedload(Paint.line).joinedload(PaintLine.brand))
        .filter(Paint.owned.is_(True))
        .all()
    )

    # Pre-convert hexes to Lab. value/hue pool = any owned paint with a usable
    # hex; glaze pool = owned inks/washes with a usable hex.
    paints_lab: list[tuple[Paint, tuple[float, float, float]]] = []
    glazes_lab: list[tuple[Paint, tuple[float, float, float]]] = []
    for paint in owned:
        if not paint.hex:
            continue
        lab = _hex_to_lab(paint.hex)
        if lab is None:
            continue
        if paint.finish in _GLAZE_FINISHES:
            glazes_lab.append((paint, lab))
        else:
            paints_lab.append((paint, lab))

    regions: list[RegionMatch] = []
    for centroid, weight in pairs:
        value, hue, glaze = _rank_region(centroid, paints_lab, glazes_lab, top_n)
        regions.append(
            RegionMatch(
                hex=_lab_to_hex(centroid),
                lab=(round(float(centroid[0]), 2), round(float(centroid[1]), 2),
                     round(float(centroid[2]), 2)),
                value_l=round(float(centroid[0]), 2),
                weight=round(weight, 4),
                value_candidates=value,
                hue_candidates=hue,
                glaze_options=glaze,
            )
        )

    return ColorMatchResult(regions=regions)

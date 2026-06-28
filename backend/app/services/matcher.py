"""
Fuzzy name matching between scraped storefront products and local models.

We use a token-based similarity score rather than edit distance because
model names tend to vary in word order and include extra tokens like
scale, version, creator name, etc.

e.g.  local:    "1-6scale Akuma CA3D"
      scraped:  "Akuma Street Fighter 1/6 Scale Figure"
      → high overlap on "akuma" + "1" + "6" + "scale"
"""
import re
from dataclasses import dataclass
from typing import Optional

from app.services.scrapers.storefront import StorefrontProduct


@dataclass
class MatchCandidate:
    local_model_id: int
    local_name: str
    local_folder: str
    product: StorefrontProduct
    score: float          # 0–1
    confidence: str       # "high" | "medium" | "low"


# _STRIP_RE replaces every non-word/non-space char with a space, so scale
# separators ("1/6", "1-6", "1:6") are already split into "1 6" before any
# further normalization runs — no dedicated scale regex is needed (#353).
_STRIP_RE = re.compile(r"[^\w\s]")


def _tokens(text: str) -> set[str]:
    text = _STRIP_RE.sub(" ", text.lower())
    return {t for t in text.split() if len(t) > 1}


def _score_tokens(a: set[str], b: set[str]) -> float:
    """Token-set similarity. Callers pass pre-tokenized sets so a product or
    local name is tokenized once, not once per (model × product) comparison (#57)."""
    if not a or not b:
        return 0.0
    intersection = a & b
    # Jaccard similarity weighted toward recall (local tokens matched)
    jaccard = len(intersection) / len(a | b)
    recall  = len(intersection) / len(a)
    return round(0.4 * jaccard + 0.6 * recall, 3)


def _score(local_name: str, product_title: str) -> float:
    """Convenience wrapper that tokenizes both sides then scores."""
    return _score_tokens(_tokens(local_name), _tokens(product_title))


# Bonus added when the model's `character` (its denoised product identity, e.g.
# "Ada Wong") is fully contained in the product title — a strong signal the store
# listing is the same product, even when the raw name is noisy. Capped at 1.0.
_CHARACTER_BONUS = 0.15

# Scale auto-tags (e.g. "75mm", "1:6"). display_name strips scale from the model
# name, but store titles carry it ("Akuma 75mm Bust"), so we re-add it as a match
# signal. Ratio digits ("1","6") are dropped by _tokens' length filter — only mm
# scales survive here; symmetric ratio normalisation is handled in #629.
_SCALE_TAG_RE = re.compile(r"^\d{1,4}mm$|^\d{1,2}[:/\-]\d{1,2}$", re.I)


def _scale_tokens(auto_tags) -> set[str]:
    toks: set[str] = set()
    for t in auto_tags or []:
        if _SCALE_TAG_RE.match(str(t).strip()):
            toks |= _tokens(t)
    return toks


def _confidence(score: float) -> str:
    if score >= 0.55:
        return "high"
    if score >= 0.30:
        return "medium"
    return "low"


def match_products_to_models(
    products: list[StorefrontProduct],
    models: list[dict],           # [{"id": int, "name": str, "folder_path": str, ...}]
    min_score: float = 0.20,
) -> list[MatchCandidate]:
    """
    For each local model, find the best-matching storefront product.
    Returns one candidate per local model (best match only), filtered
    by min_score. Sorted by score descending.
    """
    candidates: list[MatchCandidate] = []

    # Tokenize each product title once up front, not once per local model (#57).
    product_tokens = [(product, _tokens(product.title)) for product in products]

    for m in models:
        best_score = 0.0
        best_product: Optional[StorefrontProduct] = None

        # Score against the model name, title, and character — the denoised
        # product identity (e.g. "Ada Wong") that store titles key on. Tokenize
        # each once per model rather than once per product comparison.
        character = m.get("character") or ""
        char_tokens = _tokens(character) if character else set()
        name_token_sets = [
            _tokens(name)
            for name in (m.get("name", ""), m.get("title") or "")
            if name
        ]
        if char_tokens:
            name_token_sets.append(char_tokens)

        # Re-add scale as a match signal by augmenting each name set (never as a
        # standalone set — scale alone would false-match every same-scale product).
        scale_tokens = _scale_tokens(m.get("auto_tags"))
        if scale_tokens and name_token_sets:
            name_token_sets = [s | scale_tokens for s in name_token_sets]

        for product, p_tokens in product_tokens:
            s = max((_score_tokens(nt, p_tokens) for nt in name_token_sets), default=0.0)
            # Strong signal: the whole character identity appears in the title.
            if char_tokens and char_tokens <= p_tokens:
                s = min(1.0, s + _CHARACTER_BONUS)
            if s > best_score:
                best_score = s
                best_product = product

        if best_product and best_score >= min_score:
            candidates.append(MatchCandidate(
                local_model_id=m["id"],
                local_name=m.get("title") or m.get("name", ""),
                local_folder=m.get("folder_path", ""),
                product=best_product,
                score=best_score,
                confidence=_confidence(best_score),
            ))

    return sorted(candidates, key=lambda c: -c.score)

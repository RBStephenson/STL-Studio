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


_STRIP_RE = re.compile(r"[^\w\s]")
_SCALE_RE = re.compile(r"\b1[-/:]?(\d{1,2})\b")


def _tokens(text: str) -> set[str]:
    text = _STRIP_RE.sub(" ", text.lower())
    # Normalise scale expressions so "1-6" and "1/6" both become "1 6"
    text = _SCALE_RE.sub(lambda m: f"1 {m.group(1)}", text)
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

        # Score against the model name and title (folder name as fallback);
        # tokenize each once per model rather than once per product comparison.
        name_token_sets = [
            _tokens(name)
            for name in (m.get("name", ""), m.get("title") or "")
            if name
        ]

        for product, p_tokens in product_tokens:
            for n_tokens in name_token_sets:
                s = _score_tokens(n_tokens, p_tokens)
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

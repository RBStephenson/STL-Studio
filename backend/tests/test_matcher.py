"""
Tests for the storefront↔local-model fuzzy matcher (services/matcher.py).

Covers scoring behavior, candidate selection, and the #57 guarantee that each
product title and local name is tokenized once — not once per (model × product)
comparison.
"""
import app.services.matcher as matcher
from app.services.matcher import (
    _confidence,
    _score,
    match_products_to_models,
)
from app.services.scrapers.storefront import StorefrontProduct


def _product(title: str) -> StorefrontProduct:
    return StorefrontProduct(title=title, source_url="https://x/p", source_site="gumroad")


def _model(id_: int, name: str = "", title: str | None = None, folder: str = "/f") -> dict:
    return {"id": id_, "name": name, "title": title, "folder_path": folder}


# ---------------------------------------------------------------------------
# _score
# ---------------------------------------------------------------------------

class TestScore:
    def test_identical_names_score_one(self):
        assert _score("Akuma Street Fighter", "Akuma Street Fighter") == 1.0

    def test_no_overlap_scores_zero(self):
        assert _score("Batman", "Spiderman Figure") == 0.0

    def test_empty_inputs_score_zero(self):
        assert _score("", "anything") == 0.0
        assert _score("anything", "") == 0.0

    def test_single_char_tokens_ignored(self):
        # tokens of length 1 are dropped, so "a b" has no usable tokens
        assert _score("a b", "a b") == 0.0

    def test_partial_word_overlap_scores_between(self):
        # Shared "akuma" token with extra distinct tokens on each side →
        # a positive but sub-1.0 score.
        s = _score("Akuma 16scale", "Akuma 16 Scale")
        assert 0.0 < s < 1.0

    def test_recall_weighting_rewards_matched_local_tokens(self):
        # All local tokens present in a longer product title → strong recall.
        s = _score("Akuma", "Akuma Street Fighter 1/6 Scale Figure")
        assert s > 0.3


class TestConfidence:
    def test_thresholds(self):
        assert _confidence(0.55) == "high"
        assert _confidence(0.54) == "medium"
        assert _confidence(0.30) == "medium"
        assert _confidence(0.29) == "low"
        assert _confidence(0.0) == "low"


# ---------------------------------------------------------------------------
# match_products_to_models
# ---------------------------------------------------------------------------

class TestMatchProductsToModels:
    def test_best_product_chosen_per_model(self):
        products = [_product("Spiderman Figure"), _product("Akuma Street Fighter")]
        models = [_model(1, name="Akuma CA3D")]

        result = match_products_to_models(products, models)
        assert len(result) == 1
        assert result[0].local_model_id == 1
        assert result[0].product.title == "Akuma Street Fighter"

    def test_falls_back_to_name_when_title_absent(self):
        products = [_product("Akuma Street Fighter")]
        models = [_model(1, name="Akuma", title=None)]

        result = match_products_to_models(products, models)
        assert len(result) == 1
        assert result[0].product.title == "Akuma Street Fighter"

    def test_title_preferred_for_local_name_field(self):
        products = [_product("Akuma Street Fighter")]
        models = [_model(1, name="folder-junk", title="Akuma")]

        result = match_products_to_models(products, models)
        assert result[0].local_name == "Akuma"

    def test_below_min_score_excluded(self):
        products = [_product("Completely Unrelated Thing")]
        models = [_model(1, name="Akuma")]

        result = match_products_to_models(products, models, min_score=0.20)
        assert result == []

    def test_results_sorted_by_score_desc(self):
        products = [_product("Akuma Street Fighter")]
        models = [
            _model(1, name="Akuma Street Fighter"),  # exact → 1.0
            _model(2, name="Akuma"),                 # partial
        ]

        result = match_products_to_models(products, models)
        scores = [c.score for c in result]
        assert scores == sorted(scores, reverse=True)
        assert result[0].local_model_id == 1

    def test_empty_products_yields_no_candidates(self):
        assert match_products_to_models([], [_model(1, name="Akuma")]) == []

    def test_empty_models_yields_no_candidates(self):
        assert match_products_to_models([_product("Akuma")], []) == []


# ---------------------------------------------------------------------------
# #57 — pre-tokenization: each title/name tokenized once, not per comparison
# ---------------------------------------------------------------------------

class TestPreTokenization:
    def test_tokens_called_once_per_distinct_string(self, monkeypatch):
        """With P products and M models, the naive impl tokenized
        O(M × P × names) times. After #57 each product title is tokenized once
        and each model's names once — so total _tokens calls == P + sum(names)."""
        calls: list[str] = []
        real_tokens = matcher._tokens

        def counting_tokens(text: str):
            calls.append(text)
            return real_tokens(text)

        monkeypatch.setattr(matcher, "_tokens", counting_tokens)

        products = [_product(f"Product {i}") for i in range(4)]
        models = [_model(i, name=f"Model {i}", title=f"Title {i}") for i in range(5)]

        match_products_to_models(products, models)

        # 4 product titles + 5 models × 2 names each = 4 + 10 = 14, regardless of
        # the 4 × 5 × 2 = 40 comparisons performed.
        assert len(calls) == 14

    def test_scores_unchanged_vs_pairwise_score(self):
        """The pre-tokenized path must produce the same score as the per-pair
        _score() helper for the chosen candidate."""
        products = [_product("Akuma Street Fighter 1/6 Scale")]
        models = [_model(1, name="Akuma 1-6scale")]

        result = match_products_to_models(products, models)
        expected = _score("Akuma 1-6scale", "Akuma Street Fighter 1/6 Scale")
        assert result[0].score == expected

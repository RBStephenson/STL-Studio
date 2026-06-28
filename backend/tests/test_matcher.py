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
    _tokens,
    match_products_to_models,
)
from app.services.scrapers.storefront import StorefrontProduct


def _product(title: str) -> StorefrontProduct:
    return StorefrontProduct(title=title, source_url="https://x/p", source_site="gumroad")


def _model(id_: int, name: str = "", title: str | None = None, folder: str = "/f",
           character: str | None = None, auto_tags: list | None = None) -> dict:
    return {"id": id_, "name": name, "title": title, "character": character,
            "auto_tags": auto_tags or [], "folder_path": folder}


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


# ---------------------------------------------------------------------------
# #353 — scale separators are normalized by _STRIP_RE alone (no scale regex)
# ---------------------------------------------------------------------------

class TestTokens:
    def test_scale_separators_produce_identical_tokens(self):
        # "/", "-", ":" are all non-word chars stripped to spaces, so every
        # separator form tokenizes the same way. Guards against reintroducing a
        # dedicated scale regex (the removed _SCALE_RE, which never fired).
        assert _tokens("1/6scale") == _tokens("1-6scale") == _tokens("1:6scale")

    def test_scale_separator_does_not_survive_as_token(self):
        assert _tokens("1/6 figure") == {"figure"}


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
# character identity matching (#626)
# ---------------------------------------------------------------------------

class TestCharacterMatching:
    def test_character_drives_match_when_name_is_noisy(self):
        # Raw name is all structural noise; character carries the identity.
        products = [_product("Ada Wong Resident Evil 1/6 Scale")]
        models = [_model(1, name="Unsupported_Hollow_v2", character="Ada Wong")]
        result = match_products_to_models(products, models)
        assert len(result) == 1
        assert result[0].score >= 0.30  # would be ~0 without character

    def test_character_full_coverage_adds_bonus(self):
        products = [_product("Leon Kennedy figure")]
        with_char = match_products_to_models(products, [_model(1, name="Leon Kennedy", character="Leon Kennedy")])
        without_char = match_products_to_models(products, [_model(2, name="Leon Kennedy")])
        assert with_char[0].score > without_char[0].score

    def test_character_picks_the_right_product(self):
        products = [_product("Generic Bust Pack"), _product("Jill Valentine Statue")]
        models = [_model(1, name="bust_v1", character="Jill Valentine")]
        result = match_products_to_models(products, models)
        assert result[0].product.title == "Jill Valentine Statue"

    def test_no_character_falls_back_to_name(self):
        products = [_product("Akuma Street Fighter")]
        result = match_products_to_models([*products], [_model(1, name="Akuma", character=None)])
        assert len(result) == 1
        assert result[0].score > 0

    def test_bonus_capped_at_one(self):
        products = [_product("Ada Wong")]
        result = match_products_to_models(products, [_model(1, name="Ada Wong", character="Ada Wong")])
        assert result[0].score <= 1.0


# ---------------------------------------------------------------------------
# scale token re-added from auto_tags (#627)
# ---------------------------------------------------------------------------

class TestScaleMatching:
    def test_mm_scale_boosts_matching_product(self):
        # display_name stripped scale; auto_tags re-add it so the 75mm listing wins.
        products = [_product("Orc Warrior 75mm"), _product("Orc Warrior 32mm")]
        with_scale = match_products_to_models(products, [_model(1, name="Orc Warrior", auto_tags=["75mm"])])
        assert with_scale[0].product.title == "Orc Warrior 75mm"

    def test_scale_raises_score_vs_no_scale(self):
        products = [_product("Orc Warrior 75mm bust")]
        with_scale = match_products_to_models(products, [_model(1, name="Orc Warrior", auto_tags=["75mm"])])
        without = match_products_to_models(products, [_model(2, name="Orc Warrior", auto_tags=[])])
        assert with_scale[0].score >= without[0].score

    def test_scale_alone_does_not_create_false_match(self):
        # No name overlap, only shared scale → must not produce a spurious match.
        products = [_product("Totally Different Thing 75mm")]
        result = match_products_to_models(
            products, [_model(1, name="", auto_tags=["75mm"])], min_score=0.20
        )
        assert result == []

    def test_non_scale_auto_tags_ignored(self):
        # Only scale-shaped tags are injected; "bust"/"nsfw" don't leak in here.
        products = [_product("Generic 75mm")]
        result = match_products_to_models(
            products, [_model(1, name="Hero", auto_tags=["bust", "nsfw"])], min_score=0.20
        )
        assert result == []


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

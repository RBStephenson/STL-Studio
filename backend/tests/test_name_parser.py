"""
Tests for name_parser — pure functions, no DB or network needed.
"""
import pytest
from app.services import name_parser
from app.services.name_parser import parse, parse_folder, children_look_like_parts, extract_character_name


# ---------------------------------------------------------------------------
# Scale detection
# ---------------------------------------------------------------------------

class TestScaleRatio:
    def test_standard_colon(self):
        sig = parse("Dragon 1:6 Scale")
        assert "1:6" in sig.scales

    def test_slash_separator(self):
        sig = parse("Knight 1/12")
        assert "1:12" in sig.scales

    def test_dash_separator(self):
        sig = parse("Warrior 1-6")
        assert "1:6" in sig.scales

    def test_no_false_positive_on_plain_number(self):
        sig = parse("Pack 01")
        assert not sig.scales


class TestScaleMM:
    @pytest.mark.parametrize("mm", ["28mm", "32mm", "75mm", "54mm", "120mm"])
    def test_common_scales(self, mm):
        sig = parse(f"Orc {mm}")
        assert mm in sig.scales

    def test_case_insensitive(self):
        sig = parse("Paladin 28MM")
        assert "28mm" in sig.scales

    def test_non_miniature_size_ignored(self):
        sig = parse("Box 100mm width")
        assert not sig.scales


# ---------------------------------------------------------------------------
# Type keyword detection
# ---------------------------------------------------------------------------

class TestTypeDetection:
    @pytest.mark.parametrize("word,expected_tag", [
        ("bust", "bust"),
        ("Busts", "bust"),
        ("statue", "statue"),
        ("miniature", "miniature"),
        ("mini", "miniature"),
        ("terrain", "terrain"),
        ("diorama", "diorama"),
        ("dnd", "dnd"),
        ("DnD", "dnd"),
        ("RPG", "rpg"),
        ("wargame", "wargame"),
    ])
    def test_type_keyword(self, word, expected_tag):
        sig = parse(f"Undead {word}")
        assert expected_tag in sig.types

    def test_no_type_for_plain_name(self):
        sig = parse("Akuma")
        assert not sig.types


# ---------------------------------------------------------------------------
# Modifier detection
# ---------------------------------------------------------------------------

class TestModifierDetection:
    @pytest.mark.parametrize("word", [
        "pre-supported", "presupported", "presup", "pre sup", "Supported"
    ])
    def test_presupported_variants(self, word):
        sig = parse(f"Dragon {word}")
        assert "pre-supported" in sig.modifiers

    def test_nsfw_modifier(self):
        sig = parse("Elf NSFW")
        assert "nsfw" in sig.modifiers

    def test_pinup_modifier(self):
        sig = parse("Paladin Pin-Up")
        assert "pin-up" in sig.modifiers


# ---------------------------------------------------------------------------
# is_product and confidence
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_no_signals_low_confidence(self):
        sig = parse("Akuma")
        assert sig.confidence == pytest.approx(0.2)
        assert not sig.is_product

    def test_scale_boosts_confidence(self):
        sig = parse("Dragon 28mm")
        assert sig.is_product
        assert sig.confidence > 0.4

    def test_multiple_signals_higher_confidence(self):
        sig_single = parse("Dragon 28mm")
        sig_multi = parse("Dragon 28mm Bust Pre-Supported")
        assert sig_multi.confidence > sig_single.confidence

    def test_confidence_capped_at_one(self):
        sig = parse("Dragon 28mm 32mm Bust Statue Pre-Supported NSFW Terrain")
        assert sig.confidence <= 1.0


# ---------------------------------------------------------------------------
# Parts detection
# ---------------------------------------------------------------------------

class TestPartsDetection:
    @pytest.mark.parametrize("name", [
        "base", "bases", "body", "head", "heads", "arms", "legs",
        "weapons", "accessories", "parts", "support",
    ])
    def test_exact_parts_names(self, name):
        sig = parse(name)
        assert sig.is_parts

    def test_parts_pattern(self):
        # Underscore is a word char, so use space/hyphen for the boundary to work
        sig = parse("Extra Parts")
        assert sig.is_parts

    def test_product_name_not_parts(self):
        sig = parse("Barbarian Warrior 28mm")
        assert not sig.is_parts


class TestChildrenLookLikeParts:
    def test_majority_parts(self):
        assert children_look_like_parts(["head", "body", "arms", "base", "legs"])

    def test_majority_not_parts(self):
        # Names need explicit signals (scale/type/modifier) to score above the
        # confidence threshold; plain names score 0.2 and are treated as parts-like
        assert not children_look_like_parts([
            "Dragon 28mm Bust",
            "Undead Knight Pre-Supported",
            "Orc Shaman Miniature",
        ])

    def test_empty_list(self):
        assert not children_look_like_parts([])

    def test_mixed_below_threshold(self):
        # 1/4 parts names — the other 3 have explicit signals → below 60% threshold
        assert not children_look_like_parts([
            "head",
            "Dragon 28mm Bust",
            "Orc 32mm Pre-Supported",
            "Undead Knight Miniature",
        ])


# ---------------------------------------------------------------------------
# parse_folder — file name + parent name inheritance
# ---------------------------------------------------------------------------

class TestParseFolder:
    def test_signal_from_filename(self):
        # Underscore is a word char, so \b28mm\b won't match "Akuma_28mm".
        # Use hyphens (non-word chars) so the regex boundary works.
        sig = parse_folder(
            "/creator/Akuma",
            filenames=["Akuma-28mm-Bust.stl"],
        )
        assert "28mm" in sig.scales
        assert "bust" in sig.types
        assert sig.is_product

    def test_scale_inherited_from_parent(self):
        sig = parse_folder(
            "/creator/75mm Scale/Akuma",
            parent_names=["75mm Scale"],
        )
        assert "75mm" in sig.scales

    def test_parts_not_overridden_by_parent_signal(self):
        sig = parse_folder(
            "/creator/75mm Scale/head",
            parent_names=["75mm Scale"],
        )
        assert sig.is_parts
        assert not sig.is_product

    def test_no_signals_returns_low_confidence(self):
        sig = parse_folder("/creator/MyPack")
        assert sig.confidence == pytest.approx(0.2)
        assert not sig.is_product


# ---------------------------------------------------------------------------
# extract_character_name
# ---------------------------------------------------------------------------

class TestExtractCharacterName:
    def test_strips_scale(self):
        result = extract_character_name("Akuma 28mm")
        assert "28mm" not in result
        assert "Akuma" in result

    def test_strips_type(self):
        result = extract_character_name("Dragon Bust")
        assert "Bust" not in result
        assert "Dragon" in result

    def test_strips_modifier(self):
        result = extract_character_name("Knight Pre-Supported")
        assert "pre-supported" not in result.lower()

    def test_plain_name_unchanged(self):
        result = extract_character_name("Akuma")
        assert result == "Akuma"

"""
Tests for name_parser — pure functions, no DB or network needed.
"""
import pytest
from app.services import name_parser
from app.services.name_parser import (
    parse,
    parse_folder,
    children_look_like_parts,
    extract_character_name,
    character_key,
    support_status,
    cut_status,
    slicer,
    version,
    parsed_attributes,
    display_name,
)


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
        ("garage kit", "garage kit"),
        ("Garage Kits", "garage kit"),
        ("GK", "garage kit"),
        ("resin", "resin"),
        ("maquette", "maquette"),
        ("collectible", "collectible"),
    ])
    def test_type_keyword(self, word, expected_tag):
        sig = parse(f"Undead {word}")
        assert expected_tag in sig.types

    def test_no_type_for_plain_name(self):
        sig = parse("Akuma")
        assert not sig.types

    def test_garage_kit_does_not_regress_bare_kit(self):
        # "garage kit" tags as its own type without losing the bare "kit" match
        # elsewhere in a name that mentions both.
        sig = parse("Model Kit Garage Kit")
        assert "garage kit" in sig.types
        assert "kit" in sig.types


# ---------------------------------------------------------------------------
# Modifier detection
# ---------------------------------------------------------------------------

class TestModifierDetection:
    @pytest.mark.parametrize("word", [
        "pre-supported", "presupported", "presup", "pre sup"
    ])
    def test_presupported_variants(self, word):
        sig = parse(f"Dragon {word}")
        assert "pre-supported" in sig.modifiers

    def test_plain_supported_is_not_presupported(self):
        # Plain "Supported" is its own support status, not pre-supported. It is
        # surfaced via support_status(), not as a "pre-supported" modifier tag.
        sig = parse("Dragon Supported")
        assert "pre-supported" not in sig.modifiers

    def test_nsfw_modifier(self):
        sig = parse("Elf NSFW")
        assert "nsfw" in sig.modifiers

    def test_pinup_modifier(self):
        sig = parse("Paladin Pin-Up")
        assert "pin-up" in sig.modifiers

    @pytest.mark.parametrize("word,expected_tag", [
        ("Deluxe", "deluxe"),
        ("Exclusive", "exclusive"),
        ("Limited Edition", "limited edition"),
        ("Bonus", "bonus"),
    ])
    def test_edition_modifier(self, word, expected_tag):
        sig = parse(f"Statue {word}")
        assert expected_tag in sig.modifiers


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


# ---------------------------------------------------------------------------
# character_key — normalised product identity for variant grouping
# ---------------------------------------------------------------------------

class TestCharacterKey:
    def test_support_variants_collapse_to_same_key(self):
        # Loot-style: same product, different support/format → one product identity
        assert character_key("AleCask_32mm_UnSupported") == character_key("AleCask_32mm_Supported_Solid")
        assert character_key("AleCask_32mm_UnSupported") == "AleCask"

    def test_supported_unsupported_pair(self):
        # DakkaDakka-style: support status stripped, product name preserved
        assert character_key("Crimson Wings APC supported") == "Crimson Wings APC"
        assert character_key("Crimson Wings APC unsupported") == "Crimson Wings APC"

    @pytest.mark.parametrize("name", [
        "Unsupported", "Supported_Solid", "75mm Unsupported", "Presupported", "Solid",
        "Full_cutted", "Full cutted", "Full cut",
    ])
    def test_pure_variant_descriptor_is_empty(self, name):
        assert character_key(name) == ""

    def test_pure_variant_modifiers_empty(self):
        # CA3D-style leaf names that are only scale/cut descriptors → no identity
        assert character_key("1,12 pre supports") == ""
        assert character_key("1,12 uncut") == ""

    def test_full_cutted_stripped_from_character_name(self):
        # "Full_cutted" is a print-prep variant (pre-separated parts), not a character.
        # It must be stripped so that e.g. Cloud/Full_cutted and Wolverine/Full_cutted
        # are not grouped together as variants of each other.
        assert character_key("Cloud_Full_cutted") == "Cloud"
        assert character_key("Wolverine Full cutted") == "Wolverine"

    def test_distinct_products_keep_distinct_keys(self):
        assert character_key("AleCask_32mm_UnSupported") != character_key("Barrel_32mm_UnSupported")

    def test_slicer_folder_names_have_no_identity(self):
        # STUDIO-281: a bare slicer/format folder is not a character — without this,
        # every creator's "LYS" folder collapsed into one cross-character bucket.
        assert character_key("LYS") == ""
        assert character_key("CTB") == ""

    def test_slicer_token_stripped_from_character_name(self):
        # A character nested under / suffixed with a slicer format must reduce to the
        # same identity regardless of format, so LYS and STL variants group together.
        assert character_key("Spiderman LYS") == character_key("Spiderman STL")
        assert character_key("Spiderman LYS") == "Spiderman"

    def test_plain_name_unchanged(self):
        assert character_key("Catwoman") == "Catwoman"

    def test_release_number_marker_stripped_entirely(self):
        # "#1234"-style Patreon post-ID suffix — the digits alone would already be
        # stripped as junk, but the "#" must go too, not survive as a stray char.
        assert character_key("Cold Giant#4521") == "Cold Giant"
        assert character_key("Cold Giant#") == "Cold Giant"

    def test_release_number_variants_still_group_together(self):
        # Two scrapes of the same product with different post IDs must reduce to
        # the same key, same as any other variant-only difference.
        assert character_key("Catfolk Rogues#187") == character_key("Catfolk Rogues#204")

    def test_scale_word_does_not_split_variants(self):
        # CA3D-style: the word "scale" survives after "1-9" is stripped from
        # "1-9 scale ...". It must not produce a different key from "1-6 ...".
        assert character_key("1-6 Ada Wong CA3D") == character_key("1-9 scale Ada Wong CA3D")
        assert character_key("1-6 Ada Wong CA3D") == "Ada Wong CA3D"
        assert character_key("1_12 scale Afro Samurai CA3D") == "Afro Samurai CA3D"

    def test_unlisted_mm_size_is_stripped(self):
        # Two bust sizes of one character are variants, not distinct products.
        assert character_key("Chucky_Bust_160mm") == character_key("Chucky_Bust_240mm") == "Chucky"

    def test_container_and_flag_words_stripped(self):
        assert character_key("STL Ada Wong Bust") == "Ada Wong"
        assert character_key("Ahsoka_STL") == character_key("Ahsoka_NSFW_STL") == "Ahsoka"

    @pytest.mark.parametrize("name", ["15", "20", "300", "1-6 scale", "scale"])
    def test_bare_number_or_scale_word_is_empty(self, name):
        assert character_key(name) == ""

    def test_digit_in_character_name_preserved(self):
        # "2B" (NieR: Automata) must survive — there is no word boundary in "2B".
        assert character_key("2B") == "2B"

    def test_leading_number_dot_prefix_stripped_cleanly(self):
        # "1." ordering prefix: the digit is removed by _VARIANT_JUNK and the
        # orphaned period must not survive as a leading character.
        assert character_key("1.JSC Batgirl Regular") == "JSC Batgirl Regular"

    # --- creator_name suffix stripping ---

    def test_creator_full_name_stripped_as_suffix(self):
        # The creator's full name spelled out at the end is stripped.
        assert character_key("Ada Wong CA 3D Studios", "CA 3D Studios") == "Ada Wong"

    def test_single_token_creator_stripped_as_suffix(self):
        # A one-word creator name is its own full name, so it strips as a suffix.
        assert character_key("Barbarian Ghamak", "Ghamak") == "Barbarian"

    def test_creator_concatenated_abbreviation_stripped(self):
        # "CA 3D Studios" → consecutive joins include "CA3D".
        # Folders tagged "CA3D" (the studio's abbreviation) collapse with untagged ones.
        assert character_key("Ada Wong CA3D", "CA 3D Studios") == "Ada Wong"
        assert character_key("1-6 Ada Wong CA3D", "CA 3D Studios") == "Ada Wong"
        assert character_key("Cyclops CA3D", "CA 3D Studios") == "Cyclops"

    def test_creator_tag_after_scale_stripped(self):
        # Scale tokens are removed first; the CA3D suffix is then stripped.
        assert character_key("1,12 pre supports Jaina CA3D", "CA 3D Studios") == "Jaina"

    def test_creator_tag_only_not_stripped_empty_guard(self):
        # When the entire key is just the creator tag, leave it — empty key would
        # wrongly make the folder inherit its parent's character.
        assert character_key("CA3D", "CA 3D Studios") == "CA3D"

    def test_creator_tag_not_stripped_from_middle(self):
        # Creator tag in the middle of a name is left alone; only trailing tags
        # are stripped to avoid clobbering real character names.
        assert character_key("CA3D Dragon", "CA 3D Studios") == "CA3D Dragon"

    @pytest.mark.parametrize("folder,creator,expected", [
        # A lone word of a multi-word creator name must NOT be stripped, even when
        # it ends the folder name — it is almost always part of the character.
        ("Red Dragon", "Dragon Studios", "Red Dragon"),
        ("Big Boss", "Big Boss Studios", "Big Boss"),
        ("Stone Titan", "Titan Forge", "Stone Titan"),
        ("Iron Giant", "Giant Miniatures", "Iron Giant"),
    ])
    def test_partial_creator_word_not_stripped(self, folder, creator, expected):
        assert character_key(folder, creator) == expected

    def test_no_creator_name_unchanged(self):
        # Without a creator_name, existing behaviour is preserved.
        assert character_key("Ada Wong CA3D") == "Ada Wong CA3D"


# ---------------------------------------------------------------------------
# is_structural_folder — variant-grouping character must skip structural folders
# ---------------------------------------------------------------------------

class TestIsStructuralFolder:
    @pytest.mark.parametrize("name", [
        "STL", "Lychee", "Presupport", "Presupports", "Supported", "Unsupported",
        "no_supported", "Supports", "Renders", "Render Images", "Colored Turntable",
        "75mm", "178mm", "Bust", "1-10 Scale", "1-10 Scale Split", "Supported Solid",
        "32mm Supported", "parts", "base",
        "Full_cutted", "Full cutted", "Full cut", "cutted",
        # Slicer project/output + pre-slice prep folders (STUDIO-281).
        "LYS", "lys", "CTB", "Chitu", "Sliced", "Presliced", "Pre-Sliced",
        # Sized/shaped base folders (STUDIO-286). One Page Rules ships one under
        # every unit; the shape list arrives glued inside parens with a "+".
        "Bases 25mm-32mm (Round+Square)",
        "Bases 100mm-150mm (Oval+Rectangle)",
        "Bases 60mm-100mm (Round+Rectangle)",
        "Bases 50mm-60mm (Oval+Rectangle)",
        "Bases (Round)", "Base 32mm Round", "Bases Hex",
        # Cut-prep siblings (STUDIO-288). "Full_cutted" was already covered; its
        # "Semi_cutted" counterpart and the plural "cuts" forms were not.
        "Semi_cutted", "semi_cutted", "SEMI_CUTTED", "Semi cut", "semi-cutted",
        "Semi cuts", "Full_cuts",
    ])
    def test_structural_names(self, name):
        assert name_parser.is_structural_folder(name) is True

    @pytest.mark.parametrize("name", [
        "Auron - Final Fantasy X", "Alita", "Barbatos - Gundam", "Goblin Warband",
        "Chibi Kirara - Inuyasha", "Spider Noir",
        # A base-geometry word next to a real name must NOT read as structural —
        # the all-tokens rule is what keeps STUDIO-286's vocabulary safe.
        "Round Table Knight", "Oval Office Diorama", "Rectangle Sam",
        "Squarejaw Sarge",
        # Bare "semi" is deliberately absent from the cut-prep vocabulary — these
        # are the names it would wrongly swallow (STUDIO-288).
        "Semi", "Semiramis", "Semiramis Fate", "Semi Truck Driver",
    ])
    def test_character_names(self, name):
        assert name_parser.is_structural_folder(name) is False


# ---------------------------------------------------------------------------
# Generic-name qualification (STUDIO-287)
# ---------------------------------------------------------------------------

class TestGenericNameQualification:
    @pytest.mark.parametrize("name", ["Bases", "Base", "Parts", "Base Supported"])
    def test_generic_names(self, name):
        assert name_parser.is_generic_name(name) is True

    @pytest.mark.parametrize("name", [
        "Gridrunner", "Grim Realms", "Bases Round and Oval", "Civilians",
    ])
    def test_identifying_names_not_generic(self, name):
        assert name_parser.is_generic_name(name) is False

    def test_empty_name_is_not_generic(self):
        # Guards the bool(name.strip()) short-circuit — an empty name has nothing
        # to qualify and must not send the scanner up the ancestor chain.
        assert name_parser.is_generic_name("") is False
        assert name_parser.is_generic_name("   ") is False

    @pytest.mark.parametrize("name", ["Models", "model", "STL", "Print Files"])
    def test_container_folders(self, name):
        assert name_parser.is_container_folder(name) is True

    @pytest.mark.parametrize("name", ["RPG Bases", "Gridrunner", "October 2024"])
    def test_non_container_folders(self, name):
        assert name_parser.is_container_folder(name) is False

    @pytest.mark.parametrize("folder,expected", [
        # Ordering prefixes stripped, separators collapsed.
        ("52 - OCTOBER 2024 REANIMATION", "October 2024 Reanimation"),
        ("59 - October 24 - Orc and Carnival 2 Bases",
         "October 24 Orc And Carnival 2 Bases"),
        ("03 - Bases", "Bases"),
        ("12_Winter Release", "Winter Release"),
        # Raw name is kept even when every token is a parts word — this is the
        # whole point of not routing the qualifier through display_name.
        ("RPG Bases", "RPG Bases"),
        # An interior hyphen inside a word survives.
        ("Pre-Order Bundle", "Pre-Order Bundle"),
    ])
    def test_qualifier_from_folder(self, folder, expected):
        assert name_parser.qualifier_from_folder(folder) == expected

    @pytest.mark.parametrize("generic,qualifier,expected", [
        ("Bases", "October 2024 Reanimation", "October 2024 Reanimation Bases"),
        # Qualifier already ends with the generic word — no doubling up.
        ("Bases", "RPG Bases", "RPG Bases"),
        ("Bases", "rpg bases", "rpg bases"),
        # No usable qualifier falls back to the generic name unchanged.
        ("Bases", "", "Bases"),
    ])
    def test_qualify_generic_name(self, generic, qualifier, expected):
        assert name_parser.qualify_generic_name(generic, qualifier) == expected


# ---------------------------------------------------------------------------
# Structured attribute extractors
# ---------------------------------------------------------------------------

class TestSupportStatus:
    @pytest.mark.parametrize("name,expected", [
        ("Dragon Unsupported", "unsupported"),
        ("Dragon UnSupported", "unsupported"),
        ("Dragon un-supported", "unsupported"),
        ("Dragon_No_Supports", "unsupported"),
        ("Dragon NoSupport", "unsupported"),
        ("Dragon Pre-Supported", "pre-supported"),
        ("Dragon presupported", "pre-supported"),
        ("Dragon_PreSup", "pre-supported"),
        ("Dragon Supported", "supported"),
        ("AleCask_32mm_Supported_Solid", "supported"),
    ])
    def test_status(self, name, expected):
        assert support_status(name) == expected

    def test_none_when_absent(self):
        assert support_status("Akuma 28mm Bust") is None

    def test_unsupported_not_read_as_supported(self):
        # "supported" is a substring of "unsupported"; ordering must not misread it.
        assert support_status("Crimson Wings APC unsupported") == "unsupported"


class TestCutStatus:
    @pytest.mark.parametrize("name,expected", [
        ("Hero Solid", "solid"),
        ("Hero Hollow", "hollow"),
        ("Hero Hollowed", "hollow"),
        ("Hero Split", "split"),
        ("Hero Merged", "merged"),
        ("Hero Merge", "merged"),
        ("Hero Full_cut", "full-cut"),
        ("Hero Full cutted", "full-cut"),
        ("Hero fullcut", "full-cut"),
    ])
    def test_status(self, name, expected):
        assert cut_status(name) == expected

    def test_none_when_absent(self):
        assert cut_status("Akuma 28mm") is None


class TestSlicer:
    @pytest.mark.parametrize("name,expected", [
        ("Dragon Lychee", "lychee"),
        ("Dragon_Chitubox", "chitubox"),
        ("Dragon CHITUBOX files", "chitubox"),
    ])
    def test_slicer(self, name, expected):
        assert slicer(name) == expected

    def test_none_when_absent(self):
        assert slicer("Akuma 28mm") is None


class TestVersion:
    @pytest.mark.parametrize("name,expected", [
        ("Dragon v2", "v2"),
        ("Dragon V1", "v1"),
        ("Dragon_v1.1", "v1.1"),
    ])
    def test_version(self, name, expected):
        assert version(name) == expected

    @pytest.mark.parametrize("name", ["Auron Final Fantasy X", "Vader", "Akuma 28mm"])
    def test_none_when_absent(self, name):
        # "Final"/"Fixed" word-forms are intentionally not versions (name collisions).
        assert version(name) is None


class TestParsedAttributes:
    def test_collects_all(self):
        attrs = parsed_attributes("Ada Wong 1-6 Unsupported Hollow Chitubox v2")
        assert attrs == {
            "support_status": "unsupported",
            "cut_status": "hollow",
            "slicer": "chitubox",
            "version": "v2",
        }

    def test_omits_none(self):
        assert parsed_attributes("Akuma") == {}


# ---------------------------------------------------------------------------
# display_name — clean, human-readable product name for the UI
# ---------------------------------------------------------------------------

class TestDisplayName:
    @pytest.mark.parametrize("folder,expected", [
        ("AleCask_32mm_UnSupported", "AleCask"),  # mixed-case stylisation preserved
        ("ada wong 1-6 supported", "Ada Wong"),
        ("Crimson Wings APC unsupported", "Crimson Wings APC"),
        ("STL Ada Wong Bust", "Ada Wong"),
        ("1.JSC Batgirl Regular", "JSC Batgirl Regular"),
        ("Dragon Hollow v2", "Dragon"),
    ])
    def test_clean_name(self, folder, expected):
        assert display_name(folder) == expected

    def test_preserves_stylised_tokens(self):
        assert display_name("2B unsupported") == "2B"
        assert display_name("Ada Wong CA3D", "CA 3D Studios") == "Ada Wong"

    def test_strips_creator_suffix(self):
        assert display_name("Barbarian Ghamak", "Ghamak") == "Barbarian"

    def test_falls_back_to_raw_when_empty(self):
        # Pure variant descriptor → nothing identifying → keep the raw folder name.
        assert display_name("75mm Unsupported") == "75mm Unsupported"

    @pytest.mark.parametrize("folder,expected", [
        ("Cold Giant#4521", "Cold Giant"),  # Cast N Play-style Patreon post-ID suffix
        ("Catfolk Rogues Cast N Play#187", "Catfolk Rogues Cast N Play"),
        ("Product #7 Special", "Product Special"),  # marker mid-name, not just trailing
        ("Cold Giant#", "Cold Giant"),  # bare marker, no digits
    ])
    def test_strips_release_number_marker_without_leaving_a_stray_hash(self, folder, expected):
        assert display_name(folder) == expected

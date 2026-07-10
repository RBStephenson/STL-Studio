"""Tests for OS-aware path-segment sanitization (#323)."""
from app.services.path_sanitize import (
    MAX_COMPONENT_LEN,
    MAX_PATH_LEN,
    path_over_length,
    sanitize_segment,
    slug_filename,
)


class TestSanitizeSegment:
    def test_clean_name_unchanged(self):
        r = sanitize_segment("Absolute Joker")
        assert r.value == "Absolute Joker"
        assert not r.reserved_name
        assert not r.over_length

    def test_forbidden_chars_replaced(self):
        r = sanitize_segment('a<b>c:d"e/f\\g|h?i*j')
        assert "<" not in r.value and "/" not in r.value and "\\" not in r.value
        assert r.value == "a_b_c_d_e_f_g_h_i_j"

    def test_control_chars_replaced(self):
        r = sanitize_segment("tab\tnull\x00end")
        assert "\t" not in r.value and "\x00" not in r.value

    def test_trailing_dots_and_spaces_stripped(self):
        assert sanitize_segment("name...  ").value == "name"

    def test_empty_falls_back_to_underscore(self):
        assert sanitize_segment("").value == "_"
        assert sanitize_segment("...").value == "_"

    def test_reserved_name_flagged_and_prefixed(self):
        r = sanitize_segment("CON")
        assert r.reserved_name
        assert r.value == "_CON"

    def test_reserved_name_with_extension_flagged(self):
        r = sanitize_segment("nul.txt")
        assert r.reserved_name
        assert r.value.startswith("_")

    def test_reserved_check_case_insensitive(self):
        assert sanitize_segment("CoM1").reserved_name

    def test_non_reserved_lookalike_not_flagged(self):
        assert not sanitize_segment("CONSOLE").reserved_name

    def test_over_length_flagged_not_truncated(self):
        long = "x" * (MAX_COMPONENT_LEN + 10)
        r = sanitize_segment(long)
        assert r.over_length
        assert len(r.value) == MAX_COMPONENT_LEN + 10  # not truncated

    def test_unicode_normalized_nfc(self):
        # decomposed é (e + combining acute) → composed é
        decomposed = "Pokémon".replace("é", "é")
        r = sanitize_segment(decomposed)
        assert r.value == "Pokémon"


class TestPathOverLength:
    def test_under_limit(self):
        assert not path_over_length("C:/x/y")

    def test_over_limit(self):
        assert path_over_length("C:/" + "a" * MAX_PATH_LEN)


class TestSlugFilename:
    def test_slugs_stem_preserves_extension(self):
        assert slug_filename("Cold Giant last time hollowed.stl") == "cold-giant-last-time-hollowed.stl"

    def test_extension_lowercased(self):
        assert slug_filename("Model.STL") == "model.stl"

    def test_multiple_dots_uses_last_as_extension_boundary(self):
        assert slug_filename("Model.v2.stl") == "model-v2.stl"

    def test_no_extension_slugs_in_full(self):
        assert slug_filename("README") == "readme"

    def test_accents_stripped(self):
        assert slug_filename("Pokémon.stl") == "pokemon.stl"

"""Per-subtree grouping-strategy policy (#618, STUDIO-240).

Pure tests — no database, no session. These pin the contract the API layer and
the grouping engine now share instead of each reaching into private helpers.
"""
import pytest

from app.services.grouping_strategy import (
    DEFAULT_STRATEGY,
    SubtreeStrategy,
    is_within,
    normalize_path,
    parse_strategy,
    resolve_subtree_strategy,
)


class TestNormalizePath:
    def test_unifies_separators(self):
        assert normalize_path("C:\\lib\\creator") == "C:/lib/creator"

    def test_drops_a_trailing_separator(self):
        assert normalize_path("/lib/creator/") == "/lib/creator"
        assert normalize_path("C:\\lib\\creator\\") == "C:/lib/creator"

    def test_mixed_separator_styles_compare_equal(self):
        assert normalize_path("C:\\lib/creator\\") == normalize_path("C:/lib/creator")

    def test_leaves_an_already_normal_path_alone(self):
        assert normalize_path("/lib/creator") == "/lib/creator"


class TestIsWithin:
    def test_exact_path_matches(self):
        assert is_within("/lib/creator", "/lib/creator")

    def test_descendant_matches(self):
        assert is_within("/lib/creator/model", "/lib/creator")

    def test_deep_descendant_matches(self):
        assert is_within("/lib/creator/sub/deeper/model", "/lib/creator")

    def test_sibling_prefix_does_not_match(self):
        # The separator boundary is what stops STLBackup being read as STL's child.
        assert not is_within("/lib/STLBackup/model", "/lib/STL")

    def test_sibling_prefix_without_separator_does_not_match(self):
        assert not is_within("/lib/STLBackup", "/lib/STL")

    def test_ancestor_is_not_within_its_own_descendant(self):
        assert not is_within("/lib", "/lib/creator")

    def test_unrelated_path_does_not_match(self):
        assert not is_within("/other/model", "/lib/creator")

    def test_matching_tolerates_separator_style(self):
        assert is_within("C:\\lib\\creator\\model", "C:/lib/creator")


class TestParseStrategy:
    @pytest.mark.parametrize(("value", "expected"), [
        ("auto", SubtreeStrategy.AUTO),
        ("off", SubtreeStrategy.OFF),
    ])
    def test_accepts_the_documented_values(self, value, expected):
        assert parse_strategy(value) is expected

    @pytest.mark.parametrize("value", ["", "AUTO", "Off", "on", "disabled", "none"])
    def test_rejects_anything_else(self, value):
        with pytest.raises(ValueError, match="strategy must be one of"):
            parse_strategy(value)

    def test_the_error_names_the_allowed_values(self):
        with pytest.raises(ValueError) as excinfo:
            parse_strategy("nope")

        message = str(excinfo.value)
        assert "'auto'" in message and "'off'" in message


class TestResolveSubtreeStrategy:
    def test_defaults_to_auto_with_nothing_configured(self):
        assert resolve_subtree_strategy("/lib/creator/model", []) is SubtreeStrategy.AUTO
        assert DEFAULT_STRATEGY is SubtreeStrategy.AUTO

    def test_defaults_to_auto_when_no_ancestor_matches(self):
        assert resolve_subtree_strategy("/other/model", [("/lib", "off")]) is SubtreeStrategy.AUTO

    def test_an_ancestor_off_applies_to_descendants(self):
        assert resolve_subtree_strategy("/lib/creator/model", [("/lib", "off")]) is SubtreeStrategy.OFF

    def test_exact_path_configuration_applies(self):
        assert resolve_subtree_strategy("/lib/creator", [("/lib/creator", "off")]) is SubtreeStrategy.OFF

    def test_nearer_auto_overrides_an_outer_off(self):
        strategies = [("/lib", "off"), ("/lib/creator/sub", "auto")]

        assert resolve_subtree_strategy(
            "/lib/creator/sub/model", strategies
        ) is SubtreeStrategy.AUTO

    def test_nearer_off_overrides_an_outer_auto(self):
        strategies = [("/lib", "auto"), ("/lib/creator/sub", "off")]

        assert resolve_subtree_strategy(
            "/lib/creator/sub/model", strategies
        ) is SubtreeStrategy.OFF

    def test_sibling_subtree_configuration_is_ignored(self):
        assert resolve_subtree_strategy(
            "/lib/STLBackup/model", [("/lib/STL", "off")]
        ) is SubtreeStrategy.AUTO

    def test_equal_length_ancestors_resolve_the_same_either_way(self):
        forward = [("/lib/aaa", "off"), ("/lib/bbb", "auto")]
        model = "/lib/bbb/model"

        assert resolve_subtree_strategy(model, forward) is SubtreeStrategy.AUTO
        assert resolve_subtree_strategy(model, list(reversed(forward))) is SubtreeStrategy.AUTO

    def test_input_order_never_changes_the_answer(self):
        strategies = [("/lib", "off"), ("/lib/creator", "auto"), ("/lib/creator/sub", "off")]

        results = {
            resolve_subtree_strategy("/lib/creator/sub/model", list(order))
            for order in (strategies, reversed(strategies), sorted(strategies))
        }

        assert results == {SubtreeStrategy.OFF}

    def test_normalises_stored_paths(self):
        # Stored Windows paths with a trailing separator still match.
        assert resolve_subtree_strategy(
            "C:/lib/creator/model", [("C:\\lib\\creator\\", "off")]
        ) is SubtreeStrategy.OFF

    def test_unrecognised_stored_value_is_ignored(self):
        # A corrupt row must not break resolution for the subtree above it.
        strategies = [("/lib", "off"), ("/lib/creator", "bogus")]

        assert resolve_subtree_strategy(
            "/lib/creator/model", strategies
        ) is SubtreeStrategy.OFF

    def test_accepts_any_iterable_of_pairs(self):
        assert resolve_subtree_strategy(
            "/lib/creator/model", iter([("/lib", "off")])
        ) is SubtreeStrategy.OFF


class TestStrategyValuesStayWireCompatible:
    """The enum must serialise and compare exactly like the old bare strings."""

    def test_values_are_the_persisted_strings(self):
        assert SubtreeStrategy.AUTO == "auto"
        assert SubtreeStrategy.OFF == "off"

    def test_str_of_a_member_is_its_value(self):
        assert str(SubtreeStrategy.OFF) == "off"

    def test_members_are_usable_as_dict_keys_alongside_strings(self):
        assert {"off": 1}[SubtreeStrategy.OFF] == 1

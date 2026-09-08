"""Tests for the reorganize destination-template grammar (#323)."""
import pytest

from app.services.reorganize_template import (
    DEFAULT_TEMPLATE,
    ReorganizeTemplateError,
    parse_template,
    render_segments,
    segment_fields,
)


class TestParseTemplate:
    def test_default_when_blank(self):
        assert parse_template("") == ["{creator}", "{character}", "{title}"]
        assert parse_template(None) == ["{creator}", "{character}", "{title}"]
        assert parse_template("   ") == ["{creator}", "{character}", "{title}"]

    def test_strips_surrounding_slashes(self):
        assert parse_template("/{creator}/{title}/") == ["{creator}", "{title}"]

    def test_accepts_backslash_separators(self):
        assert parse_template(r"{creator}\{title}") == ["{creator}", "{title}"]

    def test_literal_segments_allowed(self):
        assert parse_template("Models/{creator}") == ["Models", "{creator}"]

    def test_token_with_literal_prefix(self):
        # mixed literal+token in one segment is allowed
        assert parse_template("creator-{creator}") == ["creator-{creator}"]

    def test_scale_field_allowed(self):
        assert parse_template("{creator}/{scale}/{title}") == [
            "{creator}", "{scale}", "{title}",
        ]

    def test_keep_field_allowed(self):
        """STUDIO-431. The grammar accepts {keep} unconditionally, even with the
        feature flag off: gating it at PARSE time would turn a template the user
        already saved into a 400 the moment they switched the flag back off. The
        flag is honoured where the value is resolved instead."""
        assert parse_template("{creator}/{keep?}/{character}/{title}") == [
            "{creator}", "{keep?}", "{character}", "{title}",
        ]
        assert parse_template("{creator}/{keep}/{title}") == [
            "{creator}", "{keep}", "{title}",
        ]

    def test_unknown_field_rejected(self):
        with pytest.raises(ReorganizeTemplateError, match="Unknown template field"):
            parse_template("{creator}/{franchise}")

    def test_the_unknown_field_message_names_keep(self):
        with pytest.raises(ReorganizeTemplateError, match=r"\{keep\}"):
            parse_template("{creator}/{franchise}")

    def test_keep_must_be_a_segment_of_its_own(self):
        """STUDIO-431. `{keep}` renders more than one folder level, so literal
        text or a second token beside it has no clean meaning — the literal
        would attach to the first level only. Rejected at parse time, like the
        all-optional rule."""
        with pytest.raises(ReorganizeTemplateError, match="segment of its own"):
            parse_template("{creator}/pack-{keep?}/{title}")
        with pytest.raises(ReorganizeTemplateError, match="segment of its own"):
            parse_template("{creator}/{keep?}{scale?}/{title}")
        with pytest.raises(ReorganizeTemplateError, match="segment of its own"):
            parse_template("{creator}/{keep}-x/{title}")
        assert parse_template("{creator}/{keep?}/{title}") == [
            "{creator}", "{keep?}", "{title}",
        ]

    def test_unbalanced_brace_rejected(self):
        with pytest.raises(ReorganizeTemplateError, match="unbalanced braces"):
            parse_template("{creator}/{title")

    def test_no_token_rejected(self):
        with pytest.raises(ReorganizeTemplateError, match="at least one"):
            parse_template("Models/Static")

    def test_default_constant_parses(self):
        assert parse_template(DEFAULT_TEMPLATE) == ["{creator}", "{character}", "{title}"]


class TestRenderSegments:
    def test_substitutes_fields(self):
        segs = parse_template("{creator}/{character}/{title}")
        out = render_segments(segs, {"creator": "Abe3D", "character": "Joker", "title": "Bust"})
        assert out == ["Abe3D", "Joker", "Bust"]

    def test_substitutes_scale_field(self):
        segs = parse_template("{creator}/{scale}/{title}")
        out = render_segments(
            segs,
            {"creator": "Abe3D", "character": "", "scale": "1:6", "title": "Bust"},
        )
        assert out == ["Abe3D", "1:6", "Bust"]

    def test_preserves_literals(self):
        segs = parse_template("Models/{creator}")
        out = render_segments(segs, {"creator": "Abe3D", "character": "", "title": ""})
        assert out == ["Models", "Abe3D"]

    def test_mixed_literal_and_token(self):
        segs = parse_template("by-{creator}")
        out = render_segments(segs, {"creator": "Abe3D", "character": "", "title": ""})
        assert out == ["by-Abe3D"]


class TestOptionalTokens:
    """STUDIO-407: a `?`-suffixed token contributes nothing when its value fell
    back, instead of forcing a sentinel and blocking the row."""

    VALUES = {"creator": "Abe3D", "character": "Joker", "scale": "_Unknown Scale", "title": "Bust"}

    def test_optional_token_parses_and_is_preserved_verbatim(self):
        assert parse_template("{creator}/{scale?}/{title}") == [
            "{creator}", "{scale?}", "{title}",
        ]

    def test_segment_fields_reports_name_and_optionality(self):
        assert segment_fields("{creator}") == [("creator", False)]
        assert segment_fields("{scale?}") == [("scale", True)]
        assert segment_fields("by-{creator}-{scale?}") == [("creator", False), ("scale", True)]
        assert segment_fields("Models") == []

    def test_unknown_optional_field_still_rejected(self):
        with pytest.raises(ReorganizeTemplateError, match="Unknown template field"):
            parse_template("{creator}/{franchise?}")

    def test_all_optional_template_rejected(self):
        # Every model would render to the same path and collide with everything.
        with pytest.raises(ReorganizeTemplateError, match="at least one required"):
            parse_template("{creator?}/{scale?}")

    def test_an_all_optional_template_is_still_rejected_with_keep(self):
        """{keep} must not become a loophole in the one rule that stops every
        model rendering to the same path — and it is the likeliest to be one,
        since a container level looks like it distinguishes models."""
        with pytest.raises(ReorganizeTemplateError, match="at least one required"):
            parse_template("{creator?}/{keep?}")

    def test_dropped_optional_segment_renders_empty(self):
        segs = parse_template("{creator}/{scale?}/{title}")
        assert render_segments(segs, self.VALUES, {"scale"}) == ["Abe3D", "", "Bust"]

    def test_rendered_list_keeps_segment_alignment(self):
        # The caller zips segments with the rendered output, so a dropped
        # segment must be an empty slot, never a shorter list.
        segs = parse_template("{creator}/{scale?}/{title}")
        assert len(render_segments(segs, self.VALUES, {"scale"})) == len(segs)

    def test_optional_token_kept_when_its_value_did_not_fall_back(self):
        segs = parse_template("{creator}/{scale?}/{title}")
        values = {**self.VALUES, "scale": "1:6"}
        assert render_segments(segs, values, set()) == ["Abe3D", "1:6", "Bust"]

    def test_segment_drops_with_its_literal_when_every_token_dropped(self):
        # "by-{scale?}" is meaningless without the scale — the literal goes too,
        # rather than leaving a bare "by-" directory.
        segs = parse_template("{creator}/by-{scale?}")
        assert render_segments(segs, self.VALUES, {"scale"}) == ["Abe3D", ""]

    def test_segment_survives_when_a_required_token_remains(self):
        # Only the optional token empties; the segment itself still has content,
        # so the trailing separator is the template author's own doing.
        segs = parse_template("{creator}-{scale?}")
        assert render_segments(segs, self.VALUES, {"scale"}) == ["Abe3D-"]

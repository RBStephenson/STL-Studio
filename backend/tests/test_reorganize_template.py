"""Tests for the reorganize destination-template grammar (#323)."""
import pytest

from app.services.reorganize_template import (
    DEFAULT_TEMPLATE,
    ReorganizeTemplateError,
    parse_template,
    render_segments,
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

    def test_unknown_field_rejected(self):
        with pytest.raises(ReorganizeTemplateError, match="Unknown template field"):
            parse_template("{creator}/{franchise}")

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

"""
Unit tests for configurable scan-root folder layouts (services/layout.py):
template parsing/validation, creator-dir resolution, and tag extraction.
"""
from pathlib import Path

import pytest

from app.services import layout


class TestParseTemplate:
    def test_blank_defaults_to_creator(self):
        assert layout.parse_template("") == ["creator"]
        assert layout.parse_template(None) == ["creator"]
        assert layout.parse_template("   ") == ["creator"]

    def test_default_template(self):
        assert layout.parse_template("{creator}") == ["creator"]

    def test_tag_above_creator(self):
        assert layout.parse_template("{tag}/{creator}") == ["tag", "creator"]

    def test_multiple_tags(self):
        assert layout.parse_template("{tag}/{tag}/{creator}") == ["tag", "tag", "creator"]

    def test_ignore_and_star(self):
        assert layout.parse_template("{ignore}/{creator}") == ["ignore", "creator"]
        assert layout.parse_template("*/{creator}") == ["ignore", "creator"]

    def test_surrounding_slashes_and_backslashes_tolerated(self):
        assert layout.parse_template("/{tag}/{creator}/") == ["tag", "creator"]
        assert layout.parse_template("{tag}\\{creator}") == ["tag", "creator"]

    def test_requires_exactly_one_creator(self):
        with pytest.raises(layout.LayoutError):
            layout.parse_template("{tag}/{tag}")
        with pytest.raises(layout.LayoutError):
            layout.parse_template("{creator}/{creator}")

    def test_creator_must_be_last(self):
        with pytest.raises(layout.LayoutError):
            layout.parse_template("{creator}/{tag}")

    def test_unknown_token_rejected(self):
        with pytest.raises(layout.LayoutError):
            layout.parse_template("{genre}/{creator}")

    def test_malformed_token_rejected(self):
        with pytest.raises(layout.LayoutError):
            layout.parse_template("tag/{creator}")


class TestRolesFor:
    def test_invalid_falls_back_to_default(self):
        # roles_for never raises — a bad stored template can't abort a scan.
        assert layout.roles_for("{creator}/{tag}") == ["creator"]
        assert layout.roles_for("garbage") == ["creator"]

    def test_valid_passes_through(self):
        assert layout.roles_for("{tag}/{creator}") == ["tag", "creator"]


class TestIterCreatorDirs:
    def test_default_layout_top_level_creators(self, tmp_path):
        (tmp_path / "Abe3D").mkdir()
        (tmp_path / "PolyMind").mkdir()
        roles = layout.parse_template("{creator}")

        entries = layout.iter_creator_dirs(tmp_path, roles)

        names = {d.name: tags for d, tags in entries}
        assert names == {"Abe3D": [], "PolyMind": []}

    def test_tag_above_creator_captures_folder_name(self, tmp_path):
        (tmp_path / "Sci-Fi" / "Abe3D").mkdir(parents=True)
        (tmp_path / "Fantasy" / "Abe3D").mkdir(parents=True)
        (tmp_path / "Fantasy" / "PolyMind").mkdir(parents=True)
        roles = layout.parse_template("{tag}/{creator}")

        entries = layout.iter_creator_dirs(tmp_path, roles)

        got = {(d.parent.name, d.name): tags for d, tags in entries}
        assert got == {
            ("Sci-Fi", "Abe3D"): ["Sci-Fi"],
            ("Fantasy", "Abe3D"): ["Fantasy"],
            ("Fantasy", "PolyMind"): ["Fantasy"],
        }

    def test_ignore_level_is_skipped_not_tagged(self, tmp_path):
        (tmp_path / "_incoming" / "Abe3D").mkdir(parents=True)
        roles = layout.parse_template("{ignore}/{creator}")

        entries = layout.iter_creator_dirs(tmp_path, roles)

        assert len(entries) == 1
        creator_dir, tags = entries[0]
        assert creator_dir.name == "Abe3D"
        assert tags == []

    def test_two_tag_levels(self, tmp_path):
        (tmp_path / "Sci-Fi" / "Mechs" / "Abe3D").mkdir(parents=True)
        roles = layout.parse_template("{tag}/{tag}/{creator}")

        entries = layout.iter_creator_dirs(tmp_path, roles)

        creator_dir, tags = entries[0]
        assert creator_dir.name == "Abe3D"
        assert tags == ["Sci-Fi", "Mechs"]


class TestTagsForPath:
    def test_extracts_tags_from_below_creator_path(self):
        root = Path("/lib")
        roles = layout.parse_template("{tag}/{creator}")
        model_path = root / "Sci-Fi" / "Abe3D" / "Mecha" / "Bust"

        assert layout.tags_for_path(model_path, root, roles) == ["Sci-Fi"]

    def test_no_tags_for_default_layout(self):
        root = Path("/lib")
        roles = layout.parse_template("{creator}")
        assert layout.tags_for_path(root / "Abe3D" / "X", root, roles) == []

    def test_path_outside_root_returns_empty(self):
        root = Path("/lib")
        roles = layout.parse_template("{tag}/{creator}")
        assert layout.tags_for_path(Path("/other/x"), root, roles) == []


class TestCreatorDepth:
    def test_depth(self):
        assert layout.creator_depth(["creator"]) == 0
        assert layout.creator_depth(["tag", "creator"]) == 1
        assert layout.creator_depth(["ignore", "tag", "creator"]) == 2

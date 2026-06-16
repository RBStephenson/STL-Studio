"""Unit tests for configurable scan rules (#31) — Phase 1 ignore patterns.

Covers the IgnoreMatcher glob semantics, default+user merge, the lenient
normalisation of a stored value, and the AppSettingsUpdate validator.
"""
from pathlib import Path

import pytest

from app.models import AppSetting
from app.schemas import AppSettingsUpdate
from app.services import scan_rules
from app.services.scan_rules import IgnoreMatcher, load_ignore_matcher


class TestIgnoreMatcher:
    def test_empty_matcher_matches_nothing(self):
        m = IgnoreMatcher(())
        assert m.matches(Path("/lib/Creator/Model")) is False

    def test_matches_by_basename(self):
        m = IgnoreMatcher(("supports",))
        assert m.matches(Path("/lib/Creator/Model/Supports")) is True
        assert m.matches(Path("/lib/Creator/Model")) is False

    def test_matches_are_case_insensitive(self):
        m = IgnoreMatcher(("supports",))
        assert m.matches(Path("/lib/Creator/SUPPORTS")) is True

    def test_glob_on_basename(self):
        m = IgnoreMatcher(("_archive*",))
        assert m.matches(Path("/lib/_archive_2024")) is True
        assert m.matches(Path("/lib/archive")) is False

    def test_matches_full_path_glob(self):
        m = IgnoreMatcher(("*/wip/*",))
        assert m.matches(Path("/lib/Creator/wip/Model")) is True
        # bare basename pattern would not have caught a nested location
        assert m.matches(Path("/lib/Creator/Model")) is False


class TestLoadIgnoreMatcher:
    def test_no_row_yields_empty(self, db):
        assert load_ignore_matcher(db).patterns == ()

    def test_loads_and_normalises_user_patterns(self, db):
        db.add(AppSetting(key=scan_rules.IGNORE_PATTERNS_KEY,
                          value=["  WIP ", "wip", "", "Supports"]))
        db.commit()
        # stripped, lower-cased, de-duped, blanks dropped — order preserved
        assert load_ignore_matcher(db).patterns == ("wip", "supports")

    def test_non_list_stored_value_is_treated_as_empty(self, db):
        db.add(AppSetting(key=scan_rules.IGNORE_PATTERNS_KEY, value="oops-not-a-list"))
        db.commit()
        assert load_ignore_matcher(db).patterns == ()

    def test_merges_built_in_defaults(self, db, monkeypatch):
        monkeypatch.setattr(scan_rules, "_DEFAULT_IGNORE_PATTERNS", ("thumbs.db",))
        db.add(AppSetting(key=scan_rules.IGNORE_PATTERNS_KEY, value=["wip"]))
        db.commit()
        assert load_ignore_matcher(db).patterns == ("thumbs.db", "wip")


class TestUpdateValidator:
    def test_strips_blanks_and_dedupes(self):
        body = AppSettingsUpdate(scan_ignore_patterns=[" wip ", "wip", "", "supports"])
        assert body.scan_ignore_patterns == ["wip", "supports"]

    def test_none_left_unchanged(self):
        assert AppSettingsUpdate().scan_ignore_patterns is None

    def test_rejects_overlong_pattern(self):
        with pytest.raises(ValueError):
            AppSettingsUpdate(scan_ignore_patterns=["x" * 201])

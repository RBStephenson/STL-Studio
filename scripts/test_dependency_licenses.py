import pytest

from check_dependency_licenses import _node_entries, _pip_entries, validate_inventory


def test_validate_inventory_accepts_allowed_and_ignored_packages():
    entries = [("safe", "MIT"), ("private-app", "UNLICENSED")]

    assert validate_inventory(entries, {"MIT"}, {"private-app"}) == []


def test_validate_inventory_reports_unknown_and_missing_licenses_sorted():
    entries = [("zeta", ""), ("alpha", "GPL-3.0-only")]

    assert validate_inventory(entries, {"MIT"}, set()) == [
        "alpha: GPL-3.0-only",
        "zeta: <missing>",
    ]


def test_pip_entries_require_expected_fields():
    with pytest.raises(ValueError, match="Name and License"):
        _pip_entries([{"Name": "example"}])


def test_node_entries_normalize_versioned_package_names_and_license_lists():
    payload = {"@scope/example@1.2.3": {"licenses": ["MIT", "Apache-2.0"]}}

    assert _node_entries(payload) == [("@scope/example", "MIT OR Apache-2.0")]


def test_node_entries_reject_missing_license_metadata():
    with pytest.raises(ValueError, match="no string license metadata"):
        _node_entries({"example@1.0.0": {}})

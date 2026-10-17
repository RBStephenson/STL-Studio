import json
import sys

import pytest

from check_npm_audit import _advisory_urls, main, validate_report


def _run_main(tmp_path, monkeypatch, allowlist, report):
    allowlist_path = tmp_path / "allowlist.json"
    report_path = tmp_path / "report.json"
    allowlist_path.write_text(json.dumps(allowlist), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_npm_audit.py", "--allowlist", str(allowlist_path), "--report", str(report_path)],
    )
    return main()


def test_validate_report_allows_a_listed_advisory():
    urls = ["https://github.com/advisories/GHSA-aaaa-bbbb-cccc"]

    assert validate_report(urls, {"https://github.com/advisories/GHSA-aaaa-bbbb-cccc"}) == []


def test_validate_report_reports_unlisted_advisories_sorted_and_deduped():
    urls = [
        "https://github.com/advisories/GHSA-zzzz",
        "https://github.com/advisories/GHSA-zzzz",
        "https://github.com/advisories/GHSA-aaaa",
    ]

    assert validate_report(urls, set()) == [
        "https://github.com/advisories/GHSA-aaaa",
        "https://github.com/advisories/GHSA-zzzz",
    ]


def test_validate_report_is_clean_when_report_has_no_advisories():
    assert validate_report([], {"https://github.com/advisories/GHSA-unused"}) == []


def test_advisory_urls_extracts_objects_and_skips_dependency_chain_strings():
    report = {
        "vulnerabilities": {
            "react-router": {
                "via": [{"url": "https://github.com/advisories/GHSA-real", "severity": "high"}],
            },
            "react-router-dom": {
                # A plain string here means "vulnerable because it depends on
                # react-router" — not a distinct advisory, must not be treated
                # as one (it isn't a URL and has no allowlist entry to match).
                "via": ["react-router"],
            },
        },
    }

    assert _advisory_urls(report) == ["https://github.com/advisories/GHSA-real"]


def test_advisory_urls_treats_a_missing_vulnerabilities_key_as_no_findings():
    # npm audit omits the key entirely on a fully clean report.
    assert _advisory_urls({}) == []


def test_advisory_urls_rejects_a_non_object_vulnerabilities_value():
    with pytest.raises(ValueError, match="vulnerabilities"):
        _advisory_urls({"vulnerabilities": "not-an-object"})


def test_advisory_urls_ignores_findings_below_high_severity():
    # npm audit --json always lists every finding regardless of severity;
    # --audit-level=high only changes npm's own exit code. This script must
    # apply the same filter itself, or it becomes stricter than the gate
    # it's replacing (a real bug caught by testing against a live desktop/
    # audit report during STUDIO-355: a moderate `tar` finding was wrongly
    # flagged before this filter existed).
    report = {
        "vulnerabilities": {
            "tar": {
                "via": [
                    {
                        "url": "https://github.com/advisories/GHSA-moderate-only",
                        "severity": "moderate",
                    }
                ],
            },
        },
    }

    assert _advisory_urls(report) == []


def test_advisory_urls_rejects_a_non_object_vulnerability_entry():
    with pytest.raises(ValueError, match="must be an object"):
        _advisory_urls({"vulnerabilities": {"react-router": "not-an-object"}})


def test_main_fails_a_high_finding_when_the_allowlist_is_empty(tmp_path, monkeypatch):
    # The shipped allowlist is empty (STUDIO-456), so an empty list must gate
    # every high finding rather than being read as "nothing configured".
    report = {
        "vulnerabilities": {
            "undici": {"via": [{"url": "https://github.com/advisories/GHSA-high", "severity": "high"}]},
        },
    }

    assert _run_main(tmp_path, monkeypatch, {"allowed_advisories": []}, report) == 1


def test_main_passes_a_clean_report_when_the_allowlist_is_empty(tmp_path, monkeypatch):
    assert _run_main(tmp_path, monkeypatch, {"allowed_advisories": []}, {}) == 0

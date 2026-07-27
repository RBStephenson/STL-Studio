import pytest

from check_npm_audit import _advisory_urls, validate_report


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

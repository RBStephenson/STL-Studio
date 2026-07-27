"""Gate `npm audit --json` reports against a reviewed advisory allowlist.

`npm audit --audit-level=high` has no per-advisory ignore mechanism, so a
disclosed advisory with no forward fix (and no relevance to how this app
actually uses the package) blocks CI outright until upstream ships a patch.
This lets a specific, justified advisory be allowlisted while any other
high-severity finding still fails the build (STUDIO-355).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read {path}: {exc}") from exc


# Matches `npm audit --audit-level=high`: the JSON report always lists every
# finding regardless of severity — --audit-level only changes npm's own exit
# code, not what's in the JSON — so this script must apply the same filter
# itself or it ends up stricter than the gate it's replacing.
_GATED_SEVERITIES = {"high", "critical"}


def _advisory_urls(report: Any) -> list[str]:
    """Extract every at-or-above-high-severity advisory URL from an
    `npm audit --json` report.

    Each vulnerability's `via` list mixes advisory objects (the actual
    finding, with a `url` and `severity`) and plain strings (a pointer to
    another vulnerable package in the dependency chain, not a distinct
    advisory) — only the objects carry a URL to check against the allowlist.
    """
    if not isinstance(report, dict):
        raise ValueError("npm audit report must be a JSON object")
    vulnerabilities = report.get("vulnerabilities", {})
    if not isinstance(vulnerabilities, dict):
        raise ValueError("npm audit report is missing a 'vulnerabilities' object")
    urls: list[str] = []
    for name, entry in vulnerabilities.items():
        if not isinstance(entry, dict):
            raise ValueError(f"npm audit vulnerability entry for {name} must be an object")
        for via in entry.get("via", []):
            if (
                isinstance(via, dict)
                and isinstance(via.get("url"), str)
                and via.get("severity") in _GATED_SEVERITIES
            ):
                urls.append(via["url"])
    return urls


def validate_report(report_urls: list[str], allowed_urls: set[str]) -> list[str]:
    """Return advisory URLs present in the report but not the allowlist."""
    return sorted({url for url in report_urls if url not in allowed_urls})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--report", type=Path, action="append", required=True)
    args = parser.parse_args()

    allowlist = _load_json(args.allowlist)
    if not isinstance(allowlist, dict):
        raise ValueError("allowlist must be a JSON object")
    entries = allowlist.get("allowed_advisories", [])
    if not isinstance(entries, list):
        raise ValueError("allowlist requires an 'allowed_advisories' list")
    allowed_urls: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            raise ValueError("each allowlist entry requires a string 'url'")
        allowed_urls.add(entry["url"])

    violations: list[str] = []
    for path in args.report:
        violations.extend(validate_report(_advisory_urls(_load_json(path)), allowed_urls))
    violations = sorted(set(violations))

    if violations:
        print("Unallowlisted npm audit findings (add a reviewed allowlist entry or fix the dependency):")
        for url in violations:
            print(f"- {url}")
        return 1
    print("npm audit findings are fully covered by the allowlist (or there were none).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

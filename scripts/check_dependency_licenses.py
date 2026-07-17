"""Validate pip-licenses and license-checker JSON against the release policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read license inventory {path}: {exc}") from exc


def _pip_entries(payload: Any) -> list[tuple[str, str]]:
    if not isinstance(payload, list):
        raise ValueError("pip inventory must be a JSON list")
    entries: list[tuple[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("pip inventory entries must be objects")
        name = item.get("Name")
        license_name = item.get("License")
        if not isinstance(name, str) or not isinstance(license_name, str):
            raise ValueError("pip inventory entries require string Name and License fields")
        entries.append((name, license_name.strip()))
    return entries


def _node_entries(payload: Any) -> list[tuple[str, str]]:
    if not isinstance(payload, dict):
        raise ValueError("npm inventory must be a JSON object")
    entries: list[tuple[str, str]] = []
    for package, metadata in payload.items():
        if not isinstance(package, str) or not isinstance(metadata, dict):
            raise ValueError("npm inventory entries must map package names to objects")
        license_value = metadata.get("licenses")
        if isinstance(license_value, list):
            license_name = " OR ".join(str(value) for value in license_value)
        elif isinstance(license_value, str):
            license_name = license_value
        else:
            raise ValueError(f"npm package {package} has no string license metadata")
        entries.append((package.rsplit("@", 1)[0], license_name.strip()))
    return entries


def validate_inventory(
    entries: list[tuple[str, str]], allowed: set[str], ignored_packages: set[str]
) -> list[str]:
    """Return policy violations for an already parsed package/license inventory."""
    violations: list[str] = []
    for package, license_name in entries:
        if package in ignored_packages:
            continue
        if license_name not in allowed:
            violations.append(f"{package}: {license_name or '<missing>'}")
    return sorted(violations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--pip", type=Path, action="append", default=[])
    parser.add_argument("--node", type=Path, action="append", default=[])
    args = parser.parse_args()

    policy = _load_json(args.policy)
    if not isinstance(policy, dict):
        raise ValueError("license policy must be a JSON object")
    allowed = set(policy.get("allowed_licenses", []))
    ignored = set(policy.get("ignored_private_packages", []))
    if not allowed or not all(isinstance(value, str) for value in allowed | ignored):
        raise ValueError("license policy requires non-empty string allowlists")

    violations: list[str] = []
    for path in args.pip:
        violations.extend(validate_inventory(_pip_entries(_load_json(path)), allowed, ignored))
    for path in args.node:
        violations.extend(validate_inventory(_node_entries(_load_json(path)), allowed, ignored))

    if violations:
        print("Dependency license policy violations:")
        for violation in sorted(violations):
            print(f"- {violation}")
        return 1
    print("Dependency licenses satisfy the release policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

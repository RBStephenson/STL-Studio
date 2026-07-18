"""Validate and checksum the complete STL Studio release asset set."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


CHECKSUM_NAME = "SHA256SUMS"
SBOM_NAMES = (
    "stl-studio-backend-windows.cdx.json",
    "stl-studio-desktop-windows.cdx.json",
    "stl-studio-backend-linux.cdx.json",
)


def required_names(version: str) -> tuple[str, ...]:
    installer = f"STL-Studio-Setup-{version}.exe"
    return (
        installer,
        f"{installer}.blockmap",
        "latest.yml",
        "stl-studio-linux",
        *SBOM_NAMES,
    )


def validate_sbom(path: Path) -> None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"invalid SBOM JSON: {path.name}") from error
    if document.get("bomFormat") != "CycloneDX":
        raise ValueError(f"SBOM is not CycloneDX: {path.name}")
    components = document.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError(f"SBOM contains no components: {path.name}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(directory: Path, version: str) -> Path:
    names = required_names(version)
    missing = [name for name in names if not (directory / name).is_file()]
    if missing:
        raise ValueError(f"release assets are missing: {missing}")
    destination = directory / CHECKSUM_NAME
    destination.write_text(
        "".join(f"{sha256(directory / name)}  {name}\n" for name in sorted(names)),
        encoding="utf-8",
    )
    return destination


def validate(directory: Path, version: str) -> None:
    names = required_names(version)
    required = (*names, CHECKSUM_NAME)
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        raise ValueError(f"release assets are missing: {missing}")
    unexpected = sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name not in required
    )
    if unexpected:
        raise ValueError(f"release assets contain unexpected files: {unexpected}")

    metadata = (directory / "latest.yml").read_text(encoding="utf-8")
    version_match = re.search(r"(?m)^version:\s*['\"]?([^'\"\s]+)", metadata)
    path_match = re.search(r"(?m)^path:\s*['\"]?([^'\"\r\n]+)", metadata)
    installer = names[0]
    if not version_match or version_match.group(1) != version:
        raise ValueError("latest.yml version does not match the release version")
    if not path_match or path_match.group(1).strip() != installer:
        raise ValueError("latest.yml path does not match the published installer")

    for name in SBOM_NAMES:
        validate_sbom(directory / name)

    entries: dict[str, str] = {}
    for line in (directory / CHECKSUM_NAME).read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(f"invalid checksum line: {line!r}")
        entries[match.group(2)] = match.group(1)
    if set(entries) != set(names):
        raise ValueError(
            "checksum manifest does not contain the exact release asset set"
        )
    mismatched = [name for name in names if entries[name] != sha256(directory / name)]
    if mismatched:
        raise ValueError(f"release asset checksums do not match: {mismatched}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--write-checksums", action="store_true")
    args = parser.parse_args()
    if args.write_checksums:
        write_checksums(args.directory, args.version)
    validate(args.directory, args.version)
    print(f"Validated release assets for v{args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

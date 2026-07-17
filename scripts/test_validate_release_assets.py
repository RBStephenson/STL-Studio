from pathlib import Path

import pytest

from validate_release_assets import required_names, validate, write_checksums


def make_assets(tmp_path: Path, version: str = "1.2.3") -> None:
    installer = required_names(version)[0]
    for name in required_names(version):
        (tmp_path / name).write_bytes(f"contents:{name}".encode())
    (tmp_path / "latest.yml").write_text(
        f"version: {version}\npath: {installer}\nsha512: placeholder\n",
        encoding="utf-8",
    )


def test_write_and_validate_complete_release(tmp_path):
    make_assets(tmp_path)

    manifest = write_checksums(tmp_path, "1.2.3")
    validate(tmp_path, "1.2.3")

    assert len(manifest.read_text(encoding="utf-8").splitlines()) == 4


def test_validate_rejects_metadata_installer_mismatch(tmp_path):
    make_assets(tmp_path)
    write_checksums(tmp_path, "1.2.3")
    (tmp_path / "latest.yml").write_text(
        "version: 1.2.3\npath: wrong.exe\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="published installer"):
        validate(tmp_path, "1.2.3")


def test_validate_rejects_tampered_asset(tmp_path):
    make_assets(tmp_path)
    write_checksums(tmp_path, "1.2.3")
    (tmp_path / "stl-studio-linux").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="checksums do not match"):
        validate(tmp_path, "1.2.3")


def test_write_checksums_rejects_missing_asset(tmp_path):
    make_assets(tmp_path)
    (tmp_path / "stl-studio-linux").unlink()

    with pytest.raises(ValueError, match="release assets are missing"):
        write_checksums(tmp_path, "1.2.3")


def test_validate_rejects_unexpected_asset(tmp_path):
    make_assets(tmp_path)
    write_checksums(tmp_path, "1.2.3")
    (tmp_path / "stale-installer.exe").write_bytes(b"stale")

    with pytest.raises(ValueError, match="unexpected files"):
        validate(tmp_path, "1.2.3")

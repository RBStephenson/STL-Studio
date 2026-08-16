"""STL Installer: extract a ZIP or copy a folder into scan_root/creator/character
(STUDIO-386).

Builds on safe_copy.copy_verified (folder-copy) and path_guard.assert_within_roots
(destination containment) -- see those modules' own test files for coverage of
the primitives themselves. These tests cover installer.py's own logic: zip-slip
rejection, the flatten decision, collision handling, and the size cap.

The flatten-decision fixtures deliberately mirror two real, structurally
different creator archives inspected during planning (Abe3D: one wrapping
folder plus its own directory entry; 3DMOONN "Percy": two distinct top-level
folders, "standard version/" and "bonus parts/") rather than a single assumed
shape, per this project's own recurring lesson about not trusting one sample.
"""
from __future__ import annotations

import zipfile

import pytest

from app.services import installer


def _make_zip(path, entries: dict[str, bytes], dirs: list[str] | None = None) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for dirname in dirs or []:
            zf.writestr(dirname if dirname.endswith("/") else dirname + "/", "")
        for name, data in entries.items():
            zf.writestr(name, data)


# ---------------------------------------------------------------------------
# Folder-copy path
# ---------------------------------------------------------------------------

def test_install_from_folder_copies_files(tmp_path):
    source = tmp_path / "src"
    (source / "sub").mkdir(parents=True)
    (source / "head.stl").write_bytes(b"head")
    (source / "sub" / "arm.stl").write_bytes(b"arm")
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    result = installer.install(source, scan_root, "Abe3D", "Zarana")

    dest = scan_root / "Abe3D" / "Zarana"
    assert (dest / "head.stl").read_bytes() == b"head"
    assert (dest / "sub" / "arm.stl").read_bytes() == b"arm"
    assert result.dest == dest
    assert result.file_count == 2
    assert result.total_bytes == 7


def test_install_from_folder_leaves_source_untouched(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "head.stl").write_bytes(b"head")
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    installer.install(source, scan_root, "Abe3D", "Zarana")

    assert (source / "head.stl").read_bytes() == b"head"  # copy_verified never touches src


def test_install_from_folder_uses_verified_copy(tmp_path, monkeypatch):
    """Confirms the folder path actually routes through the shared cross-device
    copy primitive (STUDIO-385), not a bare shutil.copy."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "head.stl").write_bytes(b"head")
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    real_copy_verified = installer.copy_verified
    calls = []

    def spy(src, dst):
        calls.append((src, dst))
        real_copy_verified(src, dst)

    monkeypatch.setattr(installer, "copy_verified", spy)

    installer.install(source, scan_root, "Abe3D", "Zarana")

    assert len(calls) == 1


def test_install_from_empty_folder_raises(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    with pytest.raises(installer.EmptySourceError):
        installer.install(source, scan_root, "Abe3D", "Zarana")


# ---------------------------------------------------------------------------
# Destination containment / collision
# ---------------------------------------------------------------------------

def test_creator_character_path_traversal_raises_valueerror(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "head.stl").write_bytes(b"head")
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    with pytest.raises(ValueError):
        installer.install(source, scan_root, "../../etc", "passwd")


def test_blank_creator_raises_valueerror(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    with pytest.raises(ValueError):
        installer.install(source, scan_root, "  ", "Zarana")


def test_existing_character_dir_is_a_hard_collision(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "head.stl").write_bytes(b"head")
    scan_root = tmp_path / "library"
    (scan_root / "Abe3D" / "Zarana").mkdir(parents=True)

    with pytest.raises(installer.DestinationExistsError):
        installer.install(source, scan_root, "Abe3D", "Zarana")


def test_empty_existing_character_dir_still_collides(tmp_path):
    """An empty dest folder -- e.g. left behind by a crashed prior attempt --
    blocks a retry just as hard as a full one. No silent resume/cleanup."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "head.stl").write_bytes(b"head")
    scan_root = tmp_path / "library"
    (scan_root / "Abe3D" / "Zarana").mkdir(parents=True)  # empty, but present

    with pytest.raises(installer.DestinationExistsError):
        installer.install(source, scan_root, "Abe3D", "Zarana")


def test_existing_creator_dir_is_not_a_collision(tmp_path):
    """The creator folder is expected to already exist for the common
    existing-creator case -- only the character leaf is collision-checked."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "head.stl").write_bytes(b"head")
    scan_root = tmp_path / "library"
    (scan_root / "Abe3D" / "OtherCharacter").mkdir(parents=True)

    result = installer.install(source, scan_root, "Abe3D", "Zarana")

    assert result.dest == scan_root / "Abe3D" / "Zarana"


def test_unsupported_source_extension_raises(tmp_path):
    source = tmp_path / "pack.rar"
    source.write_bytes(b"not really a rar")
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    with pytest.raises(installer.UnsupportedSourceError, match="STUDIO-103"):
        installer.install(source, scan_root, "Abe3D", "Zarana")


# ---------------------------------------------------------------------------
# ZIP path: flatten decision
# ---------------------------------------------------------------------------

def test_zip_flattens_single_wrapping_folder(tmp_path):
    """Mirrors the real Abe3D structure: every file nested under one shared
    top-level folder, plus a directory entry for that folder itself."""
    zip_path = tmp_path / "pack.zip"
    _make_zip(
        zip_path,
        entries={
            "1_4 Zarana - Abe3D by Ramses/Head.stl": b"head",
            "1_4 Zarana - Abe3D by Ramses/ArmL.stl": b"arm",
        },
        dirs=["1_4 Zarana - Abe3D by Ramses"],
    )
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    result = installer.install(zip_path, scan_root, "Abe3D", "Zarana")

    dest = scan_root / "Abe3D" / "Zarana"
    assert (dest / "Head.stl").read_bytes() == b"head"
    assert (dest / "ArmL.stl").read_bytes() == b"arm"
    assert not (dest / "1_4 Zarana - Abe3D by Ramses").exists()
    assert result.file_count == 2


def test_zip_does_not_flatten_multiple_top_level_folders(tmp_path):
    """Mirrors the real 3DMOONN "Percy" structure: two distinct top-level
    folders ("standard version/", "bonus parts/") -- flattening either would
    silently merge or misplace files from the other."""
    zip_path = tmp_path / "pack.zip"
    _make_zip(
        zip_path,
        entries={
            "standard version/head.stl": b"head",
            "bonus parts/mask.stl": b"mask",
        },
    )
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    result = installer.install(zip_path, scan_root, "3DMOONN", "Percy")

    dest = scan_root / "3DMOONN" / "Percy"
    assert (dest / "standard version" / "head.stl").read_bytes() == b"head"
    assert (dest / "bonus parts" / "mask.stl").read_bytes() == b"mask"
    assert result.file_count == 2


def test_zip_does_not_flatten_single_bare_top_level_file(tmp_path):
    """A single-file zip with no wrapping folder has exactly one top-level
    component -- but it's the file itself, not a directory, so flattening it
    would strip the filename down to nothing. Regression for a bug caught in
    review before this shipped."""
    zip_path = tmp_path / "pack.zip"
    _make_zip(zip_path, entries={"model.stl": b"solo"})
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    result = installer.install(zip_path, scan_root, "SoloCreator", "Solo")

    dest = scan_root / "SoloCreator" / "Solo"
    assert (dest / "model.stl").read_bytes() == b"solo"
    assert result.file_count == 1


def test_zip_ignores_macosx_metadata_for_flatten_decision(tmp_path):
    """A Mac-authored zip's __MACOSX/ sibling must not look like a second
    top-level folder and disable flatten on an otherwise-single-folder pack."""
    zip_path = tmp_path / "pack.zip"
    _make_zip(
        zip_path,
        entries={
            "Zarana/Head.stl": b"head",
            "__MACOSX/._Head.stl": b"resource-fork-junk",
        },
    )
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    result = installer.install(zip_path, scan_root, "Abe3D", "Zarana")

    dest = scan_root / "Abe3D" / "Zarana"
    assert (dest / "Head.stl").read_bytes() == b"head"
    assert result.file_count == 2  # __MACOSX entry still extracted, just ignored for flatten


# ---------------------------------------------------------------------------
# ZIP path: zip-slip
# ---------------------------------------------------------------------------

def test_zip_slip_entry_raises(tmp_path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../evil.stl", b"escaped")
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    with pytest.raises(installer.InvalidArchiveError):
        installer.install(zip_path, scan_root, "Abe3D", "Zarana")

    assert not (tmp_path / "evil.stl").exists()


def test_zip_slip_entry_aborts_before_any_writes(tmp_path):
    """Validation runs for every entry before any file is written, so a slip
    entry anywhere in the archive blocks the whole install -- never a partial
    extraction of the legitimate entries alongside a rejected one."""
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Zarana/Head.stl", b"legit")
        zf.writestr("../evil.stl", b"escaped")
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    with pytest.raises(installer.InvalidArchiveError):
        installer.install(zip_path, scan_root, "Abe3D", "Zarana")

    assert not (scan_root / "Abe3D" / "Zarana").exists()


# ---------------------------------------------------------------------------
# Size cap
# ---------------------------------------------------------------------------

def test_folder_declared_size_over_cap_raises_before_any_copy(tmp_path, monkeypatch):
    source = tmp_path / "src"
    source.mkdir()
    (source / "head.stl").write_bytes(b"x" * 100)
    scan_root = tmp_path / "library"
    scan_root.mkdir()
    monkeypatch.setattr(installer, "MAX_INSTALL_SIZE_BYTES", 10)

    with pytest.raises(installer.InstallSizeExceededError):
        installer.install(source, scan_root, "Abe3D", "Zarana")

    assert not (scan_root / "Abe3D" / "Zarana").exists()


def test_zip_declared_size_over_cap_raises_before_any_write(tmp_path, monkeypatch):
    zip_path = tmp_path / "pack.zip"
    _make_zip(zip_path, entries={"Zarana/Head.stl": b"x" * 100})
    scan_root = tmp_path / "library"
    scan_root.mkdir()
    monkeypatch.setattr(installer, "MAX_INSTALL_SIZE_BYTES", 10)

    with pytest.raises(installer.InstallSizeExceededError):
        installer.install(zip_path, scan_root, "Abe3D", "Zarana")

    assert not (scan_root / "Abe3D" / "Zarana").exists()


def test_zip_extraction_spans_multiple_chunks(tmp_path, monkeypatch):
    """Every other zip fixture in this file is well under the real 1 MiB
    _CHUNK_SIZE, so the streaming read loop only ever runs once. Shrink the
    chunk size so a ~100-byte entry is genuinely written across several
    iterations, and confirm the reassembled content is still byte-exact."""
    payload = bytes(range(256)) * 2  # 512 bytes, easy to spot corruption in
    zip_path = tmp_path / "pack.zip"
    _make_zip(zip_path, entries={"Zarana/Head.stl": payload})
    scan_root = tmp_path / "library"
    scan_root.mkdir()
    monkeypatch.setattr(installer, "_CHUNK_SIZE", 10)

    installer.install(zip_path, scan_root, "Abe3D", "Zarana")

    assert (scan_root / "Abe3D" / "Zarana" / "Head.stl").read_bytes() == payload


# ---------------------------------------------------------------------------
# Invalid / empty archives
# ---------------------------------------------------------------------------

def test_not_a_zip_file_raises_invalid_archive(tmp_path):
    zip_path = tmp_path / "pack.zip"
    zip_path.write_bytes(b"not actually a zip")
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    with pytest.raises(installer.InvalidArchiveError):
        installer.install(zip_path, scan_root, "Abe3D", "Zarana")


def test_empty_zip_raises_empty_source(tmp_path):
    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w"):
        pass
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    with pytest.raises(installer.EmptySourceError):
        installer.install(zip_path, scan_root, "Abe3D", "Zarana")

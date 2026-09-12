"""
Tests for the host-capability probes in `tests.conftest`.

These matter more than their size suggests. `host_fs_is_case_sensitive` decides
whether a real test runs or is skipped, so a probe stuck on one answer fails
silently in both directions: stuck True puts back the false Windows failure it
was written to remove, and stuck False turns CI's genuine coverage into a green
skip nobody looks at (STUDIO-451).
"""
from pathlib import Path

from tests.conftest import host_fs_is_case_sensitive


def _write(path: Path) -> None:
    path.write_bytes(b"solid x\nendsolid x\n")


def test_probe_agrees_with_how_the_same_filesystem_treats_files(tmp_path):
    """Cross-check the probe against a different mechanism on the same tree.

    The probe answers with directories; this asks the same question with FILES.
    Two mechanisms measuring one filesystem must agree — and that is an
    assertion a hardwired constant cannot satisfy on both kinds of host, which
    is exactly the failure this file exists to catch.
    """
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    probed = host_fs_is_case_sensitive(probe_dir)

    files_dir = tmp_path / "files"
    files_dir.mkdir()
    _write(files_dir / "Auron.stl")
    _write(files_dir / "auron.stl")
    files_stayed_distinct = len(list(files_dir.iterdir())) == 2

    assert probed is files_stayed_distinct, (
        "the probe's directory answer contradicts the same filesystem's file behaviour"
    )


def test_probe_is_repeatable_in_the_same_directory(tmp_path):
    """Calling it twice must not raise on the leftover probe directories, and
    must not change its answer — the session fixture reuses one temp tree."""
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()

    first = host_fs_is_case_sensitive(probe_dir)
    second = host_fs_is_case_sensitive(probe_dir)

    assert first is second, "the probe is not idempotent within one directory"


def test_probe_ignores_unrelated_entries_already_in_the_directory(tmp_path):
    """It must count its own two names, not everything present.

    A probe that compared `len(iterdir())` to 2 would read a directory holding
    one unrelated file as case-sensitive on any host.
    """
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    expected = host_fs_is_case_sensitive(clean_dir)

    busy_dir = tmp_path / "busy"
    busy_dir.mkdir()
    _write(busy_dir / "unrelated.stl")
    (busy_dir / "unrelated_folder").mkdir()

    assert host_fs_is_case_sensitive(busy_dir) is expected, (
        "pre-existing directory entries changed the probe's answer"
    )

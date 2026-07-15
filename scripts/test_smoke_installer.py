import json

import pytest

import smoke_installer


def test_find_one_requires_exactly_one_match(tmp_path):
    expected = tmp_path / "STL Studio.exe"
    expected.touch()
    assert smoke_installer.find_one(tmp_path, "STL Studio.exe") == expected
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "STL Studio.exe").touch()
    with pytest.raises(RuntimeError, match="expected one"):
        smoke_installer.find_one(tmp_path, "STL Studio.exe")


def test_wait_for_lock_reads_complete_record(tmp_path):
    profile = tmp_path / "stl-studio-desktop"
    profile.mkdir()
    lock = profile / "sidecar.lock.json"
    lock.write_text(json.dumps({"pid": 12, "port": 3456}), encoding="utf-8")
    assert smoke_installer.wait_for_lock(tmp_path, timeout_s=0.1) == {"pid": 12, "port": 3456}


def test_wait_for_lock_rejects_incomplete_record(tmp_path):
    lock = tmp_path / "sidecar.lock.json"
    lock.write_text(json.dumps({"pid": "12"}), encoding="utf-8")
    with pytest.raises(TimeoutError):
        smoke_installer.wait_for_lock(tmp_path, timeout_s=0)


def test_wait_for_lock_rejects_multiple_valid_records(tmp_path):
    for name in ("one", "two"):
        profile = tmp_path / name
        profile.mkdir()
        (profile / "sidecar.lock.json").write_text(
            json.dumps({"pid": 12, "port": 3456}), encoding="utf-8"
        )
    with pytest.raises(RuntimeError, match="multiple sidecar locks"):
        smoke_installer.wait_for_lock(tmp_path, timeout_s=0.1)


def test_wait_for_lock_reports_early_process_exit(tmp_path):
    class ExitedProcess:
        @staticmethod
        def poll():
            return 7

    with pytest.raises(RuntimeError, match="exited before startup with code 7"):
        smoke_installer.wait_for_lock(tmp_path, proc=ExitedProcess(), timeout_s=0.1)

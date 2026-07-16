import json
from pathlib import Path
import urllib.request

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


def test_write_diagnostics_captures_logs_locks_and_relevant_processes(tmp_path, monkeypatch):
    app_log = tmp_path / "electron.log"
    app_log.write_text("[startup] main-loaded\n", encoding="utf-8")
    profile = tmp_path / "appdata" / "stl-studio-desktop"
    profile.mkdir(parents=True)
    (profile / "sidecar.lock.json").write_text("{}", encoding="utf-8")

    class Result:
        stdout = '"STL Studio.exe","42"\n"unrelated.exe","43"\n'

    monkeypatch.setattr(smoke_installer.subprocess, "run", lambda *args, **kwargs: Result())
    destination = tmp_path / "diagnostics"
    smoke_installer.write_diagnostics(destination, app_log, [tmp_path / "appdata"])

    report = json.loads((destination / "report.json").read_text(encoding="utf-8"))
    assert report["sidecar_locks"] == [str(profile / "sidecar.lock.json")]
    assert report["relevant_processes"] == ['"STL Studio.exe","42"']
    assert (destination / "electron.log").read_text(encoding="utf-8") == "[startup] main-loaded\n"


def test_wait_for_absent_returns_when_path_is_missing(tmp_path):
    smoke_installer.wait_for_absent(tmp_path / "removed.exe", timeout_s=0)


def test_wait_for_absent_times_out_when_path_remains(tmp_path):
    path = tmp_path / "remaining.exe"
    path.touch()
    with pytest.raises(TimeoutError, match="path was not removed"):
        smoke_installer.wait_for_absent(path, timeout_s=0)


def test_update_feed_serves_candidate_metadata(tmp_path):
    (tmp_path / "latest.yml").write_text("version: 1.2.3\n", encoding="utf-8")
    with smoke_installer.serve_update_feed(tmp_path) as feed_url:
        with urllib.request.urlopen(f"{feed_url}latest.yml") as response:
            assert response.read() == b"version: 1.2.3\n"


def test_validate_candidate_feed_checks_version_and_assets(tmp_path):
    installer = tmp_path / "STL-Studio-Setup-1.2.3.exe"
    installer.touch()
    Path(f"{installer}.blockmap").touch()
    (tmp_path / "latest.yml").write_text("version: 1.2.3\n", encoding="utf-8")
    smoke_installer.validate_candidate_feed(tmp_path, "1.2.3")

    with pytest.raises(RuntimeError, match="does not match"):
        smoke_installer.validate_candidate_feed(tmp_path, "1.2.4")


def test_wait_for_updated_version_accepts_new_sidecar_version(tmp_path, monkeypatch):
    lock = tmp_path / "sidecar.lock.json"
    lock.write_text(json.dumps({"pid": 20, "port": 2000}), encoding="utf-8")
    monkeypatch.setattr(
        smoke_installer, "read_system_info", lambda _port: {"version": "1.2.3"}
    )
    assert smoke_installer.wait_for_updated_version(tmp_path, 10, "1.2.3", 1) == {
        "pid": 20,
        "port": 2000,
    }


def test_wait_for_updated_version_reports_wrong_version(tmp_path, monkeypatch):
    (tmp_path / "sidecar.lock.json").write_text(
        json.dumps({"pid": 20, "port": 2000}), encoding="utf-8"
    )
    monkeypatch.setattr(
        smoke_installer, "read_system_info", lambda _port: {"version": "1.2.2"}
    )
    with pytest.raises(TimeoutError, match="reported version '1.2.2'"):
        smoke_installer.wait_for_updated_version(tmp_path, 10, "1.2.3", 0.01)

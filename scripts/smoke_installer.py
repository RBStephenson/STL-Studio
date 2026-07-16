"""Install, launch, restart, and uninstall the Windows NSIS package in CI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


TIMEOUT_S = 60


def write_diagnostics(
    destination: Path,
    app_log: Path,
    search_roots: list[Path],
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if app_log.is_file():
        shutil.copy2(app_log, destination / "electron.log")

    lock_paths: list[str] = []
    for root in search_roots:
        if not root.is_dir():
            continue
        for profile_name in ("STL Studio", "stl-studio-desktop"):
            lock = root / profile_name / "sidecar.lock.json"
            if lock.is_file():
                lock_paths.append(str(lock))

    processes = subprocess.run(
        ["tasklist", "/FO", "CSV"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    relevant_processes = [
        line
        for line in processes.splitlines()
        if "STL Studio.exe" in line or "stl-studio.exe" in line
    ]
    report = {
        "sidecar_locks": lock_paths,
        "relevant_processes": relevant_processes,
    }
    (destination / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )


def wait_for_lock(
    appdata: Path,
    proc: subprocess.Popen | None = None,
    timeout_s: float = TIMEOUT_S,
) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc is not None and (exit_code := proc.poll()) is not None:
            raise RuntimeError(f"installed app exited before startup with code {exit_code}")

        valid_records = []
        for lock_path in appdata.rglob("sidecar.lock.json"):
            try:
                record = json.loads(lock_path.read_text(encoding="utf-8"))
                if isinstance(record.get("pid"), int) and isinstance(record.get("port"), int):
                    valid_records.append(record)
            except (OSError, ValueError, TypeError):
                continue
        if len(valid_records) == 1:
            return valid_records[0]
        if len(valid_records) > 1:
            raise RuntimeError(f"multiple sidecar locks appeared under {appdata}")
        time.sleep(0.25)
    raise TimeoutError(f"sidecar lock did not appear under {appdata}")


def wait_for_health(port: int, timeout_s: float = TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 300:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.25)
    raise TimeoutError(f"installed app did not serve {url}")


def wait_for_absent(path: Path, timeout_s: float = TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not path.exists():
            return
        time.sleep(0.25)
    if path.exists():
        raise TimeoutError(f"path was not removed after {timeout_s}s: {path}")


def find_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.rglob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern!r} under {root}, found {matches}")
    return matches[0]


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], check=False, capture_output=True)


def launch_and_probe(
    exe: Path,
    env: dict[str, str],
    appdata: Path,
    app_log,
) -> tuple[subprocess.Popen, dict]:
    for lock_path in appdata.rglob("sidecar.lock.json"):
        lock_path.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [str(exe)],
        env=env,
        stdout=app_log,
        stderr=subprocess.STDOUT,
    )
    try:
        lock = wait_for_lock(appdata, proc=proc)
        wait_for_health(lock["port"])
        return proc, lock
    except Exception:
        kill_tree(proc.pid)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    parser.add_argument("--diagnostics-dir", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("the installed-app smoke test requires Windows")

    installer = args.installer.resolve()
    if not installer.is_file():
        parser.error(f"installer not found: {installer}")

    root = Path(tempfile.mkdtemp(prefix="stl-studio-installed-smoke-"))
    install_dir = root / "install"
    appdata = root / "appdata"
    localappdata = root / "localappdata"
    appdata.mkdir(parents=True)
    localappdata.mkdir(parents=True)
    host_appdata = Path(os.environ.get("APPDATA", ""))
    host_localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
    app_log = root / "electron.log"
    env = os.environ.copy()
    env.update(
        {
            "APPDATA": str(appdata),
            "LOCALAPPDATA": str(localappdata),
            "STL_STUDIO_USER_DATA_DIR": str(appdata),
        }
    )
    db_path = localappdata / "STL-Inventory" / "stl_inventory.db"
    proc: subprocess.Popen | None = None
    try:
        subprocess.run([str(installer), "/S", f"/D={install_dir}"], check=True, env=env, timeout=120)
        app_exe = find_one(install_dir, "STL Studio.exe")
        with app_log.open("ab") as log:
            proc, _ = launch_and_probe(app_exe, env, appdata, log)
        if not db_path.is_file():
            raise RuntimeError(f"installed app did not create database: {db_path}")
        kill_tree(proc.pid)
        proc.wait(timeout=15)
        proc = None

        with sqlite3.connect(db_path) as db:
            db.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                ("ci_installer_smoke", json.dumps("preserved")),
            )
            db.commit()

        with app_log.open("ab") as log:
            proc, _ = launch_and_probe(app_exe, env, appdata, log)
        with sqlite3.connect(db_path) as db:
            marker = db.execute(
                "SELECT value FROM app_settings WHERE key = ?", ("ci_installer_smoke",)
            ).fetchone()
        if marker != (json.dumps("preserved"),):
            raise RuntimeError(f"database marker did not survive relaunch: {marker}")
        kill_tree(proc.pid)
        proc.wait(timeout=15)
        proc = None

        uninstaller = find_one(install_dir, "Uninstall*.exe")
        subprocess.run([str(uninstaller), "/S"], check=True, env=env, timeout=120)
        wait_for_absent(app_exe)
        if not db_path.is_file():
            raise RuntimeError("uninstall removed user database")
        print("smoke_installer: OK - install, launch, restart, persistence, and uninstall")
        return 0
    except Exception:
        if args.diagnostics_dir:
            write_diagnostics(
                args.diagnostics_dir.resolve(),
                app_log,
                [appdata, localappdata, host_appdata, host_localappdata],
            )
        raise
    finally:
        if proc is not None and proc.poll() is None:
            kill_tree(proc.pid)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

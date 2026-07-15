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


def wait_for_lock(lock_path: Path, timeout_s: float = TIMEOUT_S) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            record = json.loads(lock_path.read_text(encoding="utf-8"))
            if isinstance(record.get("pid"), int) and isinstance(record.get("port"), int):
                return record
        except (OSError, ValueError, TypeError):
            pass
        time.sleep(0.25)
    raise TimeoutError(f"sidecar lock did not appear: {lock_path}")


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


def find_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.rglob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern!r} under {root}, found {matches}")
    return matches[0]


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], check=False, capture_output=True)


def launch_and_probe(exe: Path, env: dict[str, str], lock_path: Path) -> tuple[subprocess.Popen, dict]:
    lock_path.unlink(missing_ok=True)
    proc = subprocess.Popen([str(exe)], env=env)
    try:
        lock = wait_for_lock(lock_path)
        wait_for_health(lock["port"])
        return proc, lock
    except Exception:
        kill_tree(proc.pid)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
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
    env = os.environ.copy()
    env.update({"APPDATA": str(appdata), "LOCALAPPDATA": str(localappdata)})
    lock_path = appdata / "STL Studio" / "sidecar.lock.json"
    db_path = localappdata / "STL-Inventory" / "stl_inventory.db"
    proc: subprocess.Popen | None = None
    try:
        subprocess.run([str(installer), "/S", f"/D={install_dir}"], check=True, env=env, timeout=120)
        app_exe = find_one(install_dir, "STL Studio.exe")
        proc, _ = launch_and_probe(app_exe, env, lock_path)
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

        proc, _ = launch_and_probe(app_exe, env, lock_path)
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
        if app_exe.exists():
            raise RuntimeError(f"uninstall left application executable behind: {app_exe}")
        if not db_path.is_file():
            raise RuntimeError("uninstall removed user database")
        print("smoke_installer: OK - install, launch, restart, persistence, and uninstall")
        return 0
    finally:
        if proc is not None and proc.poll() is None:
            kill_tree(proc.pid)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

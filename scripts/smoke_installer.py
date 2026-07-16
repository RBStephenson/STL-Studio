"""Install, launch, restart, and uninstall the Windows NSIS package in CI."""

from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


TIMEOUT_S = 60
UPDATE_DIALOG_BUTTONS = {
    "STL Studio update available": "Download",
    "STL Studio update ready": "Restart and Install",
}
NSIS_BUTTON_PRIORITY = ("Install", "Next >", "Finish", "Close")
UPDATE_PROFILE_PATHS = (
    ("APPDATA", "stl-studio-desktop"),
    ("APPDATA", "STL Studio"),
    ("LOCALAPPDATA", "STL-Inventory"),
    ("LOCALAPPDATA", "stl-studio-desktop"),
)
SHORTCUT_NAME = "STL Studio.lnk"


def installer_shortcuts(environ: dict[str, str]) -> tuple[Path, Path]:
    """Return the current-user shortcuts created by the NSIS package."""
    missing = [name for name in ("APPDATA", "USERPROFILE") if not environ.get(name)]
    if missing:
        raise RuntimeError(f"installer shortcut checks require environment paths: {missing}")
    return (
        Path(environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / SHORTCUT_NAME,
        Path(environ["USERPROFILE"]) / "Desktop" / SHORTCUT_NAME,
    )


def require_paths(paths: tuple[Path, ...], *, present: bool, phase: str) -> None:
    mismatches = [path for path in paths if path.exists() is not present]
    if mismatches:
        expectation = "created" if present else "removed"
        raise RuntimeError(f"{phase} expected paths to be {expectation}: {mismatches}")


def prepare_data_paths(
    root: Path,
    update_rehearsal: bool,
    environ: dict[str, str],
) -> tuple[Path, Path, dict[str, str]]:
    env = environ.copy()
    if update_rehearsal:
        missing = [name for name in ("APPDATA", "LOCALAPPDATA") if not env.get(name)]
        if missing:
            raise RuntimeError(f"update rehearsal requires environment paths: {missing}")
        dirty = [
            Path(env[variable]) / relative
            for variable, relative in UPDATE_PROFILE_PATHS
            if (Path(env[variable]) / relative).exists()
        ]
        if dirty:
            raise RuntimeError(f"update rehearsal runner profile is not clean: {dirty}")
        return Path(env["APPDATA"]), Path(env["LOCALAPPDATA"]), env

    appdata = root / "appdata"
    localappdata = root / "localappdata"
    appdata.mkdir(parents=True)
    localappdata.mkdir(parents=True)
    env.update(
        {
            "APPDATA": str(appdata),
            "LOCALAPPDATA": str(localappdata),
            "STL_STUDIO_USER_DATA_DIR": str(appdata),
        }
    )
    return appdata, localappdata, env


def find_process_ids(image_name: str) -> set[int]:
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    return {
        int(row[1])
        for row in csv.reader(result.stdout.splitlines())
        if len(row) >= 2 and row[0].casefold() == image_name.casefold()
    }


def write_update_feed_config(app_exe: Path, feed_url: str) -> Path:
    """Point an installed electron-updater client at the disposable CI feed."""
    config = app_exe.parent / "resources" / "app-update.yml"
    if not config.is_file():
        raise RuntimeError(f"installed updater configuration not found: {config}")
    config.write_text(f"provider: generic\nurl: {feed_url}\n", encoding="utf-8")
    return config


def automate_update_dialogs(
    stop_event: threading.Event,
    clicked: list[str],
    timeout_s: float,
    installer_image_name: str | None = None,
    observed: list[str] | None = None,
    user32=None,
    ctypes_module=None,
    installer_pids=None,
    window_pid=None,
) -> None:
    """Drive v0.20.3 confirmations and its owned assisted NSIS update UI."""
    if ctypes_module is None:
        import ctypes as ctypes_module
    if user32 is None:
        user32 = ctypes_module.windll.user32
    enum_windows_proc = ctypes_module.WINFUNCTYPE(
        ctypes_module.c_bool,
        ctypes_module.c_void_p,
        ctypes_module.c_void_p,
    )
    if installer_pids is None:
        def installer_pids():
            return find_process_ids(installer_image_name or "")
    if window_pid is None:
        def window_pid(hwnd):
            pid = ctypes_module.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes_module.byref(pid))
            return pid.value
    if observed is None:
        observed = []
    clicked_controls: set[tuple[int, str]] = set()
    deadline = time.monotonic() + timeout_s

    while not stop_event.is_set() and time.monotonic() < deadline:
        expected_title = next(
            (title for title in UPDATE_DIALOG_BUTTONS if title not in clicked),
            None,
        )
        if expected_title is None and installer_image_name is None:
            return
        owned_installer_pids = installer_pids() if expected_title is None else set()

        def inspect_window(hwnd, _lparam):
            title_length = user32.GetWindowTextLengthW(hwnd)
            if title_length <= 0:
                return True
            title_buffer = ctypes_module.create_unicode_buffer(title_length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            title = title_buffer.value
            if expected_title is not None and title != expected_title:
                return True
            if expected_title is None and (
                not title.startswith("STL Studio") or window_pid(hwnd) not in owned_installer_pids
            ):
                return True

            expected_button = (
                UPDATE_DIALOG_BUTTONS[expected_title]
                if expected_title is not None
                else None
            )
            available_buttons: dict[str, int] = {}

            def inspect_child(child_hwnd, _child_lparam):
                text_length = user32.GetWindowTextLengthW(child_hwnd)
                text_buffer = ctypes_module.create_unicode_buffer(text_length + 1)
                user32.GetWindowTextW(child_hwnd, text_buffer, len(text_buffer))
                button_text = text_buffer.value.replace("&", "").strip()
                available_buttons[button_text] = child_hwnd
                if expected_button is not None and button_text == expected_button:
                    user32.PostMessageW(child_hwnd, 0x00F5, 0, 0)  # BM_CLICK
                    clicked.append(expected_title)
                    return False
                return True

            user32.EnumChildWindows(hwnd, enum_windows_proc(inspect_child), 0)
            snapshot = f"{title}: {sorted(available_buttons)}"
            if snapshot not in observed:
                observed.append(snapshot)
            if expected_button is None:
                for button in NSIS_BUTTON_PRIORITY:
                    control = (int(hwnd), button)
                    if button in available_buttons and control not in clicked_controls:
                        user32.PostMessageW(available_buttons[button], 0x00F5, 0, 0)
                        clicked_controls.add(control)
                        break
            return expected_title is None or expected_title not in clicked

        user32.EnumWindows(enum_windows_proc(inspect_window), 0)
        stop_event.wait(0.25)

    if not stop_event.is_set() and len(clicked) != len(UPDATE_DIALOG_BUTTONS):
        missing = [title for title in UPDATE_DIALOG_BUTTONS if title not in clicked]
        raise TimeoutError(f"updater confirmation dialogs did not appear: {missing}")


def write_diagnostics(
    destination: Path,
    app_log: Path,
    search_roots: list[Path],
    observed_windows: list[str] | None = None,
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
        "observed_windows": observed_windows or [],
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


def read_system_info(port: int) -> dict:
    url = f"http://127.0.0.1:{port}/api/settings/system-info"
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)


def wait_for_updated_version(
    appdata: Path,
    previous_sidecar_pid: int,
    expected_version: str,
    timeout_s: float,
) -> dict:
    deadline = time.monotonic() + timeout_s
    last_error = "updated sidecar did not appear"
    while time.monotonic() < deadline:
        for lock_path in appdata.rglob("sidecar.lock.json"):
            try:
                record = json.loads(lock_path.read_text(encoding="utf-8"))
                if record.get("pid") == previous_sidecar_pid:
                    continue
                info = read_system_info(record["port"])
                if info.get("version") == expected_version:
                    return record
                last_error = f"relaunch reported version {info.get('version')!r}"
            except (KeyError, OSError, ValueError, TypeError, urllib.error.URLError) as error:
                last_error = str(error)
        time.sleep(0.5)
    raise TimeoutError(f"update did not reach {expected_version}: {last_error}")


@contextmanager
def serve_update_feed(directory: Path):
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def wait_for_absent(path: Path, timeout_s: float = TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not path.exists():
            return
        time.sleep(0.25)
    if path.exists():
        raise TimeoutError(f"path was not removed after {timeout_s}s: {path}")


def wait_for_paths_absent(paths: tuple[Path, ...], timeout_s: float = TIMEOUT_S) -> None:
    """Wait for NSIS to finish asynchronous shell-link cleanup."""
    for path in paths:
        wait_for_absent(path, timeout_s=timeout_s)


def find_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.rglob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern!r} under {root}, found {matches}")
    return matches[0]


def validate_candidate_feed(directory: Path, expected_version: str) -> None:
    metadata = directory / "latest.yml"
    if not metadata.is_file():
        raise RuntimeError("candidate update feed is missing latest.yml")
    version = next(
        (
            line.split(":", 1)[1].strip().strip("'\"")
            for line in metadata.read_text(encoding="utf-8").splitlines()
            if line.startswith("version:")
        ),
        None,
    )
    if version != expected_version:
        raise RuntimeError(
            f"candidate metadata version {version!r} does not match {expected_version!r}"
        )
    installer = find_one(directory, "STL-Studio-Setup-*.exe")
    blockmap = Path(f"{installer}.blockmap")
    if not blockmap.is_file():
        raise RuntimeError(f"candidate update feed is missing {blockmap.name}")


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], check=False, capture_output=True)


def kill_installed_app() -> None:
    subprocess.run(
        ["taskkill", "/T", "/F", "/IM", "STL Studio.exe"],
        check=False,
        capture_output=True,
    )


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
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--expected-version")
    parser.add_argument("--update-timeout", type=float, default=300)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("the installed-app smoke test requires Windows")

    installer = args.installer.resolve()
    if not installer.is_file():
        parser.error(f"installer not found: {installer}")
    if bool(args.candidate_dir) != bool(args.expected_version):
        parser.error("--candidate-dir and --expected-version must be provided together")
    candidate_dir = args.candidate_dir.resolve() if args.candidate_dir else None
    if candidate_dir is not None:
        try:
            validate_candidate_feed(candidate_dir, args.expected_version)
        except RuntimeError as error:
            parser.error(str(error))

    root = Path(tempfile.mkdtemp(prefix="stl-studio-installed-smoke-"))
    install_dir = root / "install"
    host_appdata = Path(os.environ.get("APPDATA", ""))
    host_localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
    shortcuts = installer_shortcuts(dict(os.environ))
    app_log = root / "electron.log"
    appdata, localappdata, env = prepare_data_paths(
        root,
        candidate_dir is not None,
        dict(os.environ),
    )
    db_path = localappdata / "STL-Inventory" / "stl_inventory.db"
    proc: subprocess.Popen | None = None
    feed_context = serve_update_feed(candidate_dir) if candidate_dir else None
    feed_url: str | None = None
    observed_windows: list[str] = []
    try:
        if feed_context:
            feed_url = feed_context.__enter__()
        subprocess.run([str(installer), "/S", f"/D={install_dir}"], check=True, env=env, timeout=120)
        app_exe = find_one(install_dir, "STL Studio.exe")
        require_paths(shortcuts, present=True, phase="custom install")
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
            if candidate_dir:
                db.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                    ("system_info_enabled", json.dumps(True)),
                )
            db.commit()

        # Installing the same package again exercises NSIS repair/reinstall
        # semantics. The application payload and user-owned database must both
        # remain usable before an update or ordinary relaunch is attempted.
        subprocess.run(
            [str(installer), "/S", f"/D={install_dir}"],
            check=True,
            env=env,
            timeout=120,
        )
        app_exe = find_one(install_dir, "STL Studio.exe")
        require_paths(shortcuts, present=True, phase="reinstall")
        with sqlite3.connect(db_path) as db:
            marker = db.execute(
                "SELECT value FROM app_settings WHERE key = ?", ("ci_installer_smoke",)
            ).fetchone()
        if marker != (json.dumps("preserved"),):
            raise RuntimeError(f"database marker did not survive reinstall: {marker}")

        if candidate_dir:
            assert feed_url is not None
            candidate_installer = find_one(candidate_dir, "STL-Studio-Setup-*.exe")
            write_update_feed_config(app_exe, feed_url)
            env.update({
                "STL_STUDIO_UPDATE_SMOKE": "1",
                "STL_STUDIO_UPDATE_FEED_URL": feed_url,
            })
            dialog_stop = threading.Event()
            clicked_dialogs: list[str] = []
            dialog_thread = threading.Thread(
                target=automate_update_dialogs,
                args=(
                    dialog_stop,
                    clicked_dialogs,
                    args.update_timeout,
                    candidate_installer.name,
                    observed_windows,
                ),
                daemon=True,
            )
            dialog_thread.start()
            with app_log.open("ab") as log:
                proc, first_lock = launch_and_probe(app_exe, env, appdata, log)
            try:
                wait_for_updated_version(
                    appdata,
                    first_lock["pid"],
                    args.expected_version,
                    args.update_timeout,
                )
            finally:
                dialog_stop.set()
                dialog_thread.join(timeout=5)
            if clicked_dialogs != list(UPDATE_DIALOG_BUTTONS):
                raise RuntimeError(
                    f"updater confirmations were incomplete: {clicked_dialogs}"
                )
            proc.wait(timeout=30)
            proc = None
            with sqlite3.connect(db_path) as db:
                marker = db.execute(
                    "SELECT value FROM app_settings WHERE key = ?", ("ci_installer_smoke",)
                ).fetchone()
            if marker != (json.dumps("preserved"),):
                raise RuntimeError(f"database marker did not survive update: {marker}")
            kill_installed_app()
            uninstaller = find_one(install_dir, "Uninstall*.exe")
            subprocess.run([str(uninstaller), "/S"], check=True, env=env, timeout=120)
            wait_for_absent(app_exe)
            wait_for_paths_absent(shortcuts)
            print(
                "smoke_installer: OK - install, update, relaunch, version, persistence, and uninstall"
            )
            return 0

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
        wait_for_paths_absent(shortcuts)
        if not db_path.is_file():
            raise RuntimeError("uninstall removed user database")

        # A second pass without /D proves the installer's default-directory
        # behavior independently of the custom-directory lifecycle above.
        subprocess.run([str(installer), "/S"], check=True, env=env, timeout=120)
        default_app_exe = find_one(host_localappdata / "Programs", "STL Studio.exe")
        require_paths(shortcuts, present=True, phase="default install")
        with app_log.open("ab") as log:
            proc, _ = launch_and_probe(default_app_exe, env, appdata, log)
        kill_tree(proc.pid)
        proc.wait(timeout=15)
        proc = None
        default_uninstaller = find_one(default_app_exe.parent, "Uninstall*.exe")
        subprocess.run([str(default_uninstaller), "/S"], check=True, env=env, timeout=120)
        wait_for_absent(default_app_exe)
        wait_for_paths_absent(shortcuts)
        if not db_path.is_file():
            raise RuntimeError("default uninstall removed user database")
        print(
            "smoke_installer: OK - custom/default install, reinstall, shortcuts, "
            "relaunch, persistence, and uninstall"
        )
        return 0
    except Exception:
        if args.diagnostics_dir:
            write_diagnostics(
                args.diagnostics_dir.resolve(),
                app_log,
                [appdata, localappdata, host_appdata, host_localappdata],
                observed_windows,
            )
        raise
    finally:
        if proc is not None and proc.poll() is None:
            kill_tree(proc.pid)
        if feed_context:
            feed_context.__exit__(None, None, None)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

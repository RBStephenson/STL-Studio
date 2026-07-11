"""Boot a freshly built standalone exe and confirm it actually serves (STUDIO-102).

CI builds the PyInstaller exe but never launches it, so a frozen-import crash
(e.g. STUDIO-100: `No module named 'unittest'`) only surfaces once a user runs
the installer. This script closes that gap: spawn the exe with an explicit free
port, poll /api/health until it answers or a deadline passes, then terminate it.
On failure it prints the exe's captured stdout/stderr — that's where the
traceback lands — and exits non-zero so CI fails loudly instead of shipping.

Usage:
    python scripts/smoke_boot.py path/to/stl-studio(.exe)
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# Matches desktop/src/config.ts HEALTH_POLL_*: Python + uvicorn cold start is
# the slow part, so give it generous headroom before declaring failure.
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_INTERVAL_S = 0.25
TERMINATE_GRACE_S = 5.0


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def probe_health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError):
        return False


def wait_for_health(
    proc: subprocess.Popen,
    port: int,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    interval_s: float = DEFAULT_INTERVAL_S,
    prober=probe_health,
) -> bool:
    """Poll `prober(port)` until it returns True, the deadline passes, or the
    process exits early (a crash, not a slow boot — fail immediately)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if prober(port):
            return True
        time.sleep(interval_s)
    return False


def terminate(proc: subprocess.Popen) -> None:
    """Kill the process tree, not just the immediate child — a hung grandchild
    (e.g. a subprocess the exe spawned) would otherwise keep the stdout pipe
    open forever and hang the output read below."""
    if proc.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
        )
        proc.wait(timeout=TERMINATE_GRACE_S)
        return
    proc.terminate()
    try:
        proc.wait(timeout=TERMINATE_GRACE_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=TERMINATE_GRACE_S)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe_path", type=Path, help="path to the built standalone exe")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args(argv)

    exe_path = args.exe_path.resolve()
    if not exe_path.is_file():
        print(f"smoke_boot: exe not found at {exe_path}", file=sys.stderr)
        return 1

    port = find_free_port()
    print(f"smoke_boot: launching {exe_path} --port {port}")
    try:
        proc = subprocess.Popen(
            [str(exe_path), "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as err:
        print(f"smoke_boot: FAILED to launch {exe_path}: {err}", file=sys.stderr)
        return 1

    healthy = wait_for_health(proc, port, timeout_s=args.timeout)
    crashed = proc.poll() is not None
    terminate(proc)
    try:
        output = proc.communicate(timeout=TERMINATE_GRACE_S)[0] or ""
    except subprocess.TimeoutExpired:
        output = "(output unavailable — a descendant process kept the pipe open)"

    if not healthy:
        reason = "process exited early" if crashed else "timed out waiting for /api/health"
        print(f"smoke_boot: FAILED ({reason}, exit code {proc.returncode})", file=sys.stderr)
        print("---- captured output ----", file=sys.stderr)
        print(output, file=sys.stderr)
        return 1

    print(f"smoke_boot: OK — {exe_path.name} served /api/health on port {port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Headless entry point for STL Studio (Phase 2 — STUDIO-72).

Serves the FastAPI backend + the pre-built Vite frontend in a single process on
127.0.0.1. All API routes are mounted under /api to match the frontend's
BASE = "/api". The SQLite database and config live in the platform user-data dir.

Under the Electron desktop shell (epic #528 / STUDIO-69) this runs as a windowless
sidecar: Electron owns presentation, spawns this with `--port`, polls /api/health,
and terminates it on quit. There is no native window here — the pywebview shell
(and its clr_loader/pythonnet backend) was removed in Phase 2.

The app itself comes from app.main.create_app — the same factory the Docker
deployment uses — so the standalone build cannot drift from it. This file only:
  - resolves the listen port (--port / STL_PORT / default 8484),
  - points DATABASE_URL at the user-data dir (before any app import),
  - serves the bundled frontend as static files,
  - serves in the foreground and shuts down gracefully on SIGTERM,
  - optionally opens the default browser (--open-browser) for dev source-runs.
"""
import argparse
import os
import signal
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Default listen port when neither --port nor STL_PORT is given. Kept at 8484 for
# backward compatibility and to match the Electron sidecar's fixed-port phase;
# Electron passes an explicit --port once it picks a free port.
DEFAULT_PORT = 8484
HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "STL-Inventory"


def _frontend_dist() -> Path:
    if getattr(sys, "frozen", False):
        # Running inside a PyInstaller bundle
        return Path(sys._MEIPASS) / "dist"  # type: ignore[attr-defined]
    # Running from source: project_root/frontend/dist
    return Path(__file__).parent.parent / "frontend" / "dist"


def _configure_env(data_dir: Path) -> None:
    """Point the app at the user-data DB (not the Docker /data volume). Must run
    before app.main is imported, since config binds the engine at import time."""
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir / 'stl_inventory.db'}"
    # STL_ROOTS starts empty — users add drives through the Settings page.
    os.environ.setdefault("STL_ROOTS", "")
    os.environ.setdefault("DEPLOYMENT_MODE", "standalone")


# ---------------------------------------------------------------------------
# CLI / port resolution
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stl-studio",
        description="Serve STL Studio headlessly on 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"TCP port to listen on (default: $STL_PORT or {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the default browser once the server is ready (dev source-runs).",
    )
    return parser


def resolve_port(cli_port: int | None, env: dict | None = None) -> int:
    """Resolve the listen port: explicit --port wins, then $STL_PORT, then the
    default. Invalid values fall back to the default rather than crashing."""
    if cli_port is not None:
        return cli_port
    env = os.environ if env is None else env
    raw = env.get("STL_PORT")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_PORT


# ---------------------------------------------------------------------------
# App + server
# ---------------------------------------------------------------------------

def build_app():
    """Build the FastAPI app and mount the bundled frontend at /.

    `_configure_env` must have run first. Kept out of module scope so importing
    this module (e.g. in tests) doesn't spin up the app + database.
    """
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from app.main import create_app

    app = create_app(api_prefix="/api")
    dist = _frontend_dist()
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="static-assets")

        # React Router serves real paths (/collections/12, /models/5, ...) that
        # don't exist as files. StaticFiles(html=True) only auto-serves
        # index.html for the root or an actual directory — not for those routes
        # — so reloading on one previously hit Starlette's 404 fallback and
        # returned raw JSON with no app loaded (STUDIO-374). This catch-all
        # serves any built asset that matches by path, and index.html for
        # everything else not under /api, restoring normal SPA-refresh behavior.
        dist_str = str(dist.resolve())

        @app.get("/{full_path:path}")
        def _spa_fallback(full_path: str):
            # full_path is attacker-controlled (any GET reaching 127.0.0.1
            # from the user's browser, not just the app itself). Normalize and
            # confirm the result's commonpath with dist is dist itself before
            # serving, or a ".." segment could read arbitrary files off disk —
            # the same commonpath check Starlette's own StaticFiles uses.
            joined = os.path.abspath(os.path.join(dist_str, full_path))
            if (
                full_path
                and os.path.commonpath([joined, dist_str]) == dist_str
                and os.path.isfile(joined)
            ):
                return FileResponse(joined)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/")
        def _no_frontend():
            return {"error": "Frontend not built. Run: cd frontend && npm run build"}
    return app


def _make_server(app, port: int):
    """A uvicorn Server bound to the loopback interface. Split out so tests can
    assert the bind config without starting the event loop."""
    import uvicorn

    return uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    )


def _make_sigterm_handler(server):
    """A signal handler that asks uvicorn to shut down gracefully. Named (not a
    closure buried in _serve) so it can be unit-tested directly."""

    def _handler(signum, frame):  # noqa: ARG001 - signal handler signature
        server.should_exit = True

    return _handler


def install_sigterm(server) -> None:
    """Route SIGTERM to a graceful uvicorn shutdown.

    Electron terminates the sidecar with SIGTERM on POSIX; this flips
    `should_exit` so in-flight requests drain instead of the process being cut
    off. On Windows Electron uses `taskkill /F` (TerminateProcess), which is not
    catchable — there graceful shutdown isn't possible and this is a no-op path.
    """
    signal.signal(signal.SIGTERM, _make_sigterm_handler(server))


def _wait_for_server(port: int, timeout: float = 20.0) -> bool:
    """Block until the local server accepts connections, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((HOST, port)) == 0:
                return True
        time.sleep(0.2)
    return False


def _open_browser_when_ready(url: str, port: int) -> None:
    if _wait_for_server(port):
        webbrowser.open(url)


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def run(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    port = resolve_port(args.port)

    data_dir = _user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_env(data_dir)

    url = f"http://localhost:{port}"
    print(f"STL Studio serving at {url}")
    print(f"Data stored in: {data_dir}")

    app = build_app()
    server = _make_server(app, port)
    install_sigterm(server)

    if args.open_browser:
        threading.Thread(
            target=_open_browser_when_ready, args=(url, port), daemon=True
        ).start()

    # Foreground serve on the main thread; uvicorn + our SIGTERM handler own
    # process lifetime. Electron (or Ctrl-C) drives shutdown.
    server.run()


if __name__ == "__main__":
    run()

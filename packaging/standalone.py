"""
Standalone entry point for STL Studio.

Serves the FastAPI backend + the pre-built Vite frontend in a single process.
All API routes are mounted under /api to match the frontend's BASE = "/api".
The SQLite database and config are stored in the platform-appropriate user data dir.

The app itself (routers, middleware, startup migrations) comes from
app.main.create_app — the same factory the Docker deployment uses — so the
standalone build cannot drift from it. This file only handles:
  - pointing DATABASE_URL at the user data dir (before any app import),
  - serving the bundled frontend as static files,
  - showing the app in a native window via pywebview, falling back to the
    default browser when no webview backend is available (#463).
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

PORT = 8484


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


# ---------------------------------------------------------------------------
# App + server
# ---------------------------------------------------------------------------

def build_app():
    """Build the FastAPI app and mount the bundled frontend at /.

    `_configure_env` must have run first. Kept out of module scope so importing
    this module (e.g. in tests) doesn't spin up the app + database.
    """
    from fastapi.staticfiles import StaticFiles
    from app.main import create_app

    app = create_app(api_prefix="/api")
    dist = _frontend_dist()
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")
    else:
        @app.get("/")
        def _no_frontend():
            return {"error": "Frontend not built. Run: cd frontend && npm run build"}
    return app


def _wait_for_server(port: int, timeout: float = 20.0) -> bool:
    """Block until the local server accepts connections, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def _serve_foreground(app) -> None:
    """Run uvicorn on the main thread (browser/headless mode)."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def _serve_background(app) -> None:
    """Run uvicorn from a non-main thread (window mode). Signal handlers only work
    on the main thread, so disable them — the webview owns process lifetime."""
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    )
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    server.run()


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def should_use_window(env: dict | None = None, webview_available: bool = True) -> bool:
    """Decide whether to open a native window (#463). A window is used unless the
    user opted out with STL_NO_WINDOW=1 or no webview backend is importable."""
    env = os.environ if env is None else env
    if env.get("STL_NO_WINDOW") == "1":
        return False
    return webview_available


def _open_browser_when_ready(url: str) -> None:
    if _wait_for_server(PORT):
        webbrowser.open(url)


def run() -> None:
    data_dir = _user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_env(data_dir)

    url = f"http://localhost:{PORT}"
    print(f"STL Studio running at {url}")
    print(f"Data stored in: {data_dir}")

    webview = None
    if should_use_window():
        try:
            import webview as _wv  # type: ignore
            webview = _wv
        except Exception:
            webview = None  # no desktop extra installed — browser fallback

    app = build_app()

    if webview is None:
        # Browser mode (opt-out or no webview): serve in the foreground and pop
        # the default browser once the server answers — the original behaviour.
        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
        _serve_foreground(app)
        return

    # Native window: server on a daemon thread, webview owns the main thread.
    threading.Thread(target=_serve_background, args=(app,), daemon=True).start()
    if not _wait_for_server(PORT):
        print("Server did not start in time; opening browser instead.")
        webbrowser.open(url)
        threading.Event().wait()
        return
    try:
        webview.create_window("STL Studio", url, width=1400, height=900)
        webview.start()
    except Exception as exc:  # no usable GUI backend — degrade to the browser
        print(f"Native window unavailable ({exc}); opening browser instead.")
        webbrowser.open(url)
        threading.Event().wait()


if __name__ == "__main__":
    run()

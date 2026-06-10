"""
Standalone entry point for STL Library.

Serves the FastAPI backend + the pre-built Vite frontend in a single process.
All API routes are mounted under /api to match the frontend's BASE = "/api".
The SQLite database and config are stored in the platform-appropriate user data dir.

The app itself (routers, middleware, startup migrations) comes from
app.main.create_app — the same factory the Docker deployment uses — so the
standalone build cannot drift from it. This file only handles:
  - pointing DATABASE_URL at the user data dir (before any app import),
  - serving the bundled frontend as static files,
  - launching uvicorn and opening the browser.
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


# ---------------------------------------------------------------------------
# Resolve paths before importing app modules
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


data_dir = _user_data_dir()
data_dir.mkdir(parents=True, exist_ok=True)

# Point the app at the user-data DB (not the Docker /data volume)
os.environ["DATABASE_URL"] = f"sqlite:///{data_dir / 'stl_inventory.db'}"
# STL_ROOTS starts empty — users add drives through the Settings page
os.environ.setdefault("STL_ROOTS", "")

# ---------------------------------------------------------------------------
# Build the FastAPI app
# ---------------------------------------------------------------------------

from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.main import create_app  # noqa: E402

# All API routes under /api (the React frontend calls BASE = "/api")
app = create_app(api_prefix="/api")

# Serve the built React frontend from /
dist = _frontend_dist()
if dist.exists():
    app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")
else:
    @app.get("/")
    def _no_frontend():
        return {"error": "Frontend not built. Run: cd frontend && npm run build"}

# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

PORT = 8484


def _open_browser():
    time.sleep(2.0)
    webbrowser.open(f"http://localhost:{PORT}")


if __name__ == "__main__":
    import uvicorn

    print(f"STL Library running at http://localhost:{PORT}")
    print(f"Data stored in: {data_dir}")
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

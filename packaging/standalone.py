"""
Standalone entry point for STL Inventory.

Serves the FastAPI backend + the pre-built Vite frontend in a single process.
All API routes are mounted under /api to match the frontend's BASE = "/api".
The SQLite database and config are stored in the platform-appropriate user data dir.
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

from fastapi import FastAPI                                    # noqa: E402
from fastapi.middleware.cors import CORSMiddleware              # noqa: E402
from fastapi.staticfiles import StaticFiles                    # noqa: E402

from app.database import Base, engine, SessionLocal            # noqa: E402
from app.routers import models, scan, files, collections, scrape, enrich  # noqa: E402

# Create all tables (including any new columns — startup migration runs next)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="STL Inventory")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _migrate():
    """Add columns that didn't exist in earlier DB versions."""
    from sqlalchemy import text
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(stl_files)"))}
        if "part_type" not in cols:
            conn.execute(text("ALTER TABLE stl_files ADD COLUMN part_type TEXT"))
            conn.commit()
        root_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(scan_roots)"))}
        if "layout" not in root_cols:
            conn.execute(text("ALTER TABLE scan_roots ADD COLUMN layout VARCHAR NOT NULL DEFAULT '{creator}'"))
            conn.commit()


@app.on_event("startup")
def _seed_tags():
    """Rebuild model_tags index if it's empty but models exist (first run)."""
    from sqlalchemy import func, text
    from app.models import Model, ModelTag
    from app.services.tag_sync import rebuild_all_tags
    db = SessionLocal()
    try:
        if db.query(func.count(ModelTag.id)).scalar() == 0 and \
           db.query(func.count(Model.id)).scalar() > 0:
            rebuild_all_tags(db)
    finally:
        db.close()


# All API routes under /api (the React frontend calls BASE = "/api")
app.include_router(models.router,      prefix="/api")
app.include_router(scan.router,        prefix="/api")
app.include_router(files.router,       prefix="/api")
app.include_router(collections.router, prefix="/api")
app.include_router(scrape.router,      prefix="/api")
app.include_router(enrich.router,      prefix="/api")

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

    print(f"STL Inventory running at http://localhost:{PORT}")
    print(f"Data stored in: {data_dir}")
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

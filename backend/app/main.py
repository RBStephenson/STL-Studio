from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import Base, engine, SessionLocal
from app.routers import models, scan, files, collections, scrape, enrich, database
# Registers the paint_*/guide_* tables on Base before create_all below.
from app.painting import models as painting_models  # noqa: F401
from app.painting.routers import router as painting_router

Base.metadata.create_all(bind=engine)


def _migrate_schema():
    """Add columns that didn't exist in earlier schema versions."""
    import logging
    from sqlalchemy import text
    logger = logging.getLogger(__name__)

    # (table, column, column definition) for additive migrations
    migrations = [
        ("stl_files", "part_type", "TEXT"),
        ("models", "is_favorite", "BOOLEAN DEFAULT 0"),
        ("models", "in_queue", "BOOLEAN DEFAULT 0"),
        ("models", "queued_at", "DATETIME"),
        ("models", "printed_at", "DATETIME"),
        ("models", "queue_position", "INTEGER"),
        ("models", "excluded", "BOOLEAN DEFAULT 0"),
        ("scan_roots", "layout", "VARCHAR NOT NULL DEFAULT '{creator}'"),
    ]
    with engine.connect() as conn:
        table_cols: dict[str, set[str]] = {}
        for table, column, coldef in migrations:
            if table not in table_cols:
                table_cols[table] = {
                    r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))
                }
            if column not in table_cols[table]:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}"))
                conn.commit()
                logger.info(f"Migrated: added {table}.{column}")


def _seed_tag_index():
    """Populate model_tags from JSON columns if the table is empty (one-time migration)."""
    import logging
    from sqlalchemy import func, text
    from app.models import Model, ModelTag
    from app.services.tag_sync import rebuild_all_tags

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        tag_count = db.query(func.count(ModelTag.id)).scalar()
        model_count = db.query(func.count(Model.id)).scalar()
        if tag_count == 0 and model_count > 0:
            logger.info(f"model_tags empty with {model_count} models — running initial rebuild")
            rebuild_all_tags(db)
    except Exception:
        logger.exception("Failed to seed model_tags on startup")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One-time startup migrations / seeding, run before the app serves requests.
    _migrate_schema()
    _seed_tag_index()
    yield


# --- Localhost CSRF protection (#213) -------------------------------------
# The server binds to 127.0.0.1, but any web page the user visits can still
# fire requests at http://localhost:<port>. Browsers attach an Origin header
# to cross-site requests, and a DNS-rebinding page arrives with a non-local
# Host header — so state-changing requests must present local values for both.

_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_local_hostname(hostname: str | None) -> bool:
    return hostname is not None and hostname.lower() in _LOCAL_HOSTNAMES


def _origin_is_local(origin: str) -> bool:
    return _is_local_hostname(urlsplit(origin).hostname)


def _host_is_local(host: str) -> bool:
    # Host is "name[:port]" or "[v6addr][:port]" — parse as a netloc.
    try:
        return _is_local_hostname(urlsplit(f"//{host}").hostname)
    except ValueError:
        return False


async def _block_cross_origin_writes(request, call_next):
    if request.method in _UNSAFE_METHODS:
        origin = request.headers.get("origin")
        # No Origin header = not a browser cross-site request (curl, scripts).
        if origin is not None and not _origin_is_local(origin):
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin request blocked"},
            )
        if not _host_is_local(request.headers.get("host", "")):
            return JSONResponse(
                status_code=403,
                content={"detail": "Request Host not allowed"},
            )
    return await call_next(request)


_health_router = APIRouter()


@_health_router.get("/health")
def health():
    return {"status": "ok"}


def create_app(api_prefix: str = "") -> FastAPI:
    """Build the STL Library API app.

    Single source of truth for routers, middleware, and startup migrations —
    used by both the Docker deployment (no prefix; nginx adds /api) and the
    standalone binary (api_prefix="/api", frontend served from the same app).
    """
    app = FastAPI(title="STL Library", version="0.1.0", lifespan=lifespan)

    app.middleware("http")(_block_cross_origin_writes)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:80", "http://localhost"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        models.router,
        scan.router,
        files.router,
        collections.router,
        scrape.router,
        enrich.router,
        database.router,
        painting_router,
        _health_router,
    ):
        app.include_router(router, prefix=api_prefix)

    return app


app = create_app()

from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import Base, engine, SessionLocal
from app.routers import models, scan, files, collections, scrape, enrich, database, settings
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
        ("models", "queued_at", "DATETIME"),
        ("models", "printed_at", "DATETIME"),
        ("models", "queue_position", "INTEGER"),
        ("models", "excluded", "BOOLEAN DEFAULT 0"),
        ("scan_roots", "layout", "VARCHAR NOT NULL DEFAULT '{creator}'"),
        ("paints", "size", "TEXT"),
        ("paints", "count", "INTEGER DEFAULT 1"),
        # Painting M2 #268 added these to guide tables that M0/#258 had already
        # created, so create_all never adds them to a pre-#268 DB (#279 follow-up:
        # guides list/reader 500 with "no such column: guides.title_lead").
        ("guides", "title_lead", "TEXT"),
        ("guides", "subtitle", "TEXT"),
        ("guides", "category_label", "TEXT"),
        ("guides", "quote", "TEXT"),
        ("guides", "head_style", "TEXT"),
        ("guide_tabs", "dom_id", "TEXT"),
        ("guide_tabs", "subtabs", "JSON DEFAULT '[]'"),
        ("guide_tabs", "method_block", "JSON"),
        # The remaining guide_tabs JSON/flag columns. A DB created at an
        # intermediate schema version can be missing any subset of these (the
        # #280 migration only covered dom_id/subtabs/method_block, so e.g.
        # guide_tabs.section was absent → import 500 "no column named section").
        ("guide_tabs", "has_expert_subtab", "BOOLEAN DEFAULT 0"),
        ("guide_tabs", "section", "JSON"),
        ("guide_tabs", "value_map", "JSON"),
        ("guide_tabs", "skin_config", "JSON"),
        ("guide_tabs", "metals_config", "JSON"),
        ("guide_tabs", "callouts", "JSON DEFAULT '[]'"),
        ("guide_phases", "subtab_key", "TEXT"),
        ("guide_steps", "technique_label", "TEXT"),
        ("models", "print_status", "VARCHAR NOT NULL DEFAULT 'none'"),
        ("models", "print_count", "INTEGER NOT NULL DEFAULT 0"),
        ("models", "user_rating", "INTEGER"),
        ("models", "removed_auto_tags", "JSON DEFAULT '[]'"),
        ("models", "image_manifest", "JSON"),
        ("models", "image_manifest_sig", "TEXT"),
    ]
    with engine.connect() as conn:
        table_cols: dict[str, set[str]] = {}
        for table, column, coldef in migrations:
            if table not in table_cols:
                table_cols[table] = {
                    r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))
                }
            if not table_cols[table]:
                # Table doesn't exist at all (DB predates the feature module);
                # create_all owns table creation, so there's nothing to alter.
                continue
            if column not in table_cols[table]:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}"))
                conn.commit()
                logger.info(f"Migrated: added {table}.{column}")

        # One-time backfill: derive print_status from the legacy in_queue / printed_at
        # flags for DBs that predate the lifecycle column (#166). The column was added
        # defaulting to 'none', so models tracked under the old flag-based system need
        # their status set once. Guarded by an app_settings flag because after this the
        # legacy columns are no longer maintained — re-running could resurrect stale
        # state. Queued wins over printed: a re-queued reprint reflects current intent,
        # while printed_at / print_count preserve the print history.
        existing_tables = {
            r[0] for r in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ))
        }
        model_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(models)"))}
        if (
            "app_settings" in existing_tables
            and "in_queue" in model_cols
            and "print_status" in model_cols
        ):
            already_done = conn.execute(text(
                "SELECT 1 FROM app_settings WHERE key = 'print_status_backfilled'"
            )).first()
            if not already_done:
                # Order matters — set queued first, then only fill printed where the
                # status is still untouched, so a both-flags row lands on 'queued'.
                conn.execute(text(
                    "UPDATE models SET print_status = 'queued' "
                    "WHERE print_status = 'none' AND in_queue = 1"
                ))
                conn.execute(text(
                    "UPDATE models SET print_status = 'printed' "
                    "WHERE print_status = 'none' AND printed_at IS NOT NULL"
                ))
                conn.execute(text(
                    "UPDATE models SET print_count = 1 "
                    "WHERE print_status = 'printed' AND print_count = 0"
                ))
                conn.execute(text(
                    "INSERT INTO app_settings (key, value) "
                    "VALUES ('print_status_backfilled', 'true')"
                ))
                conn.commit()
                logger.info("Migrated: backfilled print_status from legacy flags")

        # One-time cleanup of collection_models rows orphaned by collection
        # deletes from before the manual cascade existed (#214). Left in
        # place, they attach to any new collection that reuses the rowid.
        result = conn.execute(text(
            "DELETE FROM collection_models WHERE "
            "collection_id NOT IN (SELECT id FROM collections) "
            "OR model_id NOT IN (SELECT id FROM models)"
        ))
        conn.commit()
        if result.rowcount:
            logger.info(f"Migrated: removed {result.rowcount} orphaned collection_models rows")


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


def _run_migrations() -> None:
    """Run Alembic migrations at startup.

    Legacy DBs (created before Alembic was introduced) have no alembic_version
    table. For those we run the hand-rolled _migrate_schema() one final time to
    bring all columns up to date, then stamp the DB at revision 0001 (baseline)
    so future Alembic migrations apply cleanly. New and already-stamped DBs go
    straight through `upgrade head`.
    """
    import logging
    from pathlib import Path
    from sqlalchemy import text
    from alembic.config import Config
    from alembic import command

    logger = logging.getLogger(__name__)
    alembic_cfg = Config(Path(__file__).parent.parent / "alembic.ini")

    with engine.connect() as conn:
        tables = {
            r[0] for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }

    if "alembic_version" not in tables:
        _migrate_schema()
        command.stamp(alembic_cfg, "head")
        logger.info("Alembic: stamped legacy/new DB at head (0001 baseline)")
    else:
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic: schema up to date")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One-time startup migrations / seeding, run before the app serves requests.
    _run_migrations()
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
        settings.router,
        painting_router,
        _health_router,
    ):
        app.include_router(router, prefix=api_prefix)

    return app


app = create_app()

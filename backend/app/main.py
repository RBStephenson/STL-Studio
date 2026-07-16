from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings as app_settings
from app.database import Base, engine, SessionLocal
from app.routers import (
    models, tags, groups, print_queue, thumbnails,
    scan, files, collections, scrape, enrich, database, settings, reorganize, imports, cults,
)
# Registers the paint_*/guide_* tables on Base so create_all (run in
# _run_migrations at startup) sees the full metadata.
from app.painting import models as painting_models  # noqa: F401
from app.painting.routers import router as painting_router


def _migrate_schema():
    """Bring a legacy (pre-Alembic) DB's columns up to date, one final time.

    FROZEN (STUDIO-57): do NOT append to the `migrations` list below. This
    hand-rolled additive loop only runs for DBs that predate Alembic (no
    alembic_version table) — see _run_migrations. Every schema change from now
    on is an Alembic migration; new columns are created by `create_all` on
    fresh DBs and by an Alembic revision on already-managed ones.
    """
    import logging
    from sqlalchemy import text
    logger = logging.getLogger(__name__)

    # (table, column, column definition) for additive migrations.
    # FROZEN — see docstring. New columns go in an Alembic revision, not here.
    migrations = [
        ("stl_files", "part_type", "TEXT"),
        ("models", "is_favorite", "BOOLEAN DEFAULT 0"),
        ("models", "is_group_rep", "BOOLEAN NOT NULL DEFAULT 0"),
        ("models", "queued_at", "DATETIME"),
        ("models", "printed_at", "DATETIME"),
        ("models", "queue_position", "INTEGER"),
        ("models", "variant_order", "INTEGER"),
        ("models", "excluded", "BOOLEAN DEFAULT 0"),
        ("scan_roots", "layout", "VARCHAR NOT NULL DEFAULT '{creator}'"),
        ("scan_roots", "name", "VARCHAR"),
        ("scan_roots", "is_writable", "BOOLEAN NOT NULL DEFAULT 0"),
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
        ("guides", "series_badge", "JSON"),
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
        ("guide_tabs", "raw_blocks", "JSON DEFAULT '[]'"),
        ("guide_phases", "subtab_key", "TEXT"),
        ("guide_steps", "technique_label", "TEXT"),
        # #425: a mix component can be a name-only row when it doesn't resolve to a
        # shelf paint. The paint_id NOT-NULL relax is an Alembic-batch rebuild
        # (0011); only the additive name column is handled here.
        ("guide_mix_components", "name", "TEXT"),
        # #477: same for a single swatch (paint_id relax in Alembic 0012).
        ("guide_swatches", "name", "TEXT"),
        ("models", "print_status", "VARCHAR NOT NULL DEFAULT 'none'"),
        ("models", "print_count", "INTEGER NOT NULL DEFAULT 0"),
        ("models", "user_rating", "INTEGER"),
        ("models", "removed_auto_tags", "JSON DEFAULT '[]'"),
        ("models", "removed_image_paths", "JSON DEFAULT '[]'"),
        ("models", "image_manifest", "JSON"),
        ("models", "image_manifest_sig", "TEXT"),
        ("models", "is_inbox", "BOOLEAN NOT NULL DEFAULT 0"),
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
    from sqlalchemy import func
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


def _backfill_missing_variant_groups() -> int:
    """Repair legacy DBs that have scanner characters but no durable groups.

    Standalone builds can open older local SQLite files that predate Alembic.
    `create_all()` creates the modern tables before `_run_migrations()` decides
    whether to stamp those DBs, so historical data migrations such as 0017's
    variant-group backfill may never run. This repair is intentionally narrow:
    it only groups live, unpinned models that still have no variant_group_id and
    share the same (creator_id, character).
    """
    from collections import defaultdict
    import logging

    from sqlalchemy import text

    from app.models import Model, VariantGroup

    logger = logging.getLogger(__name__)
    with engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        if "models" not in tables:
            return 0
        model_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(models)"))}
        if "variant_group_id" not in model_cols:
            conn.execute(text("ALTER TABLE models ADD COLUMN variant_group_id INTEGER"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_models_variant_group_id "
            "ON models (variant_group_id)"
        ))
        conn.commit()
        if "no_group" not in model_cols:
            conn.execute(text(
                "ALTER TABLE models ADD COLUMN no_group BOOLEAN NOT NULL DEFAULT 0"
            ))
            conn.commit()

    db = SessionLocal()
    created = 0
    try:
        rows = (
            db.query(Model)
            .filter(
                Model.excluded == False,  # noqa: E712
                Model.no_group == False,  # noqa: E712
                Model.creator_id != None,  # noqa: E711
                Model.character != None,  # noqa: E711
                Model.character != "",
                Model.variant_group_id == None,  # noqa: E711
            )
            .all()
        )
        buckets: dict[tuple[int, str], list[Model]] = defaultdict(list)
        for model in rows:
            if model.creator_id is None or not model.character:
                continue
            buckets[(model.creator_id, model.character)].append(model)

        for (creator_id, label), members in buckets.items():
            if len(members) < 2:
                continue
            group = VariantGroup(
                creator_id=creator_id,
                label=label,
                rep_model_id=next((m.id for m in members if m.is_group_rep), members[0].id),
                source="auto",
                reason="legacy character backfill",
                confidence=0.6,
            )
            db.add(group)
            db.flush()
            for member in members:
                member.variant_group_id = group.id
            created += 1

        if created:
            db.commit()
            logger.info("Backfilled %s missing variant group(s)", created)
        else:
            db.rollback()
        return created
    except Exception:
        db.rollback()
        logger.exception("Failed to backfill missing variant groups")
        return 0
    finally:
        db.close()


def _run_migrations() -> None:
    """Create tables and reconcile schema at startup.

    `create_all` is the table creator: on a fresh DB it builds the whole
    schema from the live metadata; on a legacy/managed DB it only adds tables
    introduced since that DB was created (create_all never alters or drops).
    It runs here — inside the lifespan, deterministically before Alembic —
    rather than as an import-time side effect (STUDIO-57).

    Legacy DBs (created before Alembic) have no alembic_version table. For
    those we run the frozen _migrate_schema() one final time to add any missing
    columns, then stamp at head so future Alembic migrations apply cleanly.
    Already-managed DBs go straight through `upgrade head`.
    """
    import logging
    from pathlib import Path
    from sqlalchemy import text
    from alembic.config import Config
    from alembic import command
    from alembic.script import ScriptDirectory

    import sys

    from app.services.database_upgrade import (
        create_upgrade_snapshot,
        restore_upgrade_snapshot,
    )

    logger = logging.getLogger(__name__)

    if getattr(sys, "frozen", False):
        # PyInstaller bundle: alembic.ini and alembic/ are extracted to sys._MEIPASS
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent.parent
    alembic_cfg = Config(base / "alembic.ini")
    alembic_cfg.set_main_option("script_location", str(base / "alembic"))
    head_revision = ScriptDirectory.from_config(alembic_cfg).get_current_head()
    if head_revision is None:
        raise RuntimeError("Alembic migration history has no head revision")

    snapshot = create_upgrade_snapshot(engine, head_revision)
    try:
        # Table creation, moved off import time (STUDIO-57). alembic_version is not
        # part of the metadata, so this never affects the legacy-vs-managed branch.
        Base.metadata.create_all(bind=engine)
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
    except Exception:
        if snapshot is not None:
            restore_upgrade_snapshot(engine, snapshot)
            logger.exception(
                "Database migration failed; restored pre-upgrade snapshot %s",
                snapshot,
            )
        raise


def _apply_persisted_log_level():
    """Apply a log level persisted via the Settings UI, overriding the env default.

    Runs at startup once the DB is available so a level chosen in the UI
    survives a restart. An invalid stored value is ignored (kept resilient —
    the schema validates on write, so this only guards against manual edits).
    """
    import logging
    from app.logging_config import apply_log_level
    from app.models import AppSetting

    db = SessionLocal()
    try:
        row = db.get(AppSetting, "log_level")
        if row and row.value:
            apply_log_level(row.value)
    except ValueError:
        logging.getLogger("app").warning(
            "Ignoring invalid persisted log_level"
        )
    except Exception:
        # Best-effort, mirroring the other startup helpers: a DB that isn't
        # ready yet (e.g. under test harnesses) must not abort startup. The env
        # LOG_LEVEL default already applied in configure_logging stays in force.
        logging.getLogger("app").debug("Could not read persisted log_level", exc_info=True)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One-time startup migrations / seeding, run before the app serves requests.
    _run_migrations()
    _backfill_missing_variant_groups()
    _seed_tag_index()
    _apply_persisted_log_level()
    yield


# --- Write-request origin/host guard (#213) -------------------------------
# The server binds to 127.0.0.1, but any web page the user visits can still
# fire requests at http://localhost:<port>. Browsers attach an Origin header
# to cross-site requests, and a DNS-rebinding page arrives with a non-local
# Host header — so state-changing requests must present a trusted value for both.
#
# "Trusted" is localhost by default, plus any hostnames in TRUSTED_HOSTS. A
# reverse-proxy deployment on a custom domain (e.g. stl.pagden.us) sets that so
# its own writes are allowed, without weakening the guard for anyone else.

_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_trusted_hostname(hostname: str | None) -> bool:
    if hostname is None:
        return False
    h = hostname.lower()
    return h in _LOCAL_HOSTNAMES or h in app_settings.trusted_host_list


def _origin_is_trusted(origin: str) -> bool:
    return _is_trusted_hostname(urlsplit(origin).hostname)


def _host_is_trusted(host: str) -> bool:
    # Host is "name[:port]" or "[v6addr][:port]" — parse as a netloc.
    try:
        return _is_trusted_hostname(urlsplit(f"//{host}").hostname)
    except ValueError:
        return False


async def _block_cross_origin_writes(request, call_next):
    if request.method in _UNSAFE_METHODS:
        origin = request.headers.get("origin")
        # No Origin header = not a browser cross-site request (curl, scripts).
        if origin is not None and not _origin_is_trusted(origin):
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin request blocked"},
            )
        if not _host_is_trusted(request.headers.get("host", "")):
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
    """Build the STL Studio API app.

    Single source of truth for routers, middleware, and startup migrations —
    used by both the Docker deployment (no prefix; nginx adds /api) and the
    standalone binary (api_prefix="/api", frontend served from the same app).
    """
    # Bootstrap logging from the env default (LOG_LEVEL). A level persisted in
    # the DB via the Settings UI is applied later, in the lifespan startup, once
    # the database is available (see _apply_persisted_log_level).
    from app.logging_config import configure_logging
    configure_logging(app_settings.log_level)
    app = FastAPI(title="STL Studio", version="0.1.0", lifespan=lifespan)

    app.middleware("http")(_block_cross_origin_writes)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:80", "http://localhost"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        # The tag/group/print-queue/thumbnail routers carry literal `/models/...`
        # paths (e.g. /grouping-strategy, /bulk) that must be matched before the
        # core models router's `/{model_id}` catch-all — so models.router is
        # registered LAST of this family (STUDIO-58).
        tags.router,
        groups.router,
        print_queue.router,
        thumbnails.router,
        models.router,
        scan.router,
        files.router,
        collections.router,
        scrape.router,
        enrich.router,
        database.router,
        settings.router,
        reorganize.router,
        imports.router,
        painting_router,
        cults.router,
        _health_router,
    ):
        app.include_router(router, prefix=api_prefix)

    return app


app = create_app()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine, SessionLocal
from app.routers import models, scan, files, collections, scrape, enrich

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


app = FastAPI(title="STL Inventory", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:80", "http://localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(models.router)
app.include_router(scan.router)
app.include_router(files.router)
app.include_router(collections.router)
app.include_router(scrape.router)
app.include_router(enrich.router)


@app.get("/health")
def health():
    return {"status": "ok"}

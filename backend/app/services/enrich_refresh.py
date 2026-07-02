"""
Library-wide storefront refresh, run off the request path.

An empty-scope POST /enrich/refresh used to re-fetch storefront detail for
every enriched model synchronously on the request thread — minutes for a big
library, HTTP timeout risk. This mirrors the background-job pattern already
used for scans (services/scanner.py): a module-level status dict guarded by a
lock, and a plain function the router runs in a daemon thread. The function is
also safe to call directly (as the scanner tests do with scan_all_roots) for
deterministic, non-threaded test coverage.
"""
import asyncio
import dataclasses
import logging
import threading
from datetime import timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Model
from app.services import scrapers
from app.services import secrets as secrets_service
from app.services.metadata_apply import apply_scraped_to_model
from app.services.scrapers.base import ScrapedModel
from app.utils import utcnow

logger = logging.getLogger(__name__)

# Each selected match triggers a detail fetch (MMF/Cults API or Gumroad scrape).
# Bound the parallelism so we don't hammer a source or serialize the whole batch.
_FETCH_CONCURRENCY = 5

_state_lock = threading.Lock()
_refresh_state: dict = {
    "running": False, "message": "idle",
    "candidates": 0, "refreshed": 0, "failed": 0, "errors": 0,
}


def get_status() -> dict:
    with _state_lock:
        return dict(_refresh_state)


async def fetch_unique_deep(
    urls: set[str], mmf_key: Optional[str]
) -> dict[str, Optional[ScrapedModel]]:
    """Fetch full detail for each unique product URL once, bounded-concurrently.

    Variants share a product listing, so a URL is only fetched once and fanned
    out to every model that references it. A URL whose fetch fails maps to None
    so callers can decide how to degrade. Shared by the bulk-apply router path
    and the refresh below so their fetch behaviour can't drift.
    """
    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def _one(url: str):
        async with sem:
            try:
                return url, await scrapers.fetch_url(url, mmf_api_key=mmf_key)
            except Exception as e:
                logger.warning(f"Enrich: detail fetch failed for {url}: {e}")
                return url, None

    return dict(await asyncio.gather(*(_one(u) for u in urls)))


async def _do_refresh(
    db: Session,
    creator_id: Optional[int],
    model_ids: Optional[list[int]],
    stale_days: Optional[int],
) -> dict:
    query = db.query(Model).filter(Model.source_url.isnot(None))
    if creator_id is not None:
        query = query.filter(Model.creator_id == creator_id)
    if model_ids:
        query = query.filter(Model.id.in_(model_ids))
    if stale_days is not None:
        cutoff = utcnow() - timedelta(days=stale_days)
        query = query.filter(
            or_(
                Model.source_last_fetched.is_(None),
                Model.source_last_fetched < cutoff,
            )
        )

    models = query.all()
    if not models:
        return {"candidates": 0, "refreshed": 0, "failed": 0, "errors": 0}

    mmf_key = secrets_service.resolve_mmf_api_key(db)
    unique_urls = {m.source_url for m in models if m.source_url}
    fetched = await fetch_unique_deep(unique_urls, mmf_key)

    refreshed = failed = errors = 0
    for model in models:
        base = fetched.get(model.source_url)
        if base is None:
            failed += 1
            continue
        # Keep the model's existing source identity without mutating the shared
        # ScrapedModel — it's reused across every sibling on the same URL (#699 2.2).
        scraped = dataclasses.replace(
            base,
            source_url=base.source_url or model.source_url,
            source_site=base.source_site or model.source_site,
            external_id=base.external_id or model.external_id,
        )
        try:
            # Refresh operates on already-matched data, so it overwrites aggressively —
            # but still never re-points creator_id (#699 1.1); a refresh isn't a review.
            await apply_scraped_to_model(
                db, model, scraped,
                overwrite_title=True, thumbnail_fill_only=False,
                reassign_creator=False, clear_needs_review=True,
            )
            refreshed += 1
        except Exception as e:
            logger.warning(f"Enrich: refresh apply failed for model {model.id} ({model.source_url}): {e}")
            errors += 1

    db.commit()
    return {
        "candidates": len(models),
        "refreshed": refreshed,
        "failed": failed,
        "errors": errors,
    }


def run_refresh(
    creator_id: Optional[int] = None,
    model_ids: Optional[list[int]] = None,
    stale_days: Optional[int] = None,
    db: Optional[Session] = None,
) -> dict:
    """Run a refresh to completion, updating the shared status as it goes.

    Blocking — callers that don't want to block the request thread run this in
    a background thread (see the /enrich/refresh route) the same way
    scan_all_roots is run from /scan/start. Pass ``db`` to run inline against a
    caller-owned session (tests); omitted, it opens and closes its own.
    """
    with _state_lock:
        _refresh_state.update(
            running=True, message="starting",
            candidates=0, refreshed=0, failed=0, errors=0,
        )

    own_db = db is None
    _db = db or SessionLocal()
    try:
        result = asyncio.run(_do_refresh(_db, creator_id, model_ids, stale_days))
        with _state_lock:
            _refresh_state.update(result)
            _refresh_state["message"] = (
                f"done — {result['refreshed']} refreshed, "
                f"{result['failed']} failed, {result['errors']} errors"
            )
    except Exception as e:
        logger.exception(f"Refresh failed: {e}")
        with _state_lock:
            _refresh_state["message"] = f"error: {e}"
    finally:
        with _state_lock:
            _refresh_state["running"] = False
        if own_db:
            _db.close()
    return get_status()

"""
Library-wide storefront refresh, run off the request path.

An empty-scope POST /enrich/refresh used to re-fetch storefront detail for
every enriched model synchronously on the request thread — minutes for a big
library, HTTP timeout risk. The work runs off the request path as a background
job via the shared runner (services/job_runner.py, STUDIO-59). run_refresh is
also safe to call directly (as the scanner tests do with scan_all_roots) for
deterministic, non-threaded test coverage — it runs the job inline in that case.
"""
import asyncio
import dataclasses
import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Model
from app.services import scrapers
from app.services import secrets as secrets_service
from app.services.job_runner import JobHandle, JobState, runner
from app.services.metadata_apply import apply_scraped_to_model
from app.services.scrapers.base import ScrapedModel
from app.utils import utcnow

logger = logging.getLogger(__name__)

# Each selected match triggers a detail fetch (MMF/Cults API or Gumroad scrape).
# Bound the parallelism so we don't hammer a source or serialize the whole batch.
_FETCH_CONCURRENCY = 5

# Registry key for the (singleton) library refresh job.
_JOB_KEY = "enrich_refresh"

# Counter keys carried in the job's progress dict.
_COUNTERS = ("candidates", "refreshed", "failed", "errors")


def get_status() -> dict:
    """Legacy flat status shape kept as the public contract (router + frontend):
    ``{running, message, candidates, refreshed, failed, errors}``. Mapped out of
    the shared runner's uniform ``{state, progress, message, error}`` payload."""
    payload = runner.status(_JOB_KEY)
    progress = payload["progress"]
    status = {
        "running": payload["state"] == JobState.RUNNING.value,
        "message": payload["message"] or "idle",
    }
    for key in _COUNTERS:
        status[key] = progress.get(key, 0)
    return status


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


def _refresh_body(
    job: JobHandle,
    *,
    creator_id: Optional[int],
    model_ids: Optional[list[int]],
    stale_days: Optional[int],
    db: Optional[Session],
) -> None:
    """The refresh job body, shared by ``run_refresh`` (inline) and
    ``start_refresh`` (backgrounded via the runner). Pass ``db`` to run against
    a caller-owned session (tests); omitted, it opens and closes its own.

    Runs as a single-key job on the shared runner (services/job_runner.py). The
    runner records terminal DONE/ERROR state and the message-on-error; this body
    only pushes the running message and progress counters.
    """
    job.update(
        message="starting",
        candidates=0, refreshed=0, failed=0, errors=0,
    )
    own_db = db is None
    _db = db or SessionLocal()
    try:
        result = asyncio.run(_do_refresh(_db, creator_id, model_ids, stale_days))
        job.update(
            state=JobState.DONE,
            message=(
                f"done — {result['refreshed']} refreshed, "
                f"{result['failed']} failed, {result['errors']} errors"
            ),
            **result,
        )
    except Exception as e:
        # Mirror the message the UI showed before the runner owned terminal
        # state; re-raise so the runner records ERROR + the error string.
        job.update(message=f"error: {e}")
        raise
    finally:
        if own_db:
            _db.close()


def run_refresh(
    creator_id: Optional[int] = None,
    model_ids: Optional[list[int]] = None,
    stale_days: Optional[int] = None,
    db: Optional[Session] = None,
) -> dict:
    """Run a refresh to completion inline, updating the shared job status as it
    goes. For direct/synchronous callers (tests, the same convention
    scan_all_roots tests use) — bypasses the single-flight guard, matching
    ``JobRunner.run_inline``'s contract. Production requests go through
    ``start_refresh`` instead, which backgrounds the same body with
    single-flight protection.
    """
    runner.run_inline(
        _JOB_KEY, _refresh_body,
        creator_id=creator_id, model_ids=model_ids, stale_days=stale_days, db=db,
    )
    return get_status()


def start_refresh(
    creator_id: Optional[int] = None,
    model_ids: Optional[list[int]] = None,
    stale_days: Optional[int] = None,
) -> bool:
    """Start a background refresh with single-flight protection (STUDIO-85).

    ``runner.start`` registers the job (and takes the registry lock) before
    returning, on the calling (request) thread — closing the race where the
    router used to check ``get_status()["running"]`` and only then spawn a raw
    thread whose body registered the job later. Two concurrent requests could
    both see "not running" before either's job existed. Returns True if this
    call started the job, False if one was already running (caller surfaces a
    409).
    """
    handle = runner.start(
        _JOB_KEY, _refresh_body,
        single_flight=True,
        creator_id=creator_id, model_ids=model_ids, stale_days=stale_days, db=None,
    )
    return handle is not None

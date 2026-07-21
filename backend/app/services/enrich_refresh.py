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


FetchKey = tuple[str, Optional[str]]


def fetch_key(url: str, source_site: Optional[str], external_id: Optional[str]) -> FetchKey:
    """The dedup/lookup key for a product detail fetch.

    A URL alone identifies one product on every site except Loot Studios,
    where every miniature within a bundle shares the same bundle URL — the
    external_id is what actually distinguishes them, so it must be part of
    the key there (STUDIO-303). Other sites fold external_id out (None) so
    variants sharing a URL still collapse to a single fetch, same as before.
    """
    return (url, external_id) if source_site == "loot-studios" else (url, None)


async def fetch_unique_deep(
    keys: set[FetchKey], mmf_key: Optional[str]
) -> dict[FetchKey, Optional[ScrapedModel]]:
    """Fetch full detail for each unique (url, fetch-scoped id) key once,
    bounded-concurrently.

    Variants share a product listing, so a key is only fetched once and
    fanned out to every model that references it. A key whose fetch fails
    maps to None so callers can decide how to degrade. Shared by the
    bulk-apply router path and the refresh below so their fetch behaviour
    can't drift.
    """
    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def _one(key: FetchKey):
        url, external_id = key
        async with sem:
            try:
                return key, await scrapers.fetch_url(url, mmf_api_key=mmf_key, external_id=external_id)
            except Exception as e:
                logger.warning(f"Enrich: detail fetch failed for {url}: {e}")
                return key, None

    return dict(await asyncio.gather(*(_one(k) for k in keys)))


# STUDIO-89: process candidates in bounded pages instead of materializing the
# whole library refresh in memory / committing once at the end. Failed fetches
# in one chunk can't block later chunks, and progress advances mid-job instead
# of jumping straight to 100% at the very end.
_CHUNK_SIZE = 100


async def _do_refresh(
    db: Session,
    creator_id: Optional[int],
    model_ids: Optional[list[int]],
    stale_days: Optional[int],
    job: Optional[JobHandle] = None,
) -> dict:
    id_query = db.query(Model.id).filter(Model.source_url.isnot(None))
    if creator_id is not None:
        id_query = id_query.filter(Model.creator_id == creator_id)
    if model_ids:
        id_query = id_query.filter(Model.id.in_(model_ids))
    if stale_days is not None:
        cutoff = utcnow() - timedelta(days=stale_days)
        id_query = id_query.filter(
            or_(
                Model.source_last_fetched.is_(None),
                Model.source_last_fetched < cutoff,
            )
        )
    # Stable order so paging by offset can't skip or repeat rows across chunks.
    all_ids = [row[0] for row in id_query.order_by(Model.id).all()]
    if not all_ids:
        return {"candidates": 0, "refreshed": 0, "failed": 0, "errors": 0}

    mmf_key = secrets_service.resolve_mmf_api_key(db)
    candidates = len(all_ids)
    refreshed = failed = errors = 0

    for start in range(0, candidates, _CHUNK_SIZE):
        chunk_ids = all_ids[start:start + _CHUNK_SIZE]
        chunk_models = (
            db.query(Model).filter(Model.id.in_(chunk_ids)).order_by(Model.id).all()
        )
        unique_keys = {
            fetch_key(m.source_url, m.source_site, m.external_id)
            for m in chunk_models if m.source_url
        }
        fetched = await fetch_unique_deep(unique_keys, mmf_key)

        for model in chunk_models:
            base = fetched.get(fetch_key(model.source_url, model.source_site, model.external_id))
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
                # clear_needs_review stays False (STUDIO-306): a refresh re-fetches the same
                # kind of unreviewed deep data bulk apply does, so it can't clear the flag
                # bulk apply deliberately leaves set (#699 1.3) — no human looked at either.
                await apply_scraped_to_model(
                    db, model, scraped,
                    overwrite_title=True, thumbnail_fill_only=False,
                    reassign_creator=False, clear_needs_review=False,
                )
                refreshed += 1
            except Exception as e:
                logger.warning(f"Enrich: refresh apply failed for model {model.id} ({model.source_url}): {e}")
                errors += 1

        db.commit()
        if job is not None:
            job.update(
                message=f"refreshing — {start + len(chunk_ids)}/{candidates}",
                candidates=candidates, refreshed=refreshed, failed=failed, errors=errors,
            )

    return {
        "candidates": candidates,
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
        result = asyncio.run(_do_refresh(_db, creator_id, model_ids, stale_days, job=job))
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

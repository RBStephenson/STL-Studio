"""
Bulk enrichment endpoints — storefront scrape + fuzzy match + batch apply.
"""
import asyncio
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import Model
from app.services import scrapers, secrets
from app.services.scrapers.base import ScrapedModel
from app.services.scrapers.storefront import scrape_storefront
from app.services.matcher import match_products_to_models
from app.services.metadata_apply import apply_scraped_to_model
from app.utils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enrich", tags=["enrich"])

# Each selected match triggers a detail fetch (MMF/Cults API or Gumroad scrape).
# Bound the parallelism so we don't hammer a source or serialize the whole batch.
_FETCH_CONCURRENCY = 5


async def _fetch_unique_deep(
    urls: set[str], mmf_key: Optional[str]
) -> dict[str, Optional[ScrapedModel]]:
    """Fetch full detail for each unique product URL once, bounded-concurrently.

    Variants share a product listing, so a URL is only fetched once and fanned
    out to every model that references it. A URL whose fetch fails maps to None
    so callers can decide how to degrade. Shared by the bulk-apply and refresh
    paths so their fetch behaviour can't drift.
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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class StorefrontProduct_Out(BaseModel):
    title: str
    source_url: str
    source_site: str
    external_id: Optional[str] = None
    thumbnail_url: Optional[str] = None


class MatchResult(BaseModel):
    local_model_id: int
    local_name: str
    local_folder: str
    score: float
    confidence: str   # high | medium | low
    product: StorefrontProduct_Out


class ApplyItem(BaseModel):
    model_id: int
    source_url: str
    source_site: str
    external_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    title: Optional[str] = None


class BulkApplyRequest(BaseModel):
    items: list[ApplyItem]


class RefreshRequest(BaseModel):
    """Scope for a re-enrich. All optional; an empty body refreshes library-wide.

    ``stale_days`` keeps only models whose listing hasn't been fetched in N days
    (or never), so a periodic refresh skips recently-enriched models.
    """
    creator_id: Optional[int] = None
    model_ids: Optional[list[int]] = None
    stale_days: Optional[int] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/storefront/preview", response_model=list[StorefrontProduct_Out])
async def preview_storefront(url: str = Query(...), db: Session = Depends(get_db)):
    """Scrape a creator storefront and return the product list."""
    products = await scrape_storefront(url, mmf_api_key=secrets.resolve_mmf_api_key(db))
    if not products:
        raise HTTPException(
            status_code=422,
            detail="Could not find any products at that URL. Check the URL and try again.",
        )
    return [StorefrontProduct_Out(**p.__dict__) for p in products]


@router.get("/storefront/match", response_model=list[MatchResult])
async def match_storefront(
    url: str = Query(...),
    creator_id: int = Query(...),
    min_score: float = Query(0.20, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    """
    Scrape a storefront and fuzzy-match against local models for a creator.
    Returns ranked match candidates for user review.
    """
    products = await scrape_storefront(url, mmf_api_key=secrets.resolve_mmf_api_key(db))
    if not products:
        raise HTTPException(status_code=422, detail="No products found at that URL.")

    models = db.query(Model).filter(Model.creator_id == creator_id).all()
    if not models:
        raise HTTPException(status_code=404, detail="No local models found for this creator.")

    model_dicts = [
        {"id": m.id, "name": m.name, "title": m.title, "folder_path": m.folder_path}
        for m in models
    ]

    candidates = match_products_to_models(products, model_dicts, min_score=min_score)

    return [
        MatchResult(
            local_model_id=c.local_model_id,
            local_name=c.local_name,
            local_folder=c.local_folder,
            score=c.score,
            confidence=c.confidence,
            product=StorefrontProduct_Out(**c.product.__dict__),
        )
        for c in candidates
    ]


@router.post("/storefront/apply", response_model=dict)
async def bulk_apply(
    body: BulkApplyRequest,
    db: Session = Depends(get_db),
):
    """Apply confirmed matches to local models, fetching full detail per product.

    The match list only carries shallow fields (title, url, thumbnail). To save
    the user the per-model Find-on-Web grind, we fetch each selected product's
    detail once — via the MMF/Cults APIs or a Gumroad scrape — and write the full
    field set (description, tags, category, license, images) to every model that
    matched it. Variant siblings sharing a product URL all get the deep data, and
    a product whose detail can't be fetched falls back to the shallow fields so
    nothing regresses.
    """
    item_map = {item.model_id: item for item in body.items}
    models = db.query(Model).filter(Model.id.in_(item_map.keys())).all()

    # Fetch each *unique* product URL once (variants share a listing), bounded so
    # we don't hammer a source. MMF needs the key threaded; Cults self-resolves.
    mmf_key = secrets.resolve_mmf_api_key(db)
    unique_urls = {item.source_url for item in body.items if item.source_url}
    fetched = await _fetch_unique_deep(unique_urls, mmf_key)

    applied = deep = shallow = 0
    for model in models:
        item = item_map[model.id]
        scraped = fetched.get(item.source_url)

        if scraped is not None:
            # Keep the source identity from the match if the fetch didn't carry it.
            scraped.source_url = scraped.source_url or item.source_url
            scraped.source_site = scraped.source_site or item.source_site
            scraped.external_id = scraped.external_id or item.external_id
            deep += 1
        else:
            # Unsupported site / fetch failed — preserve the old shallow behaviour.
            scraped = ScrapedModel(
                title=item.title,
                source_url=item.source_url,
                source_site=item.source_site,
                external_id=item.external_id,
                thumbnail_url=item.thumbnail_url,
            )
            shallow += 1

        # Bulk policy: fill (don't overwrite) the title, and never replace an
        # existing local thumbnail.
        await apply_scraped_to_model(
            db, model, scraped, overwrite_title=False, thumbnail_fill_only=True
        )
        applied += 1

    db.commit()
    return {
        "ok": True,
        "applied": applied,
        "enriched_deep": deep,
        "fallback_shallow": shallow,
    }


@router.post("/refresh", response_model=dict)
async def refresh_enrich(body: RefreshRequest, db: Session = Depends(get_db)):
    """Re-fetch storefront detail for already-enriched models and overwrite.

    ``Model.source_last_fetched`` is recorded on enrich but otherwise unused —
    a listing can gain images, tags, or a new description after first enrich.
    This re-fetches detail for every model that already has a ``source_url``
    (scoped by creator, an explicit id list, or staleness — none → library-wide)
    and re-applies it.

    Unlike first-time bulk enrich, a refresh is an explicit user action on data
    that's already matched, so it overwrites aggressively: the title and
    thumbnail are replaced, not just filled. A model whose fetch fails is left
    untouched (counted in ``failed``) rather than clobbered with shallow data.
    """
    query = db.query(Model).filter(Model.source_url.isnot(None))
    if body.creator_id is not None:
        query = query.filter(Model.creator_id == body.creator_id)
    if body.model_ids:
        query = query.filter(Model.id.in_(body.model_ids))
    if body.stale_days is not None:
        cutoff = utcnow() - timedelta(days=body.stale_days)
        query = query.filter(
            or_(
                Model.source_last_fetched.is_(None),
                Model.source_last_fetched < cutoff,
            )
        )

    models = query.all()
    if not models:
        return {"ok": True, "candidates": 0, "refreshed": 0, "failed": 0}

    mmf_key = secrets.resolve_mmf_api_key(db)
    unique_urls = {m.source_url for m in models if m.source_url}
    fetched = await _fetch_unique_deep(unique_urls, mmf_key)

    refreshed = failed = 0
    for model in models:
        scraped = fetched.get(model.source_url)
        if scraped is None:
            failed += 1
            continue
        # Keep the model's existing source identity if the fetch didn't carry it.
        scraped.source_url = scraped.source_url or model.source_url
        scraped.source_site = scraped.source_site or model.source_site
        scraped.external_id = scraped.external_id or model.external_id
        await apply_scraped_to_model(
            db, model, scraped, overwrite_title=True, thumbnail_fill_only=False
        )
        refreshed += 1

    db.commit()
    return {
        "ok": True,
        "candidates": len(models),
        "refreshed": refreshed,
        "failed": failed,
    }

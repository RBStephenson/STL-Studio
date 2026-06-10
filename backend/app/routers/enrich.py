"""
Bulk enrichment endpoints — storefront scrape + fuzzy match + batch apply.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.utils import utcnow
from app.models import Model, Creator
from app.services.scrapers.storefront import scrape_storefront, StorefrontProduct
from app.services.matcher import match_products_to_models, MatchCandidate
from app.services.thumbnails import ThumbnailDownloadError, download_thumbnail
from app.services.variant_sync import propagate_source_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enrich", tags=["enrich"])

# A creator run can carry hundreds of thumbnails — bound the parallelism so we
# neither hammer the CDN nor serialize the whole batch (#208).
_THUMBNAIL_CONCURRENCY = 5


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/storefront/preview", response_model=list[StorefrontProduct_Out])
async def preview_storefront(url: str = Query(...)):
    """Scrape a creator storefront and return the product list."""
    products = await scrape_storefront(url)
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
    products = await scrape_storefront(url)
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
    """Apply confirmed matches to local model records."""
    applied = 0
    item_map = {item.model_id: item for item in body.items}
    models = db.query(Model).filter(Model.id.in_(item_map.keys())).all()

    # Download thumbnails server-side like /scrape/apply does — CDNs block
    # hot-linked <img> requests, so a stored bare URL often renders nothing
    # (#208). Only models without a local thumbnail get one (fill, never
    # overwrite); a failed download falls back to storing the URL.
    sem = asyncio.Semaphore(_THUMBNAIL_CONCURRENCY)

    async def _fetch(model_id: int, url: str):
        async with sem:
            try:
                return model_id, str(await download_thumbnail(model_id, url))
            except ThumbnailDownloadError as e:
                logger.warning(f"Bulk enrich: thumbnail download failed for model {model_id}: {e}")
                return model_id, None

    wanted = [
        (m.id, item_map[m.id].thumbnail_url)
        for m in models
        if item_map[m.id].thumbnail_url and not m.thumbnail_path
    ]
    downloaded: dict[int, str | None] = dict(
        await asyncio.gather(*(_fetch(mid, url) for mid, url in wanted))
    )

    for model in models:
        item = item_map[model.id]

        if model.id in downloaded:
            path = downloaded[model.id]
            if path:
                model.thumbnail_path = path
                model.thumbnail_url = None
            else:
                model.thumbnail_url = item.thumbnail_url
        if item.source_url:
            model.source_url = item.source_url
        if item.source_site:
            model.source_site = item.source_site
        if item.external_id:
            model.external_id = item.external_id
        if item.title and not model.title:
            model.title = item.title

        if item.source_url:
            propagate_source_url(db, model)

        model.source_last_fetched = utcnow()
        model.needs_review = False
        model.updated_at = utcnow()
        applied += 1

    db.commit()
    downloaded_ok = sum(1 for p in downloaded.values() if p)
    return {
        "ok": True,
        "applied": applied,
        "thumbnails_downloaded": downloaded_ok,
        "thumbnails_failed": len(downloaded) - downloaded_ok,
    }

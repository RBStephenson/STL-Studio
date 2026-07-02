"""
Bulk enrichment endpoints — storefront scrape + fuzzy match + batch apply.
"""
import asyncio
import dataclasses
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import Model, Creator
from app.services import scrapers, secrets
from app.services.scrapers.base import ScrapedModel
from app.services.scrapers.storefront import scrape_storefront
from app.services.matcher import match_products_to_models
from app.services.metadata_apply import apply_scraped_to_model
from app.utils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enrich", tags=["enrich"])

_MAX_CREATOR_MODELS = 5_000

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


def _collapse_candidates_to_groups(candidates, group_of: dict[int, int | None]):
    """Keep one candidate per variant group — the highest-scoring member. Ungrouped
    models (variant_group_id is None) each keep their own candidate. Order by score
    is preserved by re-sorting at the end (callers already sort by score)."""
    best_by_group: dict[int, object] = {}
    out = []
    for c in candidates:
        gid = group_of.get(c.local_model_id)
        if gid is None:
            out.append(c)
            continue
        cur = best_by_group.get(gid)
        if cur is None or c.score > cur.score:
            best_by_group[gid] = c
    out.extend(best_by_group.values())
    return sorted(out, key=lambda c: -c.score)


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

    models = db.query(Model).filter(
        Model.creator_id == creator_id,
        Model.excluded == False,  # noqa: E712
    ).all()
    model_count = len(models)
    if model_count == 0:
        raise HTTPException(status_code=404, detail="No local models found for this creator.")
    if model_count > _MAX_CREATOR_MODELS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Creator has {model_count} models, which exceeds the match limit of "
                f"{_MAX_CREATOR_MODELS}. Narrow the request or paginate by creator subset."
            ),
        )

    creator = db.get(Creator, creator_id)

    model_dicts = [
        {"id": m.id, "name": m.name, "title": m.title, "character": m.character,
         "auto_tags": m.auto_tags, "folder_path": m.folder_path}
        for m in models
    ]

    candidates = match_products_to_models(
        products, model_dicts, min_score=min_score,
        creator_name=creator.name if creator else None,
    )

    # Collapse to one candidate per variant group (#628): variants share a store
    # listing, so keep the best-scoring member's match per group and let apply
    # propagate it to siblings. Ungrouped models are unaffected.
    group_of = {m.id: m.variant_group_id for m in models}
    candidates = _collapse_candidates_to_groups(candidates, group_of)

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
    selected = db.query(Model).filter(Model.id.in_(item_map.keys())).all()

    # Propagate a group match to every variant (#628): a candidate is collapsed to
    # one member per group, so applying it must reach the siblings that share the
    # listing. Map each group to its selected item, then fold in all members.
    group_item = {}
    for m in selected:
        if m.variant_group_id is not None and m.variant_group_id not in group_item:
            group_item[m.variant_group_id] = item_map[m.id]

    models = list(selected)
    if group_item:
        have = {m.id for m in models}
        siblings = db.query(Model).filter(
            Model.variant_group_id.in_(group_item.keys()),
            Model.excluded == False,  # noqa: E712
        ).all()
        models.extend(s for s in siblings if s.id not in have)

    def _item_for(m):
        return item_map.get(m.id) or group_item[m.variant_group_id]

    # Fetch each *unique* product URL once (variants share a listing), bounded so
    # we don't hammer a source. MMF needs the key threaded; Cults self-resolves.
    mmf_key = secrets.resolve_mmf_api_key(db)
    unique_urls = {item.source_url for item in body.items if item.source_url}
    fetched = await _fetch_unique_deep(unique_urls, mmf_key)

    applied = deep = shallow = errors = 0
    for model in models:
        item = _item_for(model)
        base = fetched.get(item.source_url)

        if base is not None:
            # Fill in the source identity from the match without mutating the
            # shared ScrapedModel — it's reused across every sibling that
            # references the same product URL (#699 2.2).
            scraped = dataclasses.replace(
                base,
                source_url=base.source_url or item.source_url,
                source_site=base.source_site or item.source_site,
                external_id=base.external_id or item.external_id,
            )
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

        try:
            # Bulk policy: fill (don't overwrite) the title, never replace an existing
            # local thumbnail, never re-point creator_id (store spelling can differ
            # from the local creator being enriched — #699 1.1), and leave
            # needs_review set since no human reviewed the deep data (#699 1.3).
            await apply_scraped_to_model(
                db, model, scraped,
                overwrite_title=False, thumbnail_fill_only=True,
                reassign_creator=False, clear_needs_review=False,
            )
            applied += 1
        except Exception as e:
            logger.warning(f"Enrich: apply failed for model {model.id} ({item.source_url}): {e}")
            errors += 1

    db.commit()
    return {
        "ok": True,
        "applied": applied,
        "enriched_deep": deep,
        "fallback_shallow": shallow,
        "errors": errors,
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
        return {"ok": True, "candidates": 0, "refreshed": 0, "failed": 0, "errors": 0}

    mmf_key = secrets.resolve_mmf_api_key(db)
    unique_urls = {m.source_url for m in models if m.source_url}
    fetched = await _fetch_unique_deep(unique_urls, mmf_key)

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
        "ok": True,
        "candidates": len(models),
        "refreshed": refreshed,
        "failed": failed,
        "errors": errors,
    }

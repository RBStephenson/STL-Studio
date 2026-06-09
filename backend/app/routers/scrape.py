from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Model, Creator
from app.services import scrapers
from app.services.scanner import resolve_creator
from app.services.thumbnails import ThumbnailDownloadError, download_thumbnail
from app.utils import utcnow

router = APIRouter(prefix="/scrape", tags=["scrape"])

SUPPORTED_SITES = ["myminifactory", "gumroad", "cults3d"]


# --- Request / Response schemas ---

class ScrapePreview(BaseModel):
    """Scraped metadata returned to the frontend for user review before applying."""
    title: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None
    source_site: Optional[str] = None
    external_id: Optional[str] = None
    creator_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    image_urls: list[str] = []
    tags: list[str] = []
    category: Optional[str] = None
    license: Optional[str] = None
    like_count: Optional[int] = None
    download_count: Optional[int] = None


class SearchResultItem(BaseModel):
    title: str
    source_url: str
    source_site: str
    external_id: Optional[str] = None
    creator_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    like_count: Optional[int] = None


class ApplyRequest(BaseModel):
    """Fields from a ScrapePreview the user wants to save to the model."""
    title: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None
    source_site: Optional[str] = None
    external_id: Optional[str] = None
    creator_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    tags: list[str] = []
    category: Optional[str] = None
    license: Optional[str] = None
    like_count: Optional[int] = None
    download_count: Optional[int] = None


# --- Endpoints ---

@router.get("/fetch", response_model=ScrapePreview)
async def fetch_url(url: str = Query(..., description="Full URL to the product page")):
    """Fetch metadata from a product URL. Returns a preview for user confirmation."""
    site = scrapers.detect_site(url)
    if not site:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported site. Supported: {', '.join(SUPPORTED_SITES)}",
        )
    result = await scrapers.fetch_url(url)
    if not result:
        raise HTTPException(status_code=422, detail="Could not extract metadata from that URL.")
    return ScrapePreview(**result.__dict__)


@router.get("/search", response_model=list[SearchResultItem])
async def search_site(
    site: str = Query(..., description="myminifactory | gumroad | cults3d"),
    q: str = Query(..., description="Search query"),
    limit: int = Query(12, ge=1, le=24),
):
    """Search a site by name and return candidate results."""
    if site not in SUPPORTED_SITES:
        raise HTTPException(status_code=400, detail=f"Unsupported site: {site}")
    results = await scrapers.search_site(site, q, limit)
    return [SearchResultItem(**r.__dict__) for r in results]


@router.post("/apply/{model_id}", response_model=dict)
async def apply_metadata(
    model_id: int,
    body: ApplyRequest,
    db: Session = Depends(get_db),
):
    """Apply scraped (and user-reviewed) metadata to a model record."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if body.title:
        model.title = body.title
    if body.description:
        model.description = body.description
    if body.source_url:
        model.source_url = body.source_url
    if body.source_site:
        model.source_site = body.source_site
    if body.external_id:
        model.external_id = body.external_id
    if body.thumbnail_url:
        # Download the remote image to a local file — CDNs block hot-linking,
        # and the UI gives thumbnail_path precedence over thumbnail_url.
        try:
            model.thumbnail_path = str(
                await download_thumbnail(model.id, body.thumbnail_url)
            )
            model.thumbnail_url = None
        except ThumbnailDownloadError:
            # Fall back to the bare URL, clearing the local path so the new
            # remote image actually takes display precedence.
            model.thumbnail_url = body.thumbnail_url
            model.thumbnail_path = None
    if body.tags:
        # Merge with existing tags, dedup
        existing = set(model.tags or [])
        model.tags = list(existing | set(body.tags))
    if body.category:
        model.category = body.category
    if body.license:
        model.license = body.license
    if body.like_count is not None:
        model.rating = body.like_count  # store likes as proxy for rating
    if body.download_count is not None:
        model.download_count = body.download_count

    # Resolve or create creator
    if body.creator_name:
        model.creator_id = resolve_creator(body.creator_name, db).id

    model.source_last_fetched = utcnow()
    model.needs_review = False  # user reviewed it, clear the flag
    model.updated_at = utcnow()
    db.commit()

    return {"ok": True, "model_id": model_id}

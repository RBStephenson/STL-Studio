from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Model
from app.services import scrapers, secrets
from app.services.metadata_apply import apply_scraped_to_model
from app.services.scrapers.base import ScrapedModel

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


class GroupScrapeApply(BaseModel):
    """Set a store URL on selected variants and fetch+apply its metadata (#545)."""
    model_ids: list[int]
    url: str


class GroupScrapeResult(BaseModel):
    applied: int                       # models the URL/metadata was written to
    scraped: bool                      # whether metadata was fetched (vs URL-only)
    source_site: Optional[str] = None
    missing: list[int] = []            # requested ids that don't exist
    message: str = ""


def _host_label(url: str) -> Optional[str]:
    """Bare hostname (sans 'www.') for store URLs we don't scrape."""
    host = (urlparse(url if "//" in url else f"https://{url}").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None


def _mmf_key(db: Session) -> Optional[str]:
    """MMF API key: DB-stored secret first, then the .env fallback."""
    return secrets.resolve_mmf_api_key(db)


# --- Endpoints ---

@router.get("/fetch", response_model=ScrapePreview)
async def fetch_url(
    url: str = Query(..., description="Full URL to the product page"),
    db: Session = Depends(get_db),
):
    """Fetch metadata from a product URL. Returns a preview for user confirmation."""
    site = scrapers.detect_site(url)
    if not site:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported site. Supported: {', '.join(SUPPORTED_SITES)}",
        )
    result = await scrapers.fetch_url(url, mmf_api_key=_mmf_key(db))
    if not result:
        raise HTTPException(status_code=422, detail="Could not extract metadata from that URL.")
    return ScrapePreview(**result.__dict__)


@router.get("/search", response_model=list[SearchResultItem])
async def search_site(
    site: str = Query(..., description="myminifactory | gumroad | cults3d"),
    q: str = Query(..., description="Search query"),
    limit: int = Query(12, ge=1, le=24),
    db: Session = Depends(get_db),
):
    """Search a site by name and return candidate results."""
    if site not in SUPPORTED_SITES:
        raise HTTPException(status_code=400, detail=f"Unsupported site: {site}")
    results = await scrapers.search_site(site, q, limit, mmf_api_key=_mmf_key(db))
    return [SearchResultItem(**r.__dict__) for r in results]


async def _apply_request_to_model(db: Session, model: Model, body: ApplyRequest) -> None:
    """Apply reviewed/scraped metadata onto one model (no commit).

    Thin adapter over the shared writer: a reviewed single-model apply overwrites
    the title and always refreshes the thumbnail.
    """
    scraped = ScrapedModel(
        title=body.title,
        description=body.description,
        source_url=body.source_url,
        source_site=body.source_site,
        external_id=body.external_id,
        creator_name=body.creator_name,
        thumbnail_url=body.thumbnail_url,
        tags=body.tags or [],
        category=body.category,
        license=body.license,
        like_count=body.like_count,
        download_count=body.download_count,
    )
    await apply_scraped_to_model(
        db, model, scraped, overwrite_title=True, thumbnail_fill_only=False
    )


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

    await _apply_request_to_model(db, model, body)
    db.commit()
    return {"ok": True, "model_id": model_id}


@router.post("/apply-group", response_model=GroupScrapeResult)
async def apply_group(body: GroupScrapeApply, db: Session = Depends(get_db)):
    """Set a store page on selected variants and, when the site is scrapeable,
    fetch its metadata once and apply it to all of them (#545).

    Variants in a group share the same product page, so this scrapes once and
    fans the result out to every selected model — no per-model detail-page trip.
    When the site can't be scraped, it still records the URL + host label so the
    link isn't lost (matching the bulk set-store-page behaviour, #500)."""
    ids = list(dict.fromkeys(body.model_ids))  # de-dupe, preserve order
    if not ids:
        raise HTTPException(status_code=400, detail="model_ids must not be empty.")
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url must not be empty.")

    models = db.query(Model).filter(Model.id.in_(ids)).all()
    found = {m.id for m in models}
    missing = [i for i in ids if i not in found]
    if not models:
        raise HTTPException(status_code=404, detail="No matching models.")

    site = scrapers.detect_site(url)
    preview = await scrapers.fetch_url(url, mmf_api_key=_mmf_key(db)) if site else None

    if preview is not None:
        fields = {
            k: v for k, v in preview.__dict__.items() if k in ApplyRequest.model_fields
        }
        fields["source_url"] = url
        fields.setdefault("source_site", site)
        data = ApplyRequest(**fields)
        scraped = True
        message = f"Fetched and applied to {len(models)} variant(s)."
    else:
        # Unsupported site or scrape failed — still record the URL so it's not lost.
        data = ApplyRequest(source_url=url, source_site=site or _host_label(url))
        scraped = False
        message = (
            f"Store page set on {len(models)} variant(s); "
            "metadata couldn't be fetched for this site."
        )

    for model in models:
        await _apply_request_to_model(db, model, data)
    db.commit()

    return GroupScrapeResult(
        applied=len(models),
        scraped=scraped,
        source_site=data.source_site,
        missing=missing,
        message=message,
    )

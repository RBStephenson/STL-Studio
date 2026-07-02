"""Cults3D enrichment endpoints (#578).

GET  /cults/search?q=...           — keyword search, returns up to 20 results
GET  /cults/creation/{slug}        — fetch single creation by slug or full URL
"""
from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import CultsCreationRead, CultsCreatorRead, CultsSearchResponse
from app.services import cults as cults_client
from app.services import secrets

router = APIRouter(prefix="/cults", tags=["cults"])


def _get_creds(db: Session) -> tuple[str, str]:
    creds = secrets.get_cults_credentials(db)
    if not creds:
        raise HTTPException(
            status_code=424,
            detail="Cults3D credentials not configured. Set them in Settings → Cults.",
        )
    return creds


def _serialize(creation: cults_client.CultsCreation) -> CultsCreationRead:
    creator = None
    if creation.creator:
        creator = CultsCreatorRead(
            nick=creation.creator.nick,
            short_url=creation.creator.short_url,
            bio=creation.creator.bio,
            image_url=creation.creator.image_url,
        )
    return CultsCreationRead(
        name=creation.name,
        short_url=creation.short_url,
        illustration_image_url=creation.illustration_image_url,
        license_name=creation.license_name,
        license_code=creation.license_code,
        category=creation.category,
        published_at=creation.published_at,
        views_count=creation.views_count,
        likes_count=creation.likes_count,
        downloads_count=creation.downloads_count,
        tags=creation.tags,
        price_amount=creation.price_amount,
        price_currency=creation.price_currency,
        creator=creator,
    )


@router.get("/search", response_model=CultsSearchResponse)
def search_cults(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    username, api_key = _get_creds(db)
    try:
        results = cults_client.search_creations(username, api_key, q, limit)
    except cults_client.CultsAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except cults_client.CultsApiError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return CultsSearchResponse(results=[_serialize(r) for r in results])


@router.get("/creation/{slug:path}", response_model=CultsCreationRead)
def get_creation(slug: str, db: Session = Depends(get_db)):
    # Accept full URLs or bare slugs
    slug = cults_client.slug_from_url(slug)
    username, api_key = _get_creds(db)
    try:
        creation = cults_client.get_creation(username, api_key, slug)
    except cults_client.CultsAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except cults_client.CultsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except cults_client.CultsApiError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return _serialize(creation)

"""Color-match studio endpoint (spec §8.6, #493).

Accepts a multipart reference-image upload and returns a value-first / hue
palette of owned-paint suggestions. Suggest-only — nothing is persisted or
auto-assigned.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.painting.schemas import ColorMatchResult
from app.painting.services.colormatch import ColorMatchError, match_image, match_point

router = APIRouter()


@router.post("/colormatch", response_model=ColorMatchResult)
async def colormatch(
    file: UploadFile = File(...),
    k: int = Form(5),
    candidates_per_region: int = Form(5),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        return match_image(
            db, raw, k=k, candidates_per_region=candidates_per_region
        )
    except ColorMatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/colormatch/point", response_model=ColorMatchResult)
async def colormatch_point(
    file: UploadFile = File(...),
    x: float = Form(...),
    y: float = Form(...),
    candidates_per_region: int = Form(5),
    db: Session = Depends(get_db),
):
    """Eyedropper: suggest paints for a single point (normalized x,y) on the image."""
    raw = await file.read()
    try:
        return match_point(
            db, raw, x, y, candidates_per_region=candidates_per_region
        )
    except ColorMatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

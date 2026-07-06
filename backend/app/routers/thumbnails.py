"""Thumbnail endpoints, split out of the models router (STUDIO-58). Paths are
unchanged (prefix `/models`).

The `/group/...` batch routes are declared before the `/{model_id}/...` routes
so the literal `group` segment isn't captured as a model_id (FastAPI matches in
declaration order).
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Model
from app.schemas import (
    ThumbnailUpdate, ThumbnailFromUrl, BatchThumbnailFromUrl,
)
from app.services.thumbnails import (
    ThumbnailDownloadError, download_thumbnail, fetch_image_bytes, store_thumbnail,
)
from app.services import scanner
from app.utils import utcnow


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])


@router.patch("/{model_id}/thumbnail")
def set_thumbnail(model_id: int, body: ThumbnailUpdate, db: Session = Depends(get_db)):
    """Set thumbnail_path or thumbnail_url on a model."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    data = body.model_dump(exclude_unset=True)
    if "thumbnail_path" in data:
        model.thumbnail_path = data["thumbnail_path"] or None
    if "thumbnail_url" in data:
        model.thumbnail_url = data["thumbnail_url"] or None
    model.updated_at = utcnow()
    db.commit()
    return {"ok": True}


@router.post("/group/thumbnail/from-url")
async def batch_thumbnail_from_url(body: BatchThumbnailFromUrl, db: Session = Depends(get_db)):
    """Assign one image to every model in a group (#184).

    The image is fetched ONCE (reusing the single-model HTML/og:image follow),
    then the same bytes are written to each member's per-model thumbnail file.
    On a download failure we fall back to storing the bare URL on every member
    and clearing their local paths — the same graceful degradation the single
    from-url path uses (#285) — so the UI can still try to render directly.
    Unknown ids are skipped and reported. 409 if a scan is running, since it
    would overwrite character/grouping mid-write.

    Registered BEFORE `/{model_id}/thumbnail/from-url` so the literal `group`
    segment isn't captured as a model_id (FastAPI matches in declaration order).
    """
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")

    if not body.model_ids:
        raise HTTPException(status_code=400, detail="model_ids must not be empty.")

    requested = list(dict.fromkeys(body.model_ids))  # de-dupe, preserve order
    models = db.query(Model).filter(Model.id.in_(requested)).all()
    found = {m.id for m in models}
    missing = [mid for mid in requested if mid not in found]

    try:
        ext, data = await fetch_image_bytes(body.url)
    except ThumbnailDownloadError as e:
        # Graceful degrade: store the bare URL on every member so the UI can try
        # to render it directly, even though the server-side download failed.
        logger.info("Batch thumbnail fetch failed for %r: %s", body.url, e)
        for model in models:
            model.thumbnail_path = None
            model.thumbnail_url = body.url
            model.updated_at = utcnow()
        db.commit()
        return {
            "ok": True,
            "downloaded": False,
            "detail": str(e),
            "updated": [m.id for m in models],
            "missing": missing,
        }

    for model in models:
        path = store_thumbnail(model.id, ext, data)
        model.thumbnail_path = str(path)
        model.thumbnail_url = None
        model.updated_at = utcnow()
    db.commit()
    return {
        "ok": True,
        "downloaded": True,
        "updated": [m.id for m in models],
        "missing": missing,
    }


@router.post("/{model_id}/thumbnail/from-url")
async def set_thumbnail_from_url(
    model_id: int,
    body: ThumbnailFromUrl,
    db: Session = Depends(get_db),
):
    """Download a remote image server-side and store it as the local thumbnail.

    Remote CDNs commonly block hot-linking, so downloading to a local file is
    the reliable path. When the server-side download fails we *don't* dead-end
    with a 422 (the model is left unchanged and the picker shows nothing usable);
    instead we fall back to storing the bare URL and clearing the local path —
    the same graceful degradation PATCH /models/{id} and /scrape/apply use, so
    the UI can still try to render the image directly (#285). The response's
    `downloaded` flag lets the caller warn that it may not load if the host
    blocks embedding.
    """
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    try:
        path = await download_thumbnail(model_id, body.url)
    except ThumbnailDownloadError as e:
        logger.info("Thumbnail fetch failed for model %s (%r): %s", model_id, body.url, e)
        model.thumbnail_path = None
        model.thumbnail_url = body.url
        model.updated_at = utcnow()
        db.commit()
        return {"ok": True, "path": None, "downloaded": False, "detail": str(e)}

    model.thumbnail_path = str(path)
    model.thumbnail_url = None
    model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "path": str(path), "downloaded": True}


@router.post("/{model_id}/thumbnail/upload")
async def upload_thumbnail(
    model_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Store a captured PNG from the 3D viewer as this model's thumbnail."""
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if file.content_type not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(status_code=400, detail="Only PNG/JPEG/WebP images are accepted")

    out = store_thumbnail(model_id, ".png", await file.read())

    model.thumbnail_path = str(out)
    model.thumbnail_url = None
    model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "path": str(out)}

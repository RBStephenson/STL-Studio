"""Serve local image files and STL files from the mounted drives."""
import io
import zipfile
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from app.config import settings

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_STL_EXTENSIONS = {".stl", ".3mf", ".obj"}

# Directories the file server is allowed to read from
def _allowed_roots() -> list[Path]:
    roots = [Path(r) for r in settings.stl_root_list]
    if settings.orynt3d_thumbnail_cache:
        roots.append(Path(settings.orynt3d_thumbnail_cache))
    return roots


def _is_safe_path(p: Path) -> bool:
    resolved = p.resolve()
    return any(
        resolved.is_relative_to(root.resolve())
        for root in _allowed_roots()
    )


@router.get("/image")
def serve_image(path: str):
    p = Path(path)
    if p.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not an image file")
    if not _is_safe_path(p):
        raise HTTPException(status_code=403, detail="Path not allowed")
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(p)


@router.get("/stl")
def serve_stl(path: str):
    p = Path(path)
    if p.suffix.lower() not in ALLOWED_STL_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not an STL/3MF/OBJ file")
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(p, media_type="application/octet-stream")


@router.post("/download-zip")
def download_zip(body: dict):
    """
    Build a zip archive from a list of STL file IDs and stream it to the client.
    Body: { "file_ids": [1, 2, 3], "zip_name": "My Model 2026-05-30" }
    """
    from app.database import SessionLocal
    from app.models import STLFile

    file_ids: list[int] = body.get("file_ids", [])
    zip_name: str = body.get("zip_name", "kit-build")

    if not file_ids:
        raise HTTPException(status_code=400, detail="No file IDs provided")

    db = SessionLocal()
    try:
        files = db.query(STLFile).filter(STLFile.id.in_(file_ids)).all()
    finally:
        db.close()

    if not files:
        raise HTTPException(status_code=404, detail="No matching files found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            p = Path(f.path)
            if not _is_safe_path(p) or not p.exists():
                continue
            zf.write(p, arcname=f.filename)
    buf.seek(0)

    safe_name = "".join(c if c.isalnum() or c in " .-_()" else "_" for c in zip_name).strip()
    filename = f"{safe_name}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/model-images/{model_id}")
def list_model_images(model_id: int, db=None):
    """List all images found in a model's folder tree (for the image picker)."""
    from app.database import get_db
    from app.models import Model as ModelDB
    from sqlalchemy.orm import Session
    from fastapi import Depends

    # Inline dependency — cleaner to just import and call directly
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        model = db.query(ModelDB).filter(ModelDB.id == model_id).first()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        folder = Path(model.folder_path)
        if not folder.exists():
            return []
        images = []
        for img in sorted(folder.rglob("*")):
            if img.is_file() and img.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
                images.append({
                    "path": str(img),
                    "filename": img.name,
                    "url": f"/api/files/image?path={img}",
                })
        return images
    finally:
        db.close()

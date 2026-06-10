"""Serve local image files and STL files from the mounted drives."""
import io
import os
import string
import time
from urllib.parse import quote as _url_quote
import logging
import platform
import subprocess
import zipfile
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from app.config import settings
from app.schemas import DownloadZipRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_STL_EXTENSIONS = {".stl", ".3mf", ".obj"}

# Cache the allowlist briefly — image serving is a hot path (a grid loads dozens
# of thumbnails at once) and scan roots change rarely (only via the Settings UI).
_roots_cache: tuple[float, list[Path]] | None = None
_ROOTS_TTL = 5.0


# Directories the file server is allowed to read from
def _allowed_roots() -> list[Path]:
    global _roots_cache
    now = time.monotonic()
    if _roots_cache is not None and now - _roots_cache[0] < _ROOTS_TTL:
        return _roots_cache[1]

    roots = [Path(r) for r in settings.stl_root_list]

    # Roots added through the Settings UI live in the scan_roots table, not the
    # STL_ROOTS env var. Include them so file serving works in standalone mode
    # (where STL_ROOTS is empty and drives are added entirely through the UI).
    try:
        from app.database import SessionLocal
        from app.models import ScanRoot
        db = SessionLocal()
        try:
            for (path,) in db.query(ScanRoot.path).filter(ScanRoot.enabled == True):
                if path:
                    roots.append(Path(path))
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to load scan roots for the file-serving allowlist")

    # Also allow the app data directory so captured thumbnails (stored next to
    # the DB) can be served by the existing /files/image endpoint.
    db_url = settings.database_url
    if "sqlite:///" in db_url:
        db_file = Path(db_url.split("sqlite:///", 1)[1])
        if db_file.name != ":memory:":
            roots.append(db_file.parent)

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            unique.append(r)

    _roots_cache = (now, unique)
    return unique


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
    # Captured/downloaded thumbnails are rewritten in place at a fixed path
    # (thumbnails/{model_id}.png), so the URL never changes when the bytes do.
    # no-cache forces revalidation; FileResponse's ETag/Last-Modified keep
    # unchanged images as cheap 304s.
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


@router.get("/stl")
def serve_stl(path: str):
    p = Path(path)
    if p.suffix.lower() not in ALLOWED_STL_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not an STL/3MF/OBJ file")
    if not _is_safe_path(p):
        raise HTTPException(status_code=403, detail="Path not allowed")
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(p, media_type="application/octet-stream")


@router.post("/download-zip")
def download_zip(body: DownloadZipRequest):
    """Build a zip archive from a list of STL file IDs and stream it to the client."""
    from app.database import SessionLocal
    from app.models import STLFile

    file_ids = body.file_ids
    zip_name = body.zip_name

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


@router.post("/open-folder")
def open_folder(path: str):
    """
    Open a folder in the native file manager.
    Only works when the backend is running directly on the host (standalone mode).
    In Docker mode the container has no GUI so this returns 501.

    POST, not GET: it has a side effect, and a GET could be triggered by a
    plain <img> tag on a malicious page (#213).
    """
    p = Path(path)
    if not _is_safe_path(p):
        raise HTTPException(status_code=403, detail="Path not allowed")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Folder not found")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(str(p))
        elif system == "Darwin":
            subprocess.Popen(["open", str(p)])
        elif system == "Linux":
            subprocess.Popen(["xdg-open", str(p)])
        else:
            raise HTTPException(status_code=501, detail="Unsupported OS")
    except (AttributeError, FileNotFoundError, OSError) as e:
        raise HTTPException(status_code=501, detail=f"Cannot open folder: {e}")

    return {"ok": True}


@router.get("/browse-images")
def browse_images(path: str = ""):
    """List subdirectories and image files for the image-picker file browser.

    With no path: Windows returns drive letters; other OSes start at home.
    Otherwise returns immediate subdirs and image files inside `path`.
    Restricted to configured scan roots (same allowlist as /files/image).
    """
    system = platform.system()

    if not path:
        if system == "Windows":
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            return {
                "path": "",
                "parent": None,
                "is_drive_list": True,
                "entries": [{"name": d, "path": d, "is_dir": True, "url": None} for d in drives],
            }
        path = str(Path.home())

    p = Path(path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")
    if not _is_safe_path(p):
        raise HTTPException(status_code=403, detail="Path not allowed")

    parent = str(p.parent) if p.parent != p else None

    try:
        entries = []
        for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                entries.append({"name": entry.name, "path": str(entry), "is_dir": True, "url": None})
            elif entry.is_file() and entry.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": False,
                    "url": f"/api/files/image?path={_url_quote(str(entry), safe='')}",
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied for this folder")
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Cannot read folder: {e}")

    return {"path": str(p), "parent": parent, "is_drive_list": False, "entries": entries}


@router.get("/model-images/{model_id}")
def list_model_images(model_id: int):
    """List images for the image picker.

    Searches everything within the character/product boundary — the folder
    directly under the creator dir (e.g. 'Absolute Joker/'). Skips
    subdirectories that are themselves indexed model folders so sibling
    variants don't bleed in. Handles models nested at any depth inside
    the character folder.
    """
    from app.database import SessionLocal
    from app.models import Model as ModelDB

    db = SessionLocal()
    try:
        model = db.query(ModelDB).filter(ModelDB.id == model_id).first()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        folder = Path(model.folder_path)
        if not folder.exists():
            return []

        # Find the character boundary: the folder directly inside the creator dir.
        # Walk up until the parent is the creator dir (its parent is a scan root).
        # If the model is directly under the creator dir, boundary stays as the
        # model folder itself — don't expand to the full creator dir.
        roots = {str(r) for r in _allowed_roots()}
        boundary = folder
        current = folder.parent
        while current != current.parent:
            if str(current) in roots:
                break
            if str(current.parent) in roots:
                # current is the creator dir — stop; boundary is already correct
                break
            boundary = current
            current = current.parent

        # Load all other model folder paths under the boundary so we can skip
        # them during traversal (avoids mixing in sibling variant images).
        boundary_prefix = str(boundary)
        other_model_folders = {
            p for (p,) in db.query(ModelDB.folder_path)
            .filter(ModelDB.folder_path.like(f"{boundary_prefix}/%"),
                    ModelDB.id != model.id)
            .all() if p
        }

        seen: set[str] = set()
        images: list[dict] = []

        def _collect(path: Path):
            try:
                entries = path.iterdir()
            except PermissionError:
                return
            for entry in entries:
                if entry.is_dir():
                    if str(entry) not in other_model_folders:
                        _collect(entry)
                elif entry.is_file() and entry.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
                    key = str(entry)
                    if key not in seen:
                        seen.add(key)
                        images.append({"path": key, "filename": entry.name,
                                       "url": f"/api/files/image?path={_url_quote(str(entry), safe='')}"})

        _collect(boundary)
        return images
    finally:
        db.close()

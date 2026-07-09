"""Serve local image files and STL files from the mounted drives."""
import os
import string
import tempfile
import time
from urllib.parse import quote as _url_quote
import logging
import platform
import subprocess
import zipfile
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import Model as ModelDB, ScanRoot, STLFile
from app.schemas import DownloadZipRequest
from app.services.path_guard import assert_within_roots, is_within_roots
from app.utils import like_escape

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_STL_EXTENSIONS = {".stl", ".3mf", ".obj"}

# Cache the allowlist briefly — image serving is a hot path (a grid loads dozens
# of thumbnails at once) and scan roots change rarely (only via the Settings UI).
_roots_cache: tuple[float, list[Path]] | None = None
_ROOTS_TTL = 5.0

# Cache image-picker results per model. The picker walks the whole character
# boundary on every open, which is slow on external drives; reopening the same
# picker (or switching between sibling variants that share a boundary) is the
# common case. Short TTL keeps it fresh enough that a just-added image shows up
# on the next open without a manual reload. In-memory and per-process only.
_model_images_cache: dict[int, tuple[float, list[dict]]] = {}
_MODEL_IMAGES_TTL = 30.0
_MODEL_IMAGES_MAX = 128


def _clear_model_images_cache() -> None:
    """Drop all cached image-picker results (used by tests and after writes)."""
    _model_images_cache.clear()


def _store_in_memory(model_id: int, images: list[dict]) -> None:
    """Warm the per-process LRU (layer 1), evicting the oldest entry when full."""
    if len(_model_images_cache) >= _MODEL_IMAGES_MAX and model_id not in _model_images_cache:
        oldest = min(_model_images_cache, key=lambda k: _model_images_cache[k][0])
        _model_images_cache.pop(oldest, None)
    _model_images_cache[model_id] = (time.monotonic(), images)


def _boundary_signature(boundary: Path) -> str:
    """A cheap signature of the picker boundary, used to skip the full walk (#304).

    A single ``scandir`` round-trip: the boundary dir's own mtime plus each
    immediate child directory's mtime. A directory's mtime bumps when its direct
    children are added/removed/renamed, so this catches images dropped into the
    character folder or one level down (the common case) without enumerating the
    whole tree. Deeper nested additions only surface once the in-memory TTL
    lapses and the walk runs again — an accepted trade-off for the fast path.
    """
    try:
        parts = [str(boundary.stat().st_mtime_ns)]
    except OSError:
        return ""
    try:
        with os.scandir(boundary) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        parts.append(f"{entry.name}:{entry.stat().st_mtime_ns}")
                except OSError:
                    continue
    except OSError:
        return ""
    return "|".join(sorted(parts))


# Directories the file server is allowed to read from
def _allowed_roots() -> list[Path]:
    global _roots_cache
    now = time.monotonic()
    if _roots_cache is not None and now - _roots_cache[0] < _ROOTS_TTL:
        return _roots_cache[1]

    roots: list[Path] = []

    try:
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            for (path,) in db.query(ScanRoot.path).filter(ScanRoot.enabled == True):
                if path:
                    roots.append(Path(path))
            # Inbox/import models are deliberately never registered as a scan
            # root (scan_inbox_folder skips it on purpose), but their own
            # folder_path is a directory the scanner has already walked and
            # trusts — allow serving images from inside it so the Import
            # Preview page can show real thumbnails instead of every request
            # 403ing.
            for (path,) in db.query(ModelDB.folder_path).filter(ModelDB.is_inbox == True).distinct():
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
    return is_within_roots(p, _allowed_roots())


@router.get("/image")
def serve_image(path: str, v: str | None = None):
    if Path(path).suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not an image file")
    try:
        real = assert_within_roots(path, _allowed_roots())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path not allowed")
    p = Path(real)
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    # Captured/downloaded thumbnails are rewritten in place at a fixed path
    # (thumbnails/{model_id}.png), so the URL never changes when the bytes do.
    # Callers that pass an opaque content version (`v`, e.g. the model's
    # updated_at) get an immutable long-cache response: the URL changes whenever
    # the content does, so the browser can serve repeat loads from cache without
    # revalidating — this is what makes variant-group / Library re-renders instant
    # on slow external drives (#185). Without `v` we keep no-cache + ETag/304 for
    # raw drive images served by the picker, where no version signal exists.
    if v:
        cache_control = "public, max-age=31536000, immutable"
    else:
        cache_control = "no-cache"
    return FileResponse(p, headers={"Cache-Control": cache_control})


@router.get("/stl")
def serve_stl(path: str, v: str | None = None):
    """Serve an STL/3MF/OBJ file, preferring a local cached copy (#304).

    Files live on external drives; ``cached_stl`` copies to fast local storage on
    first access so repeat opens don't re-read the drive. When a version token
    ``v`` is supplied (the frontend passes the file size) the response is marked
    immutable so the browser caches it and skips the re-fetch on remount; without
    ``v`` the response is left uncached so a replaced same-path file is re-read.
    """
    from app.services.stl_cache import cached_stl

    if Path(path).suffix.lower() not in ALLOWED_STL_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not an STL/3MF/OBJ file")
    try:
        real = assert_within_roots(path, _allowed_roots())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path not allowed")
    p = Path(real)
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    served = cached_stl(p)
    cache_control = "public, max-age=31536000, immutable" if v else "no-cache"
    return FileResponse(served, media_type="application/octet-stream",
                        headers={"Cache-Control": cache_control})


@router.get("/document")
def serve_document(path: str):
    """Serve a non-STL, non-image pack file (PDF, TXT, ZIP, etc.) as a download.

    Restricted to configured scan roots — the same allowlist as /files/image.
    Rejects STL and image extensions (those have dedicated endpoints). The
    filename is taken from the path and set in the Content-Disposition header
    so the browser downloads rather than navigating."""
    _ext = Path(path).suffix.lower()
    if _ext in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Use /files/image for image files")
    if _ext in ALLOWED_STL_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Use /files/stl for STL files")

    try:
        real = assert_within_roots(path, _allowed_roots())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path not allowed")
    resolved = Path(real)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Strip characters that would break the Content-Disposition header value.
    safe_name = resolved.name.replace('"', "").replace("\n", "").replace("\r", "")
    return FileResponse(
        resolved,
        filename=safe_name,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Cache-Control": "no-cache",
        },
    )


def _unique_arcname(filename: str, used: set[str]) -> str:
    """Return an archive name for `filename` that doesn't collide with one already
    used in this zip. A model can hold several files with the same basename in
    different sub-folders (e.g. `base.stl` under Body/ and Base/); writing them all
    as `base.stl` silently drops all but the last on extraction (#219). On a clash,
    suffix `name (2).stl`, `name (3).stl`, … keeping the extension intact."""
    if filename not in used:
        used.add(filename)
        return filename
    stem, ext = os.path.splitext(filename)
    i = 2
    while f"{stem} ({i}){ext}" in used:
        i += 1
    arc = f"{stem} ({i}){ext}"
    used.add(arc)
    return arc


@router.post("/download-zip")
def download_zip(
    body: DownloadZipRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Build a zip archive from a list of STL file IDs and stream it to the client.

    The archive is written to a temp file (not an in-memory BytesIO) so a
    multi-GB kit doesn't have to fit in RAM (#219); the temp file is removed after
    the response is sent, the same way /database/backup cleans up its snapshot.
    """
    file_ids = body.file_ids
    zip_name = body.zip_name

    if not file_ids:
        raise HTTPException(status_code=400, detail="No file IDs provided")

    files = db.query(STLFile).filter(STLFile.id.in_(file_ids)).all()

    if not files:
        raise HTTPException(status_code=404, detail="No matching files found")

    fd, tmp_name = tempfile.mkstemp(prefix="stl_zip_", suffix=".zip")
    os.close(fd)
    tmp = Path(tmp_name)

    used_arcnames: set[str] = set()
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                try:
                    _real = assert_within_roots(f.path, _allowed_roots())
                except ValueError:
                    continue
                p = Path(_real)
                if not p.exists():
                    continue
                zf.write(p, arcname=_unique_arcname(f.filename, used_arcnames))
    except Exception:
        _safe_unlink(tmp)
        raise

    safe_name = "".join(c if c.isalnum() or c in " .-_()" else "_" for c in zip_name).strip()
    filename = f"{safe_name}.zip"

    background_tasks.add_task(_safe_unlink, tmp)
    # Set Content-Disposition explicitly (rather than FileResponse's filename=,
    # which percent-encodes spaces into a filename*=utf-8'' form) to keep the
    # plain `filename="…"` header the client and tests expect.
    return FileResponse(
        tmp,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _safe_unlink(path: Path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@router.post("/open-folder")
def open_folder(path: str):
    """
    Open a folder in the native file manager.
    Only works when the backend is running directly on the host (standalone mode).
    In Docker mode the container has no GUI so this returns 501.

    POST, not GET: it has a side effect, and a GET could be triggered by a
    plain <img> tag on a malicious page (#213).
    """
    try:
        real = assert_within_roots(path, _allowed_roots())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path not allowed")
    p = Path(real)
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
    if not _is_safe_path(p):
        raise HTTPException(status_code=403, detail="Path not allowed")
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

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
def list_model_images(model_id: int, refresh: bool = False, db: Session = Depends(get_db)):
    """List images for the image picker.

    Searches everything within the character/product boundary — the folder
    directly under the creator dir (e.g. 'Absolute Joker/'). Skips
    subdirectories that are themselves indexed model folders so sibling
    variants don't bleed in. Handles models nested at any depth inside
    the character folder.

    ``refresh=True`` forces a full re-walk, bypassing both the in-memory cache
    and the persisted manifest signature — the user's escape hatch when an image
    added deep in a nested subtree didn't bump the shallow boundary signature.
    """
    now = time.monotonic()
    if not refresh:
        cached = _model_images_cache.get(model_id)
        if cached is not None and now - cached[0] < _MODEL_IMAGES_TTL:
            return cached[1]

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

    # Layer 2: persisted manifest. If the boundary signature matches what the
    # stored manifest was built from, return it without a full directory walk
    # — this fast path survives restarts (unlike the in-memory cache). The
    # signature is one scandir; the walk it replaces is the whole subtree.
    sig = _boundary_signature(boundary)
    if not refresh and sig and model.image_manifest is not None and model.image_manifest_sig == sig:
        images = model.image_manifest
        _store_in_memory(model_id, images)
        return images

    # Load all other model folder paths under the boundary so we can skip
    # them during traversal (avoids mixing in sibling variant images).
    boundary_prefix = str(boundary)
    other_model_folders = {
        p for (p,) in db.query(ModelDB.folder_path)
        .filter(ModelDB.folder_path.like(f"{like_escape(boundary_prefix)}/%", escape="\\"),
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

    # Persist the freshly-walked manifest against the signature we walked at,
    # so a later open (even after a restart) can skip the walk entirely.
    if sig and (model.image_manifest != images or model.image_manifest_sig != sig):
        model.image_manifest = images
        model.image_manifest_sig = sig
        db.commit()

    _store_in_memory(model_id, images)
    return images


@router.get("/drive-status")
def drive_status(db: Session = Depends(get_db)):
    """Report availability of each configured scan root.

    External drives can be unmounted or disconnected, in which case scans and
    file serving silently return nothing. This lets the UI surface a clear
    "drive unavailable" warning instead of an empty library.
    """
    rows = db.query(ScanRoot.path, ScanRoot.enabled).all()

    roots: list[dict] = []
    for path, enabled in rows:
        if not path:
            continue
        p = Path(path)
        available = p.is_dir()
        roots.append({
            "path": path,
            "enabled": bool(enabled),
            "available": available,
        })

    return {
        "roots": roots,
        "all_available": all(r["available"] for r in roots if r["enabled"]),
    }

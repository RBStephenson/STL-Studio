import os
import platform
import string
from pathlib import Path

import threading
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ScanRoot, Creator
from app.schemas import ScanStatus, ScanRootCreate, ScanRootUpdate, InboxScanRequest
from app.services import scanner, layout
from app.config import settings

router = APIRouter(prefix="/scan", tags=["scan"])


def _configured_roots(db: Session) -> list[Path]:
    """Return all enabled scan roots from the DB plus the env config."""
    from app.models import ScanRoot as ScanRootModel
    db_roots = [Path(r) for (r,) in db.query(ScanRootModel.path).filter(ScanRootModel.enabled == True)]
    env_roots = [Path(r) for r in settings.stl_root_list]
    seen: set[Path] = set()
    result = []
    for r in db_roots + env_roots:
        if r not in seen:
            seen.add(r)
            result.append(r)
    return result


def _is_under_configured_root(p: Path, roots: list[Path]) -> bool:
    return any(p.is_relative_to(root) for root in roots)


# Safe top-level locations the first-run folder picker may browse before any
# scan root is configured. Without this, an empty root list left /scan/browse
# able to list the entire host/container filesystem (#41).
_UNIX_BROWSE_DIRS = ("/mnt", "/media", "/Volumes", "/data")


def _bootstrap_roots() -> list[Path]:
    """Allowlist for /scan/browse when no scan roots are configured yet.

    Windows: the existing drive roots. Unix/Docker: the user's home directory
    plus any common mount/data directories that exist (where STL drives and the
    app volume live).
    """
    if platform.system() == "Windows":
        return [Path(f"{d}:\\") for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    roots = [Path.home()]
    roots += [Path(d) for d in _UNIX_BROWSE_DIRS if os.path.isdir(d)]
    return roots


@router.get("/browse")
def browse_dirs(path: str = "", mode: str = "", db: Session = Depends(get_db)):
    """List sub-directories for the Settings folder picker.

    With no path: Windows returns available drive letters; other OSes start at
    the user's home directory. Otherwise returns the immediate sub-folders of
    `path`, plus its parent (for an "up" button). Directories only — never files.

    Browsing is always restricted to an allowlist: the configured scan roots
    once any exist, otherwise a small bootstrap set of safe top-level locations
    (drives on Windows; home + common mount/data dirs on Unix). This keeps the
    first-run picker from exposing the rest of the container/host filesystem.
    """
    system = platform.system()
    roots = _configured_roots(db)
    # Inbox mode: browse outside configured scan roots so the user can pick an
    # arbitrary import folder. Uses the same bootstrap allowlist as the first-run
    # picker, which is already considered a safe exposure boundary.
    allowlist = _bootstrap_roots() if mode == "inbox" else (roots or _bootstrap_roots())

    # Top level — drive list on Windows, home dir elsewhere.
    if not path:
        if system == "Windows":
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            return {
                "path": "",
                "parent": None,
                "is_drive_list": True,
                "entries": [{"name": d, "path": d} for d in drives],
            }
        path = str(Path.home())

    p = Path(path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    # Restrict browsing to the allowlist (configured roots, or bootstrap roots).
    if not _is_under_configured_root(p, allowlist):
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders")

    try:
        entries = sorted(
            (
                {"name": d.name, "path": str(d)}
                for d in p.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ),
            key=lambda e: e["name"].lower(),
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied for this folder")
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Cannot read folder: {e}")

    # Determine parent for the "up" control. At a filesystem/drive root, going up
    # returns to the drive list (Windows) or stays put (Unix root).
    if p.parent == p:
        parent = "" if system == "Windows" else None
    else:
        parent = str(p.parent)

    return {"path": str(p), "parent": parent, "is_drive_list": False, "entries": entries}


@router.post("/start", response_model=ScanStatus)
def start_scan(db: Session = Depends(get_db)):
    status = scanner.get_status()
    if status["running"]:
        raise HTTPException(status_code=409, detail="Scan already running")

    # Ensure scan roots exist in db from env config
    _sync_roots_from_config(db)

    thread = threading.Thread(target=scanner.scan_all_roots, daemon=True)
    thread.start()

    return ScanStatus(running=True, message="scan started")


@router.post("/creator/{creator_id}", response_model=ScanStatus)
def start_creator_scan(creator_id: int, db: Session = Depends(get_db)):
    """Rescan a single creator's folder(s), in addition to the full scan."""
    status = scanner.get_status()
    if status["running"]:
        raise HTTPException(status_code=409, detail="Scan already running")

    creator = db.query(Creator).filter(Creator.id == creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    thread = threading.Thread(
        target=scanner.scan_creator, args=(creator_id,), daemon=True
    )
    thread.start()

    return ScanStatus(running=True, message=f"scanning {creator.name}")


@router.post("/cancel")
def cancel_scan():
    status = scanner.get_status()
    if not status["running"]:
        raise HTTPException(status_code=409, detail="No scan running")
    scanner.request_cancel()
    return {"ok": True}


@router.post("/inbox", response_model=ScanStatus)
def start_inbox_scan(body: InboxScanRequest, db: Session = Depends(get_db)):
    """Index an arbitrary source folder as inbox models without adding it as a scan root.

    The folder must exist and must not already be a configured scan root (those
    are for permanent indexing; inbox is one-shot). Models are indexed with
    is_inbox=True so they can be filtered, enriched (#429), and later reorganized (#324).
    """
    status = scanner.get_status()
    if status["running"]:
        raise HTTPException(status_code=409, detail="Scan already running")

    path = body.path.strip()
    if not path:
        raise HTTPException(status_code=400, detail="Path is required")
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    configured = {Path(r.path) for r in db.query(ScanRoot).all()}
    configured |= {Path(r) for r in settings.stl_root_list}
    if p in configured:
        raise HTTPException(
            status_code=400,
            detail="This path is already a scan root — use a regular scan instead",
        )

    thread = threading.Thread(target=scanner.scan_inbox_folder, args=(path,), daemon=True)
    thread.start()
    return ScanStatus(running=True, message="importing")


@router.get("/status", response_model=ScanStatus)
def scan_status():
    s = scanner.get_status()
    return ScanStatus(**s)


@router.get("/roots")
def list_roots(db: Session = Depends(get_db)):
    return db.query(ScanRoot).all()


@router.post("/roots")
def add_root(body: ScanRootCreate, db: Session = Depends(get_db)):
    path = body.path.strip()
    if not path:
        raise HTTPException(status_code=400, detail="Path is required")
    p = Path(path)
    # Reject filesystem roots (/, C:\, D:\, etc.) — adding one would make the
    # file-serving allowlist match every path on the system.
    if p == p.parent:
        raise HTTPException(status_code=400, detail="Cannot add a filesystem root as a scan path")
    if not p.exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    existing = db.query(ScanRoot).filter(ScanRoot.path == path).first()
    if existing:
        raise HTTPException(status_code=409, detail="Root already exists")
    try:
        layout.parse_template(body.layout)
    except layout.LayoutError as e:
        raise HTTPException(status_code=400, detail=str(e))
    root = ScanRoot(path=path, enabled=True, layout=(body.layout or "{creator}").strip())
    db.add(root)
    db.commit()
    db.refresh(root)
    return root


@router.patch("/roots/{root_id}")
def update_root(root_id: int, body: ScanRootUpdate, db: Session = Depends(get_db)):
    root = db.query(ScanRoot).filter(ScanRoot.id == root_id).first()
    if not root:
        raise HTTPException(status_code=404, detail="Root not found")
    if body.layout is not None:
        try:
            layout.parse_template(body.layout)
        except layout.LayoutError as e:
            raise HTTPException(status_code=400, detail=str(e))
        root.layout = body.layout.strip() or "{creator}"
    if body.enabled is not None:
        root.enabled = body.enabled
    db.commit()
    db.refresh(root)
    return root


@router.delete("/roots/{root_id}")
def remove_root(root_id: int, db: Session = Depends(get_db)):
    root = db.query(ScanRoot).filter(ScanRoot.id == root_id).first()
    if not root:
        raise HTTPException(status_code=404, detail="Root not found")
    db.delete(root)
    db.commit()
    return {"ok": True}


def _sync_roots_from_config(db: Session):
    """Ensure each path in STL_ROOTS env var exists as a ScanRoot row."""
    for path in settings.stl_root_list:
        exists = db.query(ScanRoot).filter(ScanRoot.path == path).first()
        if not exists:
            db.add(ScanRoot(path=path, enabled=True))
    db.commit()

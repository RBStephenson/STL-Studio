import os
import platform
import string
from pathlib import Path

import threading
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ScanRoot, Creator
from app.schemas import ScanStatus
from app.services import scanner
from app.config import settings

router = APIRouter(prefix="/scan", tags=["scan"])


@router.get("/browse")
def browse_dirs(path: str = ""):
    """List sub-directories for the Settings folder picker.

    With no path: Windows returns available drive letters; other OSes start at
    the user's home directory. Otherwise returns the immediate sub-folders of
    `path`, plus its parent (for an "up" button). Directories only — never files.
    """
    system = platform.system()

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


@router.get("/status", response_model=ScanStatus)
def scan_status():
    s = scanner.get_status()
    return ScanStatus(**s)


@router.get("/roots")
def list_roots(db: Session = Depends(get_db)):
    return db.query(ScanRoot).all()


@router.post("/roots")
def add_root(body: dict, db: Session = Depends(get_db)):
    path = (body.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="Path is required")
    existing = db.query(ScanRoot).filter(ScanRoot.path == path).first()
    if existing:
        raise HTTPException(status_code=409, detail="Root already exists")
    root = ScanRoot(path=path, enabled=True)
    db.add(root)
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

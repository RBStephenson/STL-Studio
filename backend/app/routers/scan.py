import threading
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ScanRoot, Creator
from app.schemas import ScanStatus
from app.services import scanner
from app.config import settings

router = APIRouter(prefix="/scan", tags=["scan"])


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

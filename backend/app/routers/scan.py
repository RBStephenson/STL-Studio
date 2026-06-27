import os
import platform
import string
from pathlib import Path

import threading
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ScanRoot, Creator
from app.schemas import (
    ScanStatus, ScanRootCreate, ScanRootUpdate, InboxScanRequest, LibraryRead,
)
from app.services import scanner, layout
from app.config import settings

router = APIRouter(prefix="/scan", tags=["scan"])


def _configured_roots(db: Session) -> list[Path]:
    """Return all enabled scan roots from the DB."""
    from app.models import ScanRoot as ScanRootModel
    return [Path(r) for (r,) in db.query(ScanRootModel.path).filter(ScanRootModel.enabled == True)]


def _is_under_configured_root(p: Path, roots: list[Path]) -> bool:
    """True if ``p`` is lexically inside any allowed root.

    Uses normpath (pure string math, no filesystem access) so the containment
    check itself never touches disk — `..` segments are collapsed lexically,
    which is sufficient for a local single-user app's allowlist guard.
    """
    np = os.path.normpath(str(p))
    for root in roots:
        nr = os.path.normpath(str(root))
        # Drive roots (e.g. "F:\\") normpath to a value that already ends in a
        # separator; appending os.sep would double it and break the prefix match
        # for every child. Strip any trailing separator before joining.
        if np == nr or np.startswith(nr.rstrip(os.sep) + os.sep):
            return True
    return False


# Safe top-level locations the first-run folder picker may browse before any
# scan root is configured. Without this, an empty root list left /scan/browse
# able to list the entire host/container filesystem (#41).
_UNIX_BROWSE_DIRS = ("/mnt", "/media", "/Volumes", "/data", "/import")


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
    #
    # Default (Settings "Add Folder") mode unions the configured roots with the
    # bootstrap set. The picker's job is to add a NEW root anywhere, so it must
    # always be able to reach the bootstrap drives — narrowing to just the
    # configured roots once any existed blocked navigating to any other drive or
    # folder to add. The exposure boundary stays the bootstrap set (drives on
    # Windows, home + mounts on Unix), same as the first-run picker.
    allowlist = _bootstrap_roots() if mode == "inbox" else (roots + _bootstrap_roots())

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

    # Normalize lexically (collapses '..' without touching disk) before any
    # filesystem access.
    p = Path(os.path.normpath(path))

    # Allowlist guard runs BEFORE any filesystem access: never stat or list a
    # path outside the configured/bootstrap roots. Confining first keeps an
    # out-of-allowlist path from ever reaching the filesystem calls below.
    if not _is_under_configured_root(p, allowlist):
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders")

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
    # Inbox import intentionally accepts an arbitrary folder the user selects
    # (it is not confined to a scan root — that is the point of the feature).
    # This is a local, single-user desktop app: the user is choosing their own
    # folder. realpath resolves symlinks and collapses '..' segments; CodeQL
    # recognises it as a taint sanitizer (normpath was not recognised).
    norm = os.path.realpath(path)
    p = Path(norm)
    if not p.exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    # Reject exact match, parent overlap, AND child overlap with any configured
    # scan root. Lexical normpath comparison only (no filesystem access).
    configured_norm: list[str] = [
        os.path.normpath(r.path) for r in db.query(ScanRoot).all() if r.path
    ]
    for root in configured_norm:
        if (
            norm == root
            or norm.startswith(root + os.sep)
            or root.startswith(norm + os.sep)
        ):
            raise HTTPException(
                status_code=400,
                detail="Path overlaps with a configured scan root — use a regular scan or choose a path outside the library",
            )

    # Acquire write lock synchronously so the HTTP response is authoritative:
    # 200 means the scan is actually starting, not queued behind a lock the
    # thread might silently fail to acquire.
    if not scanner.prepare_inbox_scan():
        raise HTTPException(
            status_code=409,
            detail="Library is busy — reorganize in progress, try again shortly",
        )

    # Pass the canonical, validated path across the worker boundary (not the raw
    # request value). If the thread fails to launch, release the lock and reset
    # state so a failed start doesn't wedge the library at running-forever.
    try:
        thread = threading.Thread(
            target=scanner.scan_inbox_folder,
            args=(str(p),),
            kwargs={"_lock_already_held": True},
            daemon=True,
        )
        thread.start()
    except Exception as e:
        scanner.abort_inbox_scan()
        raise HTTPException(status_code=500, detail=f"Failed to start import: {e}")

    return ScanStatus(running=True, message="importing")


@router.get("/status", response_model=ScanStatus)
def scan_status():
    s = scanner.get_status()
    return ScanStatus(**s)


@router.get("/roots")
def list_roots(db: Session = Depends(get_db)):
    return db.query(ScanRoot).all()


@router.get("/libraries", response_model=list[LibraryRead])
def list_libraries(db: Session = Depends(get_db)):
    """Writable scan roots usable as import destinations (#450) — feeds the
    Library dropdown. `write_enabled` reflects the deployment-level flag so the
    UI can grey out destinations on a read-only deploy (the disk probe still
    runs at apply time)."""
    roots = db.query(ScanRoot).filter(ScanRoot.is_writable == True).all()  # noqa: E712
    return [
        LibraryRead(
            id=r.id,
            path=r.path,
            name=r.name or Path(r.path).name,
            is_writable=r.is_writable,
            write_enabled=settings.reorganize_write_enabled,
        )
        for r in roots
    ]


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
    root = ScanRoot(
        path=path,
        enabled=True,
        layout=(body.layout or "{creator}").strip(),
        name=(body.name or "").strip() or p.name,
        is_writable=body.is_writable,
    )
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
    if body.name is not None:
        root.name = body.name.strip() or Path(root.path).name
    if body.is_writable is not None:
        root.is_writable = body.is_writable
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
    """Seed scan roots from STL_ROOTS on first boot.

    Each path in settings.stl_root_list is added as an enabled ScanRoot if
    the directory exists in the container and isn't already registered.
    """
    from pathlib import Path as _Path
    added = False
    for root_path in settings.stl_root_list:
        if not _Path(root_path).is_dir():
            continue
        exists = db.query(ScanRoot).filter(ScanRoot.path == root_path).first()
        if not exists:
            db.add(ScanRoot(path=root_path, enabled=True))
            added = True
    if added:
        db.commit()

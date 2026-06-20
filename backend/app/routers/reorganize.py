"""
Library reorganize — Phase 1 preview endpoint (#323).

GET /reorganize/preview computes a read-only move manifest from current model
metadata, persists it as an identified artifact, and returns it. No files are
modified under any code path here; the persisted manifest exists so Phase 2
(#324) can execute the *approved* plan and verify non-drift.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ReorganizeManifest
from app.schemas import (
    ReorganizeApplyRequest,
    ReorganizeApplyResponse,
    ReorganizeEntry,
    ReorganizeFileMove,
    ReorganizePreviewRequest,
    ReorganizePreviewResponse,
    ReorganizeStats,
    ReorganizeUndoRequest,
    ReorganizeUndoResponse,
    ReorganizeUndoSkip,
)
from app.services import reorganize, reorganize_apply, write_lock
from app.services.reorganize_apply import ApplyError
from app.services.reorganize_template import ReorganizeTemplateError

router = APIRouter(prefix="/reorganize", tags=["reorganize"])


def _entry_to_schema(e: reorganize.Entry) -> ReorganizeEntry:
    return ReorganizeEntry(
        model_id=e.model_id,
        model_name=e.model_name,
        files=[
            ReorganizeFileMove(
                stl_file_id=f.stl_file_id,
                current_path=f.current_path,
                proposed_path=f.proposed_path,
                size_bytes=f.size_bytes,
                mtime_ns=f.mtime_ns,
                content_hash=f.content_hash,
                fingerprint_method=f.fingerprint_method,
                missing_file=f.missing_file,
            )
            for f in e.files
        ],
        kind=e.kind,
        proposed_dir=e.proposed_dir,
        eligible=e.eligible,
        pack_override_paths=e.pack_override_paths,
        group_override_paths=e.group_override_paths,
        collision=e.collision,
        collision_kind=e.collision_kind,
        collision_with=e.collision_with,
        unclassifiable=e.unclassifiable,
        missing_fields=e.missing_fields,
        over_length=e.over_length,
        reserved_name=e.reserved_name,
        overlaps_other=e.overlaps_other,
        spans_multiple_dirs=e.spans_multiple_dirs,
        is_symlink=e.is_symlink,
        escapes_scan_root=e.escapes_scan_root,
        missing_files_on_disk=e.missing_files_on_disk,
    )


def _compute_stats(entries: list[ReorganizeEntry]) -> ReorganizeStats:
    return ReorganizeStats(
        total=len(entries),
        eligible=sum(1 for e in entries if e.eligible),
        moves_needed=sum(1 for e in entries if e.kind in ("move", "rename", "case_rename")),
        already_in_place=sum(1 for e in entries if e.kind == "in_place"),
        collisions=sum(1 for e in entries if e.collision),
        unclassifiable=sum(1 for e in entries if e.unclassifiable),
        over_length=sum(1 for e in entries if e.over_length),
        reserved=sum(1 for e in entries if e.reserved_name),
        overlaps=sum(1 for e in entries if e.overlaps_other),
        blocked=sum(1 for e in entries if not e.eligible),
    )


def _build_and_persist(
    db: Session,
    template: str | None,
    root_id: int | None,
    overrides: dict[int, dict] | None,
) -> ReorganizePreviewResponse:
    try:
        manifest = reorganize.build_manifest(db, template, root_id, overrides)
    except ReorganizeTemplateError as e:
        raise HTTPException(status_code=400, detail=str(e))

    entries = [_entry_to_schema(e) for e in manifest.entries]
    response = ReorganizePreviewResponse(
        manifest_id=uuid.uuid4().hex,
        template=manifest.template,
        generated_at=datetime.now(timezone.utc).isoformat(),
        entries=entries,
        stats=_compute_stats(entries),
    )
    # Persist the immutable artifact so Phase 2 can execute + verify it.
    db.add(ReorganizeManifest(
        id=response.manifest_id,
        template=response.template,
        payload=response.model_dump(),
    ))
    db.commit()
    return response


@router.get("/preview", response_model=ReorganizePreviewResponse)
def preview(
    template: str | None = Query(None),
    root_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> ReorganizePreviewResponse:
    return _build_and_persist(db, template, root_id, None)


@router.post("/preview", response_model=ReorganizePreviewResponse)
def preview_with_overrides(
    body: ReorganizePreviewRequest, db: Session = Depends(get_db),
) -> ReorganizePreviewResponse:
    """Regenerate the manifest with per-entry user resolutions (Phase 2c). A
    resolved manifest is a new persisted artifact with its own fingerprint
    baseline, so apply/undo verify against exactly what the user approved."""
    overrides = {mid: ov.model_dump(exclude_none=True) for mid, ov in body.overrides.items()}
    return _build_and_persist(db, body.template, body.root_id, overrides)


@router.post("/apply", response_model=ReorganizeApplyResponse)
def apply(body: ReorganizeApplyRequest, db: Session = Depends(get_db)) -> ReorganizeApplyResponse:
    """Execute the selected entries of a previously-previewed manifest (#324, 2a).

    Refused unless the deployment opts into write mode AND each destination probes
    writable; aborts on drift; serialized against scans by the app-wide write lock.
    """
    try:
        result = reorganize_apply.apply_manifest(db, body.manifest_id, body.entry_ids)
    except write_lock.LibraryBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ApplyError as e:
        raise HTTPException(status_code=e.status, detail={"message": str(e), **e.detail})

    return ReorganizeApplyResponse(
        manifest_id=result.manifest_id,
        moved_files=result.moved_files,
        moved_models=result.moved_models,
        undo_log=result.undo_log,
    )


@router.post("/undo", response_model=ReorganizeUndoResponse)
def undo(body: ReorganizeUndoRequest, db: Session = Depends(get_db)) -> ReorganizeUndoResponse:
    """Reverse a completed apply by replaying its undo log (#324, 2b).

    Idempotent and partial-apply safe: drifted / missing / origin-occupied files
    are skipped and reported, never forced. Same write-mode guard and app-wide
    lock as apply.
    """
    try:
        result = reorganize_apply.undo_manifest(db, body.manifest_id)
    except write_lock.LibraryBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ApplyError as e:
        raise HTTPException(status_code=e.status, detail={"message": str(e), **e.detail})

    return ReorganizeUndoResponse(
        manifest_id=result.manifest_id,
        reversed_files=result.reversed_files,
        skipped=[ReorganizeUndoSkip(**s) for s in result.skipped],
    )

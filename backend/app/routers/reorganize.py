"""
Library reorganize — Phase 1 preview endpoint (#323).

GET /reorganize/preview computes a read-only move manifest from current model
metadata, persists it as an identified artifact, and returns it. No files are
modified under any code path here; the persisted manifest exists so Phase 2
(#324) can execute the *approved* plan and verify non-drift.
"""
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AppSetting, ReorganizeManifest
from app.schemas import (
    ReorganizeAiSuggestRequest,
    ReorganizeAiSuggestResponse,
    ReorganizeAiSuggestion,
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
from app.services import ai_organize, reorganize, reorganize_apply, write_lock
from app.services.reorganize_apply import ApplyError
from app.services.reorganize_template import ReorganizeTemplateError

router = APIRouter(prefix="/reorganize", tags=["reorganize"])


def _entry_to_schema(e: reorganize.Entry) -> ReorganizeEntry:
    return ReorganizeEntry(
        model_id=e.model_id,
        model_name=e.model_name,
        creator_id=e.creator_id,
        creator_name=e.creator_name,
        model_ids=e.model_ids or [e.model_id],
        package_mode=e.package_mode,
        package_name=e.package_name,
        ambiguous_package=e.ambiguous_package,
        character_source_dir=e.character_source_dir,
        character_proposed_dir=e.character_proposed_dir,
        character_package_ids=e.character_package_ids,
        character_model_ids=e.character_model_ids,
        shared_files=[
            ReorganizeFileMove(
                stl_file_id=f.stl_file_id,
                current_path=f.current_path,
                proposed_path=f.proposed_path,
                size_bytes=f.size_bytes,
                mtime_ns=f.mtime_ns,
                content_hash=f.content_hash,
                fingerprint_method=f.fingerprint_method,
                missing_file=f.missing_file,
                kind=f.kind,
            )
            for f in e.shared_files
        ],
        source_path=e.source_dir,
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
                kind=f.kind,
            )
            for f in e.files
        ],
        kind=e.kind,
        proposed_dir=e.proposed_dir,
        eligible=e.eligible,
        pack_override_paths=e.pack_override_paths,
        collision=e.collision,
        collision_kind=e.collision_kind,
        collision_with=e.collision_with,
        suggested_suffix=e.suggested_suffix,
        unclassifiable=e.unclassifiable,
        missing_fields=e.missing_fields,
        over_length=e.over_length,
        reserved_name=e.reserved_name,
        overlaps_other=e.overlaps_other,
        spans_multiple_dirs=e.spans_multiple_dirs,
        source_directories=e.source_directories,
        is_symlink=e.is_symlink,
        escapes_scan_root=e.escapes_scan_root,
        missing_files_on_disk=e.missing_files_on_disk,
        locked=e.locked,
    )


def _compute_stats(entries: list[ReorganizeEntry]) -> ReorganizeStats:
    return ReorganizeStats(
        total=len(entries),
        eligible=sum(1 for e in entries if e.eligible),
        # Only count moves that will actually happen on Apply right now — a
        # move-kind entry that's still blocked (collision, unclassifiable,
        # etc.) belongs to the Blocked/Collisions/Unclassifiable buckets, not
        # this one, or the "Moves" count would include work nothing can act
        # on yet (STUDIO-164).
        moves_needed=sum(1 for e in entries if e.kind in ("move", "rename", "case_rename") and e.eligible),
        already_in_place=sum(1 for e in entries if e.kind == "in_place"),
        collisions=sum(1 for e in entries if e.collision),
        unclassifiable=sum(1 for e in entries if e.unclassifiable),
        over_length=sum(1 for e in entries if e.over_length),
        reserved=sum(1 for e in entries if e.reserved_name),
        overlaps=sum(1 for e in entries if e.overlaps_other),
        blocked=sum(1 for e in entries if not e.eligible),
    )


def _slugify_all(db: Session) -> bool:
    """Whether every destination segment renders lowercase/hyphenated. Defaults
    to on (matches AppSettingsRead.reorganize_slugify); a stored row overrides."""
    row = db.get(AppSetting, "reorganize_slugify")
    return bool(row.value) if row is not None else True


def _slugify_filenames(db: Session) -> bool:
    """Whether each STL's own filename also renders lowercase/hyphenated
    (independent of _slugify_all, which only touches directory segments).
    Defaults off (matches AppSettingsRead.reorganize_slugify_filenames) — an
    opt-in, since it renames files on disk, not just directories."""
    row = db.get(AppSetting, "reorganize_slugify_filenames")
    return bool(row.value) if row is not None else False


def _package_mode(db: Session) -> bool:
    row = db.get(AppSetting, "reorganize_package_mode_enabled")
    return bool(row.value) if row is not None else False


def _stored_template(db: Session, template: str | None) -> str | None:
    """An explicit template wins; otherwise fall back to the persisted setting
    (build_manifest itself falls back further to the built-in default)."""
    if template:
        return template
    row = db.get(AppSetting, "reorganize_template")
    return row.value if row is not None else None


def _prune_stale_manifests(db: Session) -> None:
    """Delete previously-persisted manifest rows that were never applied
    (STUDIO-313).

    Every preview call persists a *full* manifest payload — every entry in the
    library, with per-file move lists and fingerprints — as its own row, and
    the Reorganize page re-previews the whole library on every resolved-field
    edit (collision detection is global). Left unpruned that's unbounded DB
    growth from routine use, not just an edge case.

    A manifest with no undo log on disk was never applied (or applying it
    failed before any file moved) — apply always operates on the manifest the
    UI just re-previewed, so a stale, never-applied row can no longer be
    targeted by anything and is safe to drop. A manifest whose undo log
    exists is kept indefinitely: undo reads this exact row's trusted
    ``applied_inbox_roots`` field to confine inbox restores, and the log
    itself is never deleted once written (undo doesn't clean it up), so
    there's no reliable point at which the manifest becomes safe to drop
    either. That bounds growth to "one row per file actually moved", not
    "one row per preview" — the applied case is the rare, deliberate one.
    """
    for row in db.query(ReorganizeManifest).all():
        if not reorganize_apply.undo_log_path(row.id).exists():
            db.delete(row)


def _build_and_persist(
    db: Session,
    template: str | None,
    root_id: int | None,
    overrides: dict[int, dict] | None,
    inbox_source: str | None = None,
    slugify_title: bool = False,
    slugify_all: bool | None = None,
    slugify_filenames: bool | None = None,
) -> ReorganizePreviewResponse:
    """``slugify_all=None`` (the Reorganize page's own callers) defers to the
    persisted reorganize_slugify setting. A caller with its own, independent
    naming contract — e.g. import-apply, which must not silently follow
    whatever the Reorganize page's slug preference happens to be set to —
    passes an explicit True/False instead. ``slugify_filenames`` follows the
    same None-defers-to-setting convention, backed by its own independent
    reorganize_slugify_filenames setting."""
    resolved_slugify_all = _slugify_all(db) if slugify_all is None else slugify_all
    resolved_slugify_filenames = (
        _slugify_filenames(db) if slugify_filenames is None else slugify_filenames
    )
    try:
        manifest = reorganize.build_manifest(
            db, template, root_id, overrides, inbox_source,
            slugify_title=slugify_title, slugify_all=resolved_slugify_all,
            slugify_filenames=resolved_slugify_filenames,
            preserve_packages=_package_mode(db),
        )
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
    _prune_stale_manifests(db)
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
    return _build_and_persist(db, _stored_template(db, template), root_id, None)


@router.post("/preview", response_model=ReorganizePreviewResponse)
def preview_with_overrides(
    body: ReorganizePreviewRequest, db: Session = Depends(get_db),
) -> ReorganizePreviewResponse:
    """Regenerate the manifest with per-entry user resolutions (Phase 2c). A
    resolved manifest is a new persisted artifact with its own fingerprint
    baseline, so apply/undo verify against exactly what the user approved."""
    overrides = {mid: ov.model_dump(exclude_none=True) for mid, ov in body.overrides.items()}
    return _build_and_persist(db, _stored_template(db, body.template), body.root_id, overrides)


@router.post("/apply", response_model=ReorganizeApplyResponse)
def apply(body: ReorganizeApplyRequest, db: Session = Depends(get_db)) -> ReorganizeApplyResponse:
    """Execute the selected entries of a previously-previewed manifest (#324, 2a).

    Refused unless the `reorganize_enabled` feature flag is on AND each destination
    probes writable; aborts on drift; serialized against scans by the app-wide write lock.
    """
    try:
        manifest_id = reorganize_apply._validate_manifest_id(body.manifest_id)
        result = reorganize_apply.apply_manifest(db, manifest_id, body.entry_ids)
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
    are skipped and reported, never forced. Same feature-flag guard and app-wide
    lock as apply.
    """
    try:
        manifest_id = reorganize_apply._validate_manifest_id(body.manifest_id)
        result = reorganize_apply.undo_manifest(db, manifest_id)
    except write_lock.LibraryBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ApplyError as e:
        raise HTTPException(status_code=e.status, detail={"message": str(e), **e.detail})

    return ReorganizeUndoResponse(
        manifest_id=result.manifest_id,
        reversed_files=result.reversed_files,
        skipped=[ReorganizeUndoSkip(**s) for s in result.skipped],
    )


_AI_SUGGEST_MODEL_CAP = 40  # per-request cap — matches the AI batching in ai_organize


@router.post("/ai-suggest", response_model=ReorganizeAiSuggestResponse)
def ai_suggest(body: ReorganizeAiSuggestRequest, db: Session = Depends(get_db)) -> ReorganizeAiSuggestResponse:
    """Suggest creator/character/title for entries the deterministic preview
    couldn't classify (unclassifiable or in collision), via the AI organizer's
    configured endpoint (STUDIO-186).

    Advisory only — returns suggestions, never writes anything. The caller
    resubmits accepted values through POST /reorganize/preview's ``overrides``
    (the existing Phase 2c per-model resolution path) for them to affect the
    manifest; this endpoint has no side effects of its own.

    Gated by the ``reorganize_ai_suggestions_enabled`` flag AND requires an AI
    organizer endpoint configured (same ``ai_organize_api``/``ai_organize_enabled``
    settings used by the model-level AI Organize feature) — no separate API
    config for this.
    """
    flag_row = db.get(AppSetting, "reorganize_ai_suggestions_enabled")
    if not flag_row or not bool(flag_row.value):
        raise HTTPException(status_code=400, detail="Reorganize AI suggestions are not enabled")

    manifest_row = db.get(ReorganizeManifest, body.manifest_id)
    if not manifest_row:
        raise HTTPException(status_code=404, detail="Manifest not found")

    wanted = set(body.model_ids)
    if len(wanted) > _AI_SUGGEST_MODEL_CAP:
        raise HTTPException(
            status_code=400,
            detail=f"Too many entries requested ({len(wanted)}) — max {_AI_SUGGEST_MODEL_CAP} per call",
        )

    entries_by_id = {e["model_id"]: e for e in manifest_row.payload.get("entries", [])}
    candidates: list[dict] = []
    for mid in body.model_ids:
        entry = entries_by_id.get(mid)
        if not entry or not (entry.get("unclassifiable") or entry.get("collision")):
            continue
        filenames = [
            os.path.basename(f["current_path"])
            for f in entry.get("files", [])
            if f.get("kind", "stl") == "stl" and f.get("current_path")
        ]
        candidates.append({
            "id": mid,
            "folder_name": entry.get("model_name") or "",
            "source_path": entry.get("source_path") or "",
            "filenames": filenames,
        })

    if not candidates:
        return ReorganizeAiSuggestResponse(suggestions=[], llm_status="skipped")

    from app.routers.models import _load_organize_config  # local import: avoids a router->router import cycle at module load

    try:
        org_cfg = _load_organize_config(db)
    except HTTPException as e:
        return ReorganizeAiSuggestResponse(suggestions=[], llm_status="disabled", llm_detail=str(e.detail))

    try:
        result = ai_organize.suggest_reorganize_fields(
            candidates, org_cfg.url, org_cfg.model, org_cfg.api_key,
            timeout=org_cfg.timeout, api_type=org_cfg.api_type, effort=org_cfg.effort,
            batch_size=org_cfg.batch_size, reasoning_enabled=org_cfg.reasoning_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if result.llm.status != "ok":
        return ReorganizeAiSuggestResponse(suggestions=[], llm_status=result.llm.status, llm_detail=result.llm.detail)

    suggestions = [
        ReorganizeAiSuggestion(
            model_id=s["id"], creator=s.get("creator"),
            character=s.get("character"), title=s.get("title"),
        )
        for s in result.suggestions
        if isinstance(s.get("id"), int)
    ]
    return ReorganizeAiSuggestResponse(suggestions=suggestions, llm_status="ok")

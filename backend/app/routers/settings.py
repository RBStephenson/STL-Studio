"""Server-persisted app settings (#180; the store #32 will extend).

A single key/value table backs all app-wide settings. AppSettingsRead in
schemas.py is the whitelist of known keys and their defaults: GET overlays
stored rows on it, and the PATCH schema (AppSettingsUpdate) rejects anything
outside it, so unknown keys can never be written.
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import RESTART_REQUIRED_KEYS, settings
from app.database import get_db
from app.models import AppSetting, AiApiConfig
from app.schemas import (
    AiApiConfigCreate,
    AiApiConfigRead,
    AiApiConfigUpdate,
    AiKeyUpdate,
    AiOrganizeSettingsRead,
    AiSettingsRead,
    AppSettingsRead,
    AppSettingsUpdate,
    CultsCredentialsUpdate,
    CultsSettingsRead,
    EnvReloadResult,
    FilterPreset,
    MmfSettingsRead,
)
from app.services import secrets

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

DEFAULTS: dict = AppSettingsRead().model_dump()

FILTER_PRESETS_KEY = "filter_presets"


def _merged(db: Session) -> dict:
    values = dict(DEFAULTS)
    for row in db.query(AppSetting).filter(AppSetting.key.in_(DEFAULTS)):
        values[row.key] = row.value
    return values


@router.get("", response_model=AppSettingsRead)
def get_settings(db: Session = Depends(get_db)):
    return _merged(db)


@router.patch("", response_model=AppSettingsRead)
def update_settings(body: AppSettingsUpdate, db: Session = Depends(get_db)):
    # exclude_none: a null value means "leave unchanged", and must never be
    # stored into a typed setting.
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in updates.items():
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    db.commit()
    # Apply a log-level change live so it takes effect without a restart. The
    # schema already validated the value, so apply_log_level won't raise here.
    if "log_level" in updates:
        from app.logging_config import apply_log_level
        apply_log_level(updates["log_level"])
    return _merged(db)


@router.post("/reload", response_model=EnvReloadResult)
def reload_env_settings():
    """Re-read the .env / environment config without a full restart (#140).

    Useful after editing drive mappings in .env. Values read dynamically
    (drive translations) take effect immediately; keys in RESTART_REQUIRED_KEYS
    (e.g. database_url, bound once at startup) are reported back so the user
    knows a restart is still needed for those.
    """
    try:
        settings.reload()
    except Exception:
        # A malformed .env (bad types, etc.) raises a pydantic ValidationError —
        # leave the live config untouched (reload copies fields only after a
        # fresh Settings() succeeds) and return a generic message; the raw
        # exception can reveal internal config field names, so it's logged
        # server-side only, not sent to the client (STUDIO-30).
        _log.exception("Could not reload settings")
        raise HTTPException(status_code=400, detail="Could not reload settings: invalid configuration")
    # The file-serving allowlist caches scan roots for a few seconds; drop it so
    # a newly-configured root is honored on the very next request, not after TTL.
    import app.routers.files as files_module
    files_module._roots_cache = None
    return EnvReloadResult(
        drive_mappings={"drive1": settings.stl_drive_1, "drive2": settings.stl_drive_2},
        restart_required=list(RESTART_REQUIRED_KEYS),
    )


def _stored_presets(db: Session) -> list[dict]:
    """The currently-stored preset list, straight from the DB (never a client
    snapshot). Falls back to the default empty list when the row is absent."""
    row = db.get(AppSetting, FILTER_PRESETS_KEY)
    return list(row.value) if row is not None else list(DEFAULTS[FILTER_PRESETS_KEY])


def _write_presets(db: Session, presets: list[dict]) -> None:
    row = db.get(AppSetting, FILTER_PRESETS_KEY)
    if row is None:
        db.add(AppSetting(key=FILTER_PRESETS_KEY, value=presets))
    else:
        row.value = presets
    db.commit()


@router.put("/filter-presets", response_model=AppSettingsRead)
def upsert_filter_preset(preset: FilterPreset, db: Session = Depends(get_db)):
    """Add or replace a single preset by name, atomically against the stored
    list. Single-preset semantics avoid the whole-list-replace clobber (#287)
    where a stale client snapshot could drop unrelated presets."""
    presets = [p for p in _stored_presets(db) if p.get("name") != preset.name]
    presets.append(preset.model_dump())
    _write_presets(db, presets)
    return _merged(db)


@router.delete("/filter-presets", response_model=AppSettingsRead)
def delete_filter_preset(name: str, db: Session = Depends(get_db)):
    """Remove a single preset by name, leaving the rest untouched (#287)."""
    presets = [p for p in _stored_presets(db) if p.get("name") != name]
    _write_presets(db, presets)
    return _merged(db)


# --- AI settings (#517) ---------------------------------------------------
# The API key is encrypted at rest and write-only: these endpoints report only
# whether a key is set (+ a masked hint), accept a new key, or clear it. The
# plaintext is never returned to the client.

def _ai_settings(db: Session) -> AiSettingsRead:
    hint = secrets.ai_api_key_hint(db)
    model_row = db.get(AppSetting, "ai_model")
    model = model_row.value if model_row is not None else ""
    effort_row = db.get(AppSetting, "ai_effort")
    effort = effort_row.value if effort_row is not None else "low"
    return AiSettingsRead(
        key_set=hint is not None, key_hint=hint, model=model, effort=effort
    )


@router.get("/ai", response_model=AiSettingsRead)
def get_ai_settings(db: Session = Depends(get_db)):
    return _ai_settings(db)


@router.put("/ai/key", response_model=AiSettingsRead)
def set_ai_key(body: AiKeyUpdate, db: Session = Depends(get_db)):
    secrets.set_ai_api_key(db, body.key)
    return _ai_settings(db)


@router.delete("/ai/key", response_model=AiSettingsRead)
def clear_ai_key(db: Session = Depends(get_db)):
    secrets.clear_ai_api_key(db)
    return _ai_settings(db)


# --- Cults3D settings (#578) ----------------------------------------------

def _cults_settings(db: Session) -> CultsSettingsRead:
    hint = secrets.cults_credentials_hint(db)
    return CultsSettingsRead(credentials_set=hint is not None, hint=hint)


@router.get("/cults", response_model=CultsSettingsRead)
def get_cults_settings(db: Session = Depends(get_db)):
    return _cults_settings(db)


@router.put("/cults/credentials", response_model=CultsSettingsRead)
def set_cults_credentials(body: CultsCredentialsUpdate, db: Session = Depends(get_db)):
    secrets.set_cults_credentials(db, body.username, body.api_key)
    return _cults_settings(db)


@router.delete("/cults/credentials", response_model=CultsSettingsRead)
def clear_cults_credentials(db: Session = Depends(get_db)):
    secrets.clear_cults_credentials(db)
    return _cults_settings(db)


# --- MyMiniFactory settings -----------------------------------------------
# Write-only API key, same pattern as the AI key.

def _mmf_settings(db: Session) -> MmfSettingsRead:
    hint = secrets.mmf_api_key_hint(db)
    return MmfSettingsRead(key_set=hint is not None, key_hint=hint)


@router.get("/mmf", response_model=MmfSettingsRead)
def get_mmf_settings(db: Session = Depends(get_db)):
    return _mmf_settings(db)


@router.put("/mmf/key", response_model=MmfSettingsRead)
def set_mmf_key(body: AiKeyUpdate, db: Session = Depends(get_db)):
    secrets.set_mmf_api_key(db, body.key)
    return _mmf_settings(db)


@router.delete("/mmf/key", response_model=MmfSettingsRead)
def clear_mmf_key(db: Session = Depends(get_db)):
    secrets.clear_mmf_api_key(db)
    return _mmf_settings(db)


# --- AI Organizer settings ------------------------------------------------
# OpenAI-compatible endpoint for part naming/normalization. The API key is
# write-only (same Fernet pattern); url and model are stored in app_settings.

def _organize_settings(db: Session) -> AiOrganizeSettingsRead:
    hint = secrets.organize_api_key_hint(db)
    enabled_row = db.get(AppSetting, "ai_organize_enabled")
    url_row = db.get(AppSetting, "ai_organize_url")
    model_row = db.get(AppSetting, "ai_organize_model")
    return AiOrganizeSettingsRead(
        key_set=hint is not None,
        key_hint=hint,
        enabled=bool(enabled_row.value) if enabled_row else False,
        url=url_row.value if url_row else "",
        model=model_row.value if model_row else "",
    )


@router.get("/ai-organize", response_model=AiOrganizeSettingsRead)
def get_organize_settings(db: Session = Depends(get_db)):
    return _organize_settings(db)


@router.put("/ai-organize/key", response_model=AiOrganizeSettingsRead)
def set_organize_key(body: AiKeyUpdate, db: Session = Depends(get_db)):
    secrets.set_organize_api_key(db, body.key)
    return _organize_settings(db)


@router.delete("/ai-organize/key", response_model=AiOrganizeSettingsRead)
def clear_organize_key(db: Session = Depends(get_db)):
    secrets.clear_organize_api_key(db)
    return _organize_settings(db)


@router.get("/ai-organize/models")
def get_organize_models(url: str = Query(""), db: Session = Depends(get_db)):
    """Proxy a /v1/models (or /api/tags) call to the configured AI endpoint.

    Returns {"models": [...]} so the frontend can populate a dropdown without
    making a cross-origin request from the browser.
    """
    if not url:
        url_row = db.get(AppSetting, "ai_organize_url")
        url = url_row.value if url_row else ""
    if not url:
        raise HTTPException(status_code=400, detail="No URL configured")

    api_key = secrets.get_organize_api_key(db) or ""
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    import re
    base = re.sub(r"(?i)(https?://)(?:localhost|127\.0\.0\.1)\b", r"\1host.docker.internal", url.rstrip("/"))
    try:
        r = httpx.get(f"{base}/v1/models", headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            models = sorted({m["id"] for m in data.get("data", []) if "id" in m})
            if models:
                return {"models": models}
        # Ollama also exposes /api/tags which lists local models.
        r2 = httpx.get(f"{base}/api/tags", headers=headers, timeout=10)
        if r2.status_code == 200:
            data2 = r2.json()
            models = sorted({m["name"] for m in data2.get("models", []) if "name" in m})
            return {"models": models}
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach AI endpoint: {exc}")

    raise HTTPException(status_code=502, detail="No models returned from endpoint")


# --- Named AI API configs -------------------------------------------------

def _config_to_read(db: Session, c: AiApiConfig) -> AiApiConfigRead:
    hint = secrets.ai_api_config_key_hint(db, c.id)
    return AiApiConfigRead(
        id=c.id,
        name=c.name,
        api_type=c.api_type,
        url=c.url,
        model=c.model,
        effort=c.effort,
        request_timeout=c.request_timeout,
        key_set=hint is not None,
        key_hint=hint,
    )


@router.get("/ai-apis", response_model=list[AiApiConfigRead])
def list_ai_api_configs(db: Session = Depends(get_db)):
    configs = db.query(AiApiConfig).order_by(AiApiConfig.created_at).all()
    return [_config_to_read(db, c) for c in configs]


@router.post("/ai-apis", response_model=AiApiConfigRead, status_code=201)
def create_ai_api_config(body: AiApiConfigCreate, db: Session = Depends(get_db)):
    from app.utils import utcnow as _now
    c = AiApiConfig(
        name=body.name,
        api_type=body.api_type,
        url=body.url,
        model=body.model or "",
        effort=body.effort,
        request_timeout=body.request_timeout,
        created_at=_now(),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return AiApiConfigRead(id=c.id, name=c.name, api_type=c.api_type, url=c.url,
                           model=c.model, effort=c.effort,
                           request_timeout=c.request_timeout, key_set=False, key_hint=None)


@router.patch("/ai-apis/{config_id}", response_model=AiApiConfigRead)
def update_ai_api_config(config_id: int, body: AiApiConfigUpdate, db: Session = Depends(get_db)):
    c = db.get(AiApiConfig, config_id)
    if not c:
        raise HTTPException(status_code=404, detail="Config not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return _config_to_read(db, c)


@router.delete("/ai-apis/{config_id}", status_code=204)
def delete_ai_api_config(config_id: int, db: Session = Depends(get_db)):
    c = db.get(AiApiConfig, config_id)
    if not c:
        raise HTTPException(status_code=404, detail="Config not found")
    secrets.clear_ai_api_config_key(db, config_id)
    db.delete(c)
    db.commit()


@router.post("/ai-apis/{config_id}/key", response_model=AiApiConfigRead)
def set_ai_api_config_key(config_id: int, body: AiKeyUpdate, db: Session = Depends(get_db)):
    c = db.get(AiApiConfig, config_id)
    if not c:
        raise HTTPException(status_code=404, detail="Config not found")
    secrets.set_ai_api_config_key(db, config_id, body.key)
    return _config_to_read(db, c)


@router.delete("/ai-apis/{config_id}/key", response_model=AiApiConfigRead)
def clear_ai_api_config_key_route(config_id: int, db: Session = Depends(get_db)):
    c = db.get(AiApiConfig, config_id)
    if not c:
        raise HTTPException(status_code=404, detail="Config not found")
    secrets.clear_ai_api_config_key(db, config_id)
    return _config_to_read(db, c)


@router.get("/ai-apis/{config_id}/models")
def get_ai_api_config_models(config_id: int, db: Session = Depends(get_db)):
    """Proxy a /v1/models (or /api/tags) call for an OpenAI-compatible config."""
    c = db.get(AiApiConfig, config_id)
    if not c:
        raise HTTPException(status_code=404, detail="Config not found")
    if c.api_type != "openai" or not c.url:
        return {"models": []}

    api_key = secrets.get_ai_api_config_key(db, config_id) or ""
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    import re
    base = re.sub(r"(?i)(https?://)(?:localhost|127\.0\.0\.1)\b", r"\1host.docker.internal", c.url.rstrip("/"))
    timeout = c.request_timeout
    try:
        r = httpx.get(f"{base}/v1/models", headers=headers, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            models = sorted({m["id"] for m in data.get("data", []) if "id" in m})
            if models:
                return {"models": models}
        r2 = httpx.get(f"{base}/api/tags", headers=headers, timeout=timeout)
        if r2.status_code == 200:
            data2 = r2.json()
            models = sorted({m["name"] for m in data2.get("models", []) if "name" in m})
            return {"models": models}
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach AI endpoint: {exc}")

    raise HTTPException(status_code=502, detail="No models returned from endpoint")

"""Server-persisted app settings (#180; the store #32 will extend).

A single key/value table backs all app-wide settings. AppSettingsRead in
schemas.py is the whitelist of known keys and their defaults: GET overlays
stored rows on it, and the PATCH schema (AppSettingsUpdate) rejects anything
outside it, so unknown keys can never be written.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import RESTART_REQUIRED_KEYS, settings
from app.database import get_db
from app.models import AppSetting
from app.schemas import (
    AiKeyUpdate,
    AiSettingsRead,
    AppSettingsRead,
    AppSettingsUpdate,
    Cults3DCredentialsUpdate,
    Cults3DSettingsRead,
    EnvReloadResult,
    FilterPreset,
)
from app.services import secrets

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
    for key, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    db.commit()
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
    except Exception as e:
        # A malformed .env (bad types, etc.) raises a pydantic ValidationError —
        # report it cleanly instead of a generic 500, and leave the live config
        # untouched (reload copies fields only after a fresh Settings() succeeds).
        raise HTTPException(status_code=400, detail=f"Could not reload settings: {e}")
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


# --- Cults3D settings --------------------------------------------------------
# Credentials are write-only: GET returns only whether they're configured plus
# the username and a masked key hint. Plaintext API key is never returned.

def _cults3d_settings(db: Session) -> Cults3DSettingsRead:
    username, hint = secrets.cults3d_credentials_hint(db)
    return Cults3DSettingsRead(
        configured=username is not None and hint is not None,
        username=username,
        key_hint=hint,
    )


@router.get("/cults3d", response_model=Cults3DSettingsRead)
def get_cults3d_settings(db: Session = Depends(get_db)):
    return _cults3d_settings(db)


@router.put("/cults3d/credentials", response_model=Cults3DSettingsRead)
def set_cults3d_credentials(body: Cults3DCredentialsUpdate, db: Session = Depends(get_db)):
    secrets.set_cults3d_credentials(db, body.username, body.api_key)
    return _cults3d_settings(db)


@router.delete("/cults3d/credentials", response_model=Cults3DSettingsRead)
def clear_cults3d_credentials(db: Session = Depends(get_db)):
    secrets.clear_cults3d_credentials(db)
    return _cults3d_settings(db)

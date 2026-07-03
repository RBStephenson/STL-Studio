"""Encrypted-at-rest storage for sensitive app settings (#517).

Secrets (currently just the AI provider API key) are kept out of the plaintext
`app_settings` whitelist. The ciphertext lives in its own `app_settings` row; the
Fernet key it's encrypted with lives *outside* the database — in `STL_SECRET_KEY`
if set, otherwise a generated `.secret_key` file in the database's data dir. So a
leaked DB / backup alone doesn't expose the key.

If the key material is ever lost, the stored ciphertext can't be decrypted; that
is treated as "no key set" and the user simply re-enters it.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting

# app_settings row holding the encrypted API key (NOT in the AppSettingsRead
# whitelist, so the plain settings GET never echoes it).
AI_API_KEY_ENC = "ai_api_key_enc"

# Cults3D credentials: username is stored as plaintext (it's public), API key encrypted.
CULTS3D_USERNAME_KEY = "cults3d_username"
CULTS3D_API_KEY_ENC = "cults3d_api_key_enc"

_SECRET_KEY_ENV = "STL_SECRET_KEY"
_SECRET_KEY_FILENAME = ".secret_key"

_fernet: Fernet | None = None


def _data_dir() -> Path:
    """Directory beside the SQLite database file (where the key file lives).

    Falls back to the current working directory for non-SQLite / in-memory URLs
    (e.g. the test engine), which is fine — tests set STL_SECRET_KEY or accept an
    ephemeral generated key.
    """
    url = settings.database_url
    prefix = "sqlite:///"
    if url.startswith(prefix):
        # sqlite:////data/x.db -> /data/x.db ; sqlite:///./x.db -> ./x.db
        db_path = url[len(prefix) - 1:] if url.startswith("sqlite:////") else url[len(prefix):]
        parent = Path(db_path).resolve().parent
        if parent.exists():
            return parent
    return Path.cwd()


def _load_or_create_key() -> bytes:
    env_key = os.environ.get(_SECRET_KEY_ENV)
    if env_key:
        return env_key.encode()

    key_path = _data_dir() / _SECRET_KEY_FILENAME
    if key_path.exists():
        return key_path.read_bytes()

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    # Best-effort lock-down; no-op / ignored on platforms without POSIX perms.
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def reset_cache() -> None:
    """Drop the cached Fernet — used by tests that swap the key/env."""
    global _fernet
    _fernet = None


def set_ai_api_key(db: Session, raw_key: str) -> None:
    """Encrypt and store the API key. Empty/blank input clears it instead."""
    raw_key = raw_key.strip()
    if not raw_key:
        clear_ai_api_key(db)
        return
    token = _get_fernet().encrypt(raw_key.encode()).decode()
    row = db.get(AppSetting, AI_API_KEY_ENC)
    if row is None:
        db.add(AppSetting(key=AI_API_KEY_ENC, value=token))
    else:
        row.value = token
    db.commit()


def get_ai_api_key(db: Session) -> str | None:
    """Decrypt and return the stored API key, or None if unset/undecryptable."""
    row = db.get(AppSetting, AI_API_KEY_ENC)
    if row is None or not isinstance(row.value, str):
        return None
    try:
        return _get_fernet().decrypt(row.value.encode()).decode()
    except InvalidToken:
        # Key material changed/lost — treat as "no key set".
        return None


def clear_ai_api_key(db: Session) -> None:
    row = db.get(AppSetting, AI_API_KEY_ENC)
    if row is not None:
        db.delete(row)
        db.commit()


def ai_api_key_hint(db: Session) -> str | None:
    """A masked hint for display (e.g. `sk-…wxyz`), never the full key."""
    key = get_ai_api_key(db)
    if not key:
        return None
    tail = key[-4:] if len(key) >= 4 else key
    return f"…{tail}"


# --- Cults3D credentials (#578) -------------------------------------------
# Stored as a single encrypted blob: "username\x00apikey" (null-byte separator
# so neither field can contain the delimiter accidentally).

CULTS_CREDS_ENC = "cults_credentials_enc"


def set_cults_credentials(db: Session, username: str, api_key: str) -> None:
    """Encrypt and persist Cults3D username + API key. Blank clears both."""
    username, api_key = username.strip(), api_key.strip()
    if not username or not api_key:
        clear_cults_credentials(db)
        return
    blob = f"{username}\x00{api_key}"
    token = _get_fernet().encrypt(blob.encode()).decode()
    row = db.get(AppSetting, CULTS_CREDS_ENC)
    if row is None:
        db.add(AppSetting(key=CULTS_CREDS_ENC, value=token))
    else:
        row.value = token
    db.commit()


def get_cults_credentials(db: Session) -> tuple[str, str] | None:
    """Return (username, api_key) or None if unset/undecryptable."""
    row = db.get(AppSetting, CULTS_CREDS_ENC)
    if row is None or not isinstance(row.value, str):
        return None
    try:
        blob = _get_fernet().decrypt(row.value.encode()).decode()
        username, api_key = blob.split("\x00", 1)
        return username, api_key
    except (InvalidToken, ValueError):
        return None


def clear_cults_credentials(db: Session) -> None:
    row = db.get(AppSetting, CULTS_CREDS_ENC)
    if row is not None:
        db.delete(row)
        db.commit()


def cults_credentials_hint(db: Session) -> str | None:
    """Masked hint: `rbstephenson / …wxyz`."""
    creds = get_cults_credentials(db)
    if not creds:
        return None
    username, api_key = creds
    tail = api_key[-4:] if len(api_key) >= 4 else api_key
    return f"{username} / …{tail}"


# --- MyMiniFactory API key ------------------------------------------------
# Single encrypted key (simple ?key= query auth), mirroring the AI key.

MMF_API_KEY_ENC = "mmf_api_key_enc"


def set_mmf_api_key(db: Session, raw_key: str) -> None:
    """Encrypt and store the MMF API key. Empty/blank input clears it instead."""
    raw_key = raw_key.strip()
    if not raw_key:
        clear_mmf_api_key(db)
        return
    token = _get_fernet().encrypt(raw_key.encode()).decode()
    row = db.get(AppSetting, MMF_API_KEY_ENC)
    if row is None:
        db.add(AppSetting(key=MMF_API_KEY_ENC, value=token))
    else:
        row.value = token
    db.commit()


def get_mmf_api_key(db: Session) -> str | None:
    """Decrypt and return the stored MMF API key, or None if unset/undecryptable."""
    row = db.get(AppSetting, MMF_API_KEY_ENC)
    if row is None or not isinstance(row.value, str):
        return None
    try:
        return _get_fernet().decrypt(row.value.encode()).decode()
    except InvalidToken:
        return None


def clear_mmf_api_key(db: Session) -> None:
    row = db.get(AppSetting, MMF_API_KEY_ENC)
    if row is not None:
        db.delete(row)
        db.commit()


def mmf_api_key_hint(db: Session) -> str | None:
    """A masked hint for display (e.g. `…wxyz`), never the full key."""
    key = get_mmf_api_key(db)
    if not key:
        return None
    tail = key[-4:] if len(key) >= 4 else key
    return f"…{tail}"


def resolve_mmf_api_key(db: Session) -> str | None:
    """The MMF key to use for API calls: DB-stored secret first, then the
    ``MMF_API_KEY`` env/.env fallback. None when neither is set."""
    return get_mmf_api_key(db) or (settings.mmf_api_key or None)


# --- AI Organizer API key -------------------------------------------------
# Optional — Ollama and other local servers don't require a real key, so
# empty/absent is valid; the caller passes whatever is stored (may be "").

ORGANIZE_API_KEY_ENC = "ai_organize_api_key_enc"


def set_organize_api_key(db: Session, raw_key: str) -> None:
    raw_key = raw_key.strip()
    if not raw_key:
        clear_organize_api_key(db)
        return
    token = _get_fernet().encrypt(raw_key.encode()).decode()
    row = db.get(AppSetting, ORGANIZE_API_KEY_ENC)
    if row is None:
        db.add(AppSetting(key=ORGANIZE_API_KEY_ENC, value=token))
    else:
        row.value = token
    db.commit()


def get_organize_api_key(db: Session) -> str | None:
    row = db.get(AppSetting, ORGANIZE_API_KEY_ENC)
    if row is None or not isinstance(row.value, str):
        return None
    try:
        return _get_fernet().decrypt(row.value.encode()).decode()
    except InvalidToken:
        return None


def clear_organize_api_key(db: Session) -> None:
    row = db.get(AppSetting, ORGANIZE_API_KEY_ENC)
    if row is not None:
        db.delete(row)
        db.commit()


def organize_api_key_hint(db: Session) -> str | None:
    key = get_organize_api_key(db)
    if not key:
        return None
    tail = key[-4:] if len(key) >= 4 else key
    return f"…{tail}"


# --- Named AI API config keys ---------------------------------------------
# Each config's encrypted key is stored in app_settings under a per-ID row
# so deleting a config can cleanly remove its secret without affecting others.

def _config_key_setting(config_id: int) -> str:
    return f"ai_api_key_{config_id}_enc"


def set_ai_api_config_key(db: Session, config_id: int, raw_key: str) -> None:
    raw_key = raw_key.strip()
    setting_key = _config_key_setting(config_id)
    if not raw_key:
        _clear_setting(db, setting_key)
        return
    token = _get_fernet().encrypt(raw_key.encode()).decode()
    row = db.get(AppSetting, setting_key)
    if row is None:
        db.add(AppSetting(key=setting_key, value=token))
    else:
        row.value = token
    db.commit()


def get_ai_api_config_key(db: Session, config_id: int) -> str | None:
    row = db.get(AppSetting, _config_key_setting(config_id))
    if row is None or not isinstance(row.value, str):
        return None
    try:
        return _get_fernet().decrypt(row.value.encode()).decode()
    except InvalidToken:
        return None


def clear_ai_api_config_key(db: Session, config_id: int) -> None:
    _clear_setting(db, _config_key_setting(config_id))


def ai_api_config_key_hint(db: Session, config_id: int) -> str | None:
    key = get_ai_api_config_key(db, config_id)
    if not key:
        return None
    tail = key[-4:] if len(key) >= 4 else key
    return f"…{tail}"


def _clear_setting(db: Session, setting_key: str) -> None:
    row = db.get(AppSetting, setting_key)
    if row is not None:
        db.delete(row)
        db.commit()

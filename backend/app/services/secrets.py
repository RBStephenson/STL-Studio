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


# --- Cults3D credentials ---------------------------------------------------

def set_cults3d_credentials(db: Session, username: str, api_key: str) -> None:
    """Store Cults3D username (plaintext) and encrypted API key. Blank clears."""
    username = username.strip()
    api_key = api_key.strip()
    if not username and not api_key:
        clear_cults3d_credentials(db)
        return
    # username is public info — store plaintext
    row = db.get(AppSetting, CULTS3D_USERNAME_KEY)
    if row is None:
        db.add(AppSetting(key=CULTS3D_USERNAME_KEY, value=username))
    else:
        row.value = username
    # API key is sensitive — encrypt
    if api_key:
        token = _get_fernet().encrypt(api_key.encode()).decode()
        row2 = db.get(AppSetting, CULTS3D_API_KEY_ENC)
        if row2 is None:
            db.add(AppSetting(key=CULTS3D_API_KEY_ENC, value=token))
        else:
            row2.value = token
    db.commit()


def get_cults3d_credentials(db: Session) -> tuple[str, str] | None:
    """Return (username, api_key) or None if not configured."""
    username_row = db.get(AppSetting, CULTS3D_USERNAME_KEY)
    key_row = db.get(AppSetting, CULTS3D_API_KEY_ENC)
    if username_row is None or key_row is None:
        return None
    username = username_row.value if isinstance(username_row.value, str) else None
    if not username:
        return None
    try:
        api_key = _get_fernet().decrypt(key_row.value.encode()).decode()
    except InvalidToken:
        return None
    return (username, api_key)


def clear_cults3d_credentials(db: Session) -> None:
    for key in (CULTS3D_USERNAME_KEY, CULTS3D_API_KEY_ENC):
        row = db.get(AppSetting, key)
        if row is not None:
            db.delete(row)
    db.commit()


def cults3d_credentials_hint(db: Session) -> tuple[str | None, str | None]:
    """(username, masked_api_key_hint) — safe to show in the UI."""
    username_row = db.get(AppSetting, CULTS3D_USERNAME_KEY)
    key_row = db.get(AppSetting, CULTS3D_API_KEY_ENC)
    username = username_row.value if username_row and isinstance(username_row.value, str) else None
    hint: str | None = None
    if key_row and isinstance(key_row.value, str):
        try:
            raw = _get_fernet().decrypt(key_row.value.encode()).decode()
            tail = raw[-4:] if len(raw) >= 4 else raw
            hint = f"…{tail}"
        except InvalidToken:
            pass
    return (username or None, hint)

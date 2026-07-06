"""Secrets never touch disk (see app/services/secrets.py docstring).

A prior version wrote a generated Fernet key to a `.secret_key` file, which
leaked into version control. These tests assert the replacement behavior:
no file is ever written, the ephemeral in-memory test DB stores its key as an
ordinary row instead, and a real (non-ephemeral) DATABASE_URL without
STL_SECRET_KEY set falls back to an in-memory-only key.
"""
import os

from app.services import secrets


def test_no_file_written_anywhere_under_cwd(monkeypatch, tmp_path, db):
    """Exercise the full encrypt/decrypt path with no STL_SECRET_KEY set, from
    a cwd we control, and assert nothing new appears on disk."""
    monkeypatch.delenv("STL_SECRET_KEY", raising=False)
    secrets.reset_cache()
    monkeypatch.chdir(tmp_path)

    secrets.set_ai_api_key(db, "sk-test-12345")
    assert secrets.get_ai_api_key(db) == "sk-test-12345"

    written = list(tmp_path.rglob("*"))
    assert written == [], f"expected no files written, found: {written}"
    secrets.reset_cache()


def test_ephemeral_database_stores_key_as_row_not_file(monkeypatch, tmp_path, db):
    """In the test DB (sqlite:///:memory:), the ephemeral key is persisted as
    an app_settings row so encryption is stable across reset_cache() calls."""
    monkeypatch.delenv("STL_SECRET_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    secrets.reset_cache()

    secrets.set_organize_api_key(db, "ollama-key")
    secrets.reset_cache()  # simulate a fresh process picking the DB back up
    assert secrets.get_organize_api_key(db) == "ollama-key"

    from app.models import AppSetting
    row = db.get(AppSetting, secrets._EPHEMERAL_DB_KEY_SETTING)
    assert row is not None and isinstance(row.value, str)
    assert list(tmp_path.rglob("*")) == []
    secrets.reset_cache()


def test_non_ephemeral_database_without_env_key_never_touches_disk(monkeypatch, tmp_path, db):
    """A 'real' (non-:memory:) DATABASE_URL without STL_SECRET_KEY falls back
    to an in-memory-only key — still never a file, even though it isn't the
    ephemeral-test branch."""
    monkeypatch.delenv("STL_SECRET_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    fake_db_path = tmp_path / "real.db"
    monkeypatch.setattr(secrets.settings, "database_url", f"sqlite:///{fake_db_path}")
    secrets.reset_cache()

    secrets.set_mmf_api_key(db, "mmf-key")
    assert secrets.get_mmf_api_key(db) == "mmf-key"

    assert list(tmp_path.rglob("*")) == [], "no file should exist, including the fake DB path"
    secrets.reset_cache()


def test_stl_secret_key_env_takes_precedence_over_ephemeral_db(monkeypatch, db):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("STL_SECRET_KEY", key)
    secrets.reset_cache()

    assert secrets._load_or_create_key(db) == key.encode()
    secrets.reset_cache()

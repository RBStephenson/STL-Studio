import logging

from app.logging_config import (
    LOG_FILE_NAME,
    configure_logging,
    configure_persistent_logging,
    sanitize_log_text,
)


def test_sanitize_log_text_removes_secrets_and_private_paths():
    text = sanitize_log_text(
        'Authorization: Bearer abc123 "api_key": "hidden" '
        "C:\\Users\\Brent\\secret.stl /mnt/nas/model.stl"
    )
    assert "abc123" not in text
    assert "hidden" not in text
    assert "Brent" not in text
    assert "<redacted>" in text
    assert "<local-path>" in text


def test_persistent_handler_writes_sanitized_file_and_disables(tmp_path):
    configure_logging("INFO")
    configure_persistent_logging(False, str(tmp_path))
    assert configure_persistent_logging(True, str(tmp_path)) is True

    logging.getLogger("app.test").info("token=private-value /data/private/catalog.db")
    for handler in logging.getLogger("app").handlers:
        handler.flush()

    text = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "private-value" not in text
    assert "/data/private" not in text

    assert configure_persistent_logging(False, str(tmp_path)) is False

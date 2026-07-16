"""Application logging configuration.

Uvicorn configures only its own ``uvicorn*`` loggers; the ``app.*`` hierarchy
otherwise propagates to a root logger left at WARNING with no handler, so every
``logger.info(...)`` in the app (e.g. the AI-organize request trace) was
silently discarded. We attach one stdout handler to the top-level ``app``
logger and drive its level from a single place, so the level can be changed at
runtime (via the Settings UI) without restarting the process.

Kept in its own module so both ``app.main`` (startup) and ``app.routers.settings``
(live updates) can import the helpers without a circular import.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import sys

# Standard levels, ordered least→most severe. This is the whitelist the API
# and UI offer; anything else is rejected.
LOG_LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_APP_LOGGER = "app"
_FILE_HANDLER_MARKER = "_stl_studio_file"
LOG_FILE_NAME = "backend.log"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3

_BEARER = re.compile(r"(?i)(bearer\s+)([^\s,;&\"']+)")
_NAMED_SECRET = re.compile(
    r"(?i)([\"']?(?:authorization|api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?)([^\"'\s,;&}]+)"
)
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]*")
_PRIVATE_UNIX_PATH = re.compile(r"/(?:data|mnt|media|home|Users)/[^\s,;]+")


def sanitize_log_text(value: object) -> str:
    """Remove common credentials and private filesystem locations."""
    text = str(value)
    text = _BEARER.sub(lambda match: f"{match.group(1)}<redacted>", text)
    text = _NAMED_SECRET.sub(lambda match: f"{match.group(1)}<redacted>", text)
    text = _WINDOWS_PATH.sub("<local-path>", text)
    return _PRIVATE_UNIX_PATH.sub("<local-path>", text)


class SanitizingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return sanitize_log_text(super().format(record))


def _file_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [handler for handler in logger.handlers if getattr(handler, _FILE_HANDLER_MARKER, False)]


def configure_persistent_logging(enabled: bool, log_dir: str) -> bool:
    """Enable or disable the bounded sanitized backend logfile live."""
    logger = logging.getLogger(_APP_LOGGER)
    existing = _file_handlers(logger)
    if not enabled:
        for handler in existing:
            logger.removeHandler(handler)
            handler.close()
        return False
    if existing:
        return True
    try:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / LOG_FILE_NAME,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        setattr(handler, _FILE_HANDLER_MARKER, True)
        handler.setFormatter(SanitizingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        return True
    except OSError:
        logger.exception("Could not initialize persistent diagnostics")
        return False


def _has_handler(logger: logging.Logger) -> bool:
    return any(getattr(h, "_stl_studio", False) for h in logger.handlers)


def configure_logging(level: str) -> None:
    """Attach the stdout handler to the ``app`` logger and set its level.

    Idempotent — safe to call more than once (won't double-add the handler).
    """
    app_logger = logging.getLogger(_APP_LOGGER)
    if not _has_handler(app_logger):
        # Pin to stdout so the trace lands in `docker compose logs` next to the
        # app's own output (uvicorn's default handler uses stderr).
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler._stl_studio = True  # type: ignore[attr-defined]
        app_logger.addHandler(handler)
    # Don't also propagate to any handler uvicorn installs on root (avoids
    # duplicate lines).
    app_logger.propagate = False
    apply_log_level(level)


def normalize_level(level: str) -> str:
    """Return the canonical upper-case level name, or raise ValueError."""
    normalized = (level or "").upper()
    if normalized not in LOG_LEVELS:
        raise ValueError(
            f"Invalid log level {level!r}; expected one of {', '.join(LOG_LEVELS)}"
        )
    return normalized


def apply_log_level(level: str) -> str:
    """Set the ``app`` logger level at runtime and return the normalized name.

    Takes effect immediately for every ``app.*`` logger — no restart needed.
    Raises ValueError for an unknown level.
    """
    normalized = normalize_level(level)
    logging.getLogger(_APP_LOGGER).setLevel(normalized)
    return normalized

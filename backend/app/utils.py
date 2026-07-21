from datetime import datetime, timezone


def like_escape(value: str) -> str:
    """Escape SQL LIKE metacharacters (\\, %, _) so ``value`` is matched
    literally. Callers must pass ``escape="\\\\"`` to ``.like()``/``.ilike()``.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def utcnow() -> datetime:
    """Current UTC time as a naive datetime.

    Drop-in replacement for the deprecated ``datetime.utcnow()`` — same value
    (naive, in UTC) but without the DeprecationWarning. Intentionally kept naive
    to match the existing ``DateTime`` columns, so stored values are unchanged.

    Never call ``.timestamp()`` directly on these values: on a naive datetime it
    assumes LOCAL time, skewing the epoch by the host's UTC offset. Use
    ``utc_timestamp()`` instead (STUDIO-294).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_timestamp(dt: datetime) -> float:
    """POSIX epoch seconds for a datetime that is known to hold UTC wall-clock
    time, whether naive (this codebase's storage convention — see ``utcnow``) or
    already tz-aware.

    ``dt.timestamp()`` on a naive datetime interprets it as LOCAL time, which
    shifted every comparison against ``st_mtime`` by the host's UTC offset —
    e.g. US Eastern made scan baselines look ~4-5h newer than reality, so
    folders changed within that window after a scan were wrongly treated as
    unchanged and their new files never indexed (STUDIO-294).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()

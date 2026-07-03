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
    to match the existing ``DateTime`` columns and ``.timestamp()`` comparisons,
    so stored values and behaviour are unchanged.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

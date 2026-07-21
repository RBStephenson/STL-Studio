from datetime import datetime, timedelta, timezone

from app.utils import like_escape, utc_timestamp, utcnow


class TestLikeEscape:
    def test_escapes_percent(self):
        assert like_escape("50%off") == "50\\%off"

    def test_escapes_underscore(self):
        assert like_escape("My_Guy") == "My\\_Guy"

    def test_escapes_backslash_first(self):
        # Backslash must be escaped before % and _ or a literal "\_" in the
        # input would be misread as an already-escaped wildcard.
        assert like_escape("a\\_b") == "a\\\\\\_b"

    def test_plain_string_unchanged(self):
        assert like_escape("Ordinary Name") == "Ordinary Name"


class TestUtcTimestamp:
    """utc_timestamp must read a naive datetime as UTC, not local time —
    dt.timestamp() on a naive value assumes local time, which skewed scan
    mtime comparisons by the host's UTC offset (STUDIO-294)."""

    def test_naive_utc_matches_aware_epoch(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        aware = naive.replace(tzinfo=timezone.utc)
        assert utc_timestamp(naive) == aware.timestamp()

    def test_aware_input_passthrough(self):
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert utc_timestamp(aware) == aware.timestamp()

    def test_utcnow_round_trips_to_current_epoch(self):
        import time
        assert abs(utc_timestamp(utcnow()) - time.time()) < 5

    def test_ordering_preserved(self):
        a = datetime(2026, 1, 1, 12, 0, 0)
        b = a + timedelta(seconds=1)
        assert utc_timestamp(a) < utc_timestamp(b)

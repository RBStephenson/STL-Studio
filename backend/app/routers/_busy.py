"""The library-busy gate, in one place (STUDIO-450).

Nine endpoints across five routers refuse a write while the library is being
mutated elsewhere. They used to each ask ``scanner.get_status()["running"]``,
which is scan *job state* and answers a narrower question than any of them
meant:

* it is False for the entire duration of a reorganize apply, an undo, or an
  install — none of which run as a scan job, all of which hold the write lock;
* it goes False the moment a cancelled scan reaches its terminal state, while
  the worker is still unwinding with the lock held.

So the gates that had ``library_write`` behind them (database restore/reset/
repair) passed the pre-check and were refused by the lock a moment later, and
told the user "a scan is in progress" while the app reported no scan running —
the reported bug. The gates with nothing behind them (group merge/split/patch,
grouping strategy, bulk tags, thumbnail regeneration) were worse off: they let
the write through, straight into the pass they were meant to be excluded from.

One definition now. ``write_lock.is_held()`` decides, and the scan job state is
consulted only to pick the more specific wording when it applies.

Not a substitute for ``library_write`` — the lock can be taken in the gap
between this check and the work, so callers that mutate still take the lock and
still handle :class:`LibraryBusy`. This makes the *reported* state and the
*enforced* state come from the same source; it does not make the check atomic.
"""
from fastapi import HTTPException

from app.services import scanner, write_lock

# Kept distinct from write_lock.BUSY_DETAIL because it is the one holder we can
# name exactly, and the only one with an action the user can take right now.
SCAN_RUNNING_DETAIL = (
    "A scan is currently running — wait for it to finish or cancel it first"
)


def require_library_idle() -> None:
    """Raise 409 unless the library write lock is free.

    Names a running scan specifically when that is what holds the lock; otherwise
    reports the generic busy state, because the lock itself does not record which
    operation took it and guessing "a scan" is how the original contradiction
    read to the user.
    """
    if not write_lock.is_held():
        return
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail=SCAN_RUNNING_DETAIL)
    raise HTTPException(status_code=409, detail=write_lock.BUSY_DETAIL)

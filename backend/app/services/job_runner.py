"""Shared in-memory background-job runner (STUDIO-59, code-health F4).

The ``threading.Thread(daemon=True)`` + module-global status dict + ``Lock``
pattern was reimplemented independently in the scanner, enrich-refresh, import,
and draft-generation code, each with a slightly different progress/status
protocol. This module deduplicates that into one registry with a single lock
and a uniform payload shape::

    {"state": <JobState>, "progress": {...}, "message": str, "error": str|None}

Consumers migrate one at a time. Each keeps its own public status shape by
mapping this payload back to its legacy field names (aliases), so router and
frontend contracts are unchanged.

Non-goals (kept out on purpose): persistence across restarts and queueing.
Semantics stay in-memory — this is deduplication, not a new capability.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class JobState(str, Enum):
    """Lifecycle of a job. ``str`` mixin so payloads JSON-serialise to the plain
    value without a custom encoder."""

    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


# A job body receives its own handle so it can push progress and observe cancel.
JobTarget = Callable[["JobHandle"], Any]


@dataclass
class JobHandle:
    """One job's live state plus the worker-facing controls.

    The registry lock is shared across every handle (passed in at creation) so a
    single lock guards the whole registry and all per-job field mutation — matching
    the "single state registry + lock" the ticket calls for. Workers only ever
    touch a handle through :meth:`update` / :attr:`cancelled`; readers use
    :meth:`payload`.
    """

    key: str
    _lock: threading.Lock
    state: JobState = JobState.IDLE
    message: str = ""
    error: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    _cancel: threading.Event = field(default_factory=threading.Event)
    _done: threading.Event = field(default_factory=threading.Event)

    # -- worker side --------------------------------------------------------

    def update(
        self,
        *,
        state: JobState | None = None,
        message: str | None = None,
        error: str | None = None,
        **progress: Any,
    ) -> None:
        """Merge new state/message/error and progress counters atomically.

        Progress keys are merged into the existing dict (not replaced) so a worker
        can bump one counter at a time from parallel threads without clobbering the
        others. Called on the hot path (e.g. once per indexed file), so it stays
        cheap: one lock, dict updates, no allocation of a new payload.
        """
        with self._lock:
            if state is not None:
                self.state = state
            if message is not None:
                self.message = message
            if error is not None:
                self.error = error
            if progress:
                self.progress.update(progress)

    def increment(self, **deltas: int) -> None:
        """Atomically add to progress counters (missing keys start at 0).

        For hot-path counters bumped concurrently from parallel worker threads
        (e.g. the scanner's files_found across four creator workers) — a plain
        ``update`` would read-modify-write outside the lock and lose increments.
        """
        with self._lock:
            for name, delta in deltas.items():
                self.progress[name] = self.progress.get(name, 0) + delta

    @property
    def cancelled(self) -> bool:
        """True once :meth:`JobRunner.cancel` was called for this job. Workers poll
        this at safe checkpoints — cancellation is cooperative, never a kill."""
        return self._cancel.is_set()

    # -- reader side --------------------------------------------------------

    def payload(self) -> dict:
        """Uniform snapshot: ``{state, progress, message, error}``. A shallow copy
        of ``progress`` so callers can't mutate live job state through the result."""
        with self._lock:
            return {
                "state": self.state.value,
                "progress": dict(self.progress),
                "message": self.message,
                "error": self.error,
            }


class JobRunner:
    """Registry of named jobs guarded by one lock.

    ``start`` launches a daemon thread that runs the target with the job's handle,
    marking terminal state (DONE / ERROR) and signalling completion even if the
    body raises. ``single_flight`` (default) refuses to start a job whose key is
    already running, returning ``None`` so the caller can surface a 409.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobHandle] = {}

    def start(
        self,
        key: str,
        target: JobTarget,
        *,
        single_flight: bool = True,
        **kwargs: Any,
    ) -> JobHandle | None:
        """Start ``target`` on a daemon thread, passing it a fresh :class:`JobHandle`.

        Extra ``kwargs`` are forwarded to ``target(handle, **kwargs)``. Returns the
        handle, or ``None`` when ``single_flight`` and a job with this key is already
        running. The handle is registered (and any prior terminal one replaced)
        before the thread starts, so an immediate ``status(key)`` sees RUNNING.
        """
        with self._lock:
            existing = self._jobs.get(key)
            if single_flight and existing is not None and existing.state is JobState.RUNNING:
                return None
            handle = JobHandle(key=key, _lock=self._lock, state=JobState.RUNNING)
            self._jobs[key] = handle

        def _run() -> None:
            try:
                target(handle, **kwargs)
                # A target that finishes without setting a terminal state (or that
                # cancelled cooperatively) gets a sensible default here.
                if handle.state is JobState.RUNNING:
                    handle.update(
                        state=JobState.CANCELLED if handle.cancelled else JobState.DONE
                    )
            except Exception as exc:  # noqa: BLE001 — surface any failure as job state
                logger.exception("Job %r failed: %s", key, exc)
                handle.update(state=JobState.ERROR, error=str(exc))
            finally:
                handle._done.set()

        threading.Thread(target=_run, name=f"job:{key}", daemon=True).start()
        return handle

    def run_inline(
        self, key: str, target: JobTarget, **kwargs: Any
    ) -> JobHandle:
        """Run ``target`` synchronously on the calling thread (no daemon thread).

        Same terminal-state bookkeeping as :meth:`start`, for callers that manage
        their own thread or run inline (tests). Bypasses the single-flight guard.
        """
        with self._lock:
            handle = JobHandle(key=key, _lock=self._lock, state=JobState.RUNNING)
            self._jobs[key] = handle
        try:
            target(handle, **kwargs)
            if handle.state is JobState.RUNNING:
                handle.update(
                    state=JobState.CANCELLED if handle.cancelled else JobState.DONE
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job %r failed: %s", key, exc)
            handle.update(state=JobState.ERROR, error=str(exc))
        finally:
            handle._done.set()
        return handle

    def get(self, key: str) -> JobHandle | None:
        with self._lock:
            return self._jobs.get(key)

    def keys(self) -> list[str]:
        """Snapshot of registered job keys. Lets a consumer that namespaces its
        keys (e.g. ``draft:<id>``) reset just its own without touching others."""
        with self._lock:
            return list(self._jobs)

    def status(self, key: str) -> dict:
        """Uniform payload for ``key``, or an IDLE payload if it never ran."""
        handle = self.get(key)
        if handle is None:
            return {"state": JobState.IDLE.value, "progress": {}, "message": "", "error": None}
        return handle.payload()

    def is_running(self, key: str) -> bool:
        handle = self.get(key)
        return handle is not None and handle.state is JobState.RUNNING

    def cancel(self, key: str) -> bool:
        """Request cooperative cancellation. Returns True if a running job was
        signalled, False if there is no running job for this key."""
        handle = self.get(key)
        if handle is None or handle.state is not JobState.RUNNING:
            return False
        handle._cancel.set()
        return True

    def wait(self, key: str, timeout: float | None = None) -> bool:
        """Block until ``key``'s worker finishes (or ``timeout`` elapses).

        Returns True if the job completed or never ran, False on timeout. Lets tests
        await completion deterministically instead of polling on a wall clock."""
        handle = self.get(key)
        if handle is None:
            return True
        return handle._done.wait(timeout)

    def reset(self, key: str | None = None) -> None:
        """Drop a job (or all jobs) from the registry. Test-only hook so a
        module-level runner doesn't leak state across cases."""
        with self._lock:
            if key is None:
                self._jobs.clear()
            else:
                self._jobs.pop(key, None)


# Process-wide registry. In-memory and single-process, matching the pattern it
# replaces — one runner shared by every consumer.
runner = JobRunner()

"""Async AI draft-generation jobs (#524, M4 §8.3).

Mirrors the library-scan pattern: a background daemon thread does the work while
the request returns immediately, and the UI polls a status endpoint. Generation
produces a **candidate draft** that is held for review (#492) — the job does NOT
touch the guide's content spine. The reconciled draft tabs, the validator flags
computed on that candidate, and any unresolved paints all ride in the job status
so the review UI can diff the proposal against the live guide before the user
accepts it (a plain PATCH of the tabs). Nothing is committed until then.

The actual model call is injected behind `Generator` so this plumbing can ship
and be tested with a fake before the real Claude call lands (#526). The default
generator raises until then.
"""
from __future__ import annotations

import threading
from typing import Callable

from sqlalchemy.orm import Session

from app.painting.models import Guide
from app.painting.schemas import GuideDraft
from app.painting.services.draft import reconcile_draft_paints
from app.painting.services.guides import build_tabs
from app.painting.services.validation import validate_guide

# A generator turns a guide (its metadata/context) into a GuideDraft. Swapped for
# the real Claude-backed implementation in #526; tests inject a fake.
Generator = Callable[[Session, Guide], GuideDraft]

_state_lock = threading.Lock()
# guide_id -> {status: idle|running|done|error, message, unresolved, error}
_jobs: dict[int, dict] = {}
# guide_id -> Event set when that guide's worker finishes. Lets callers await
# completion deterministically (tests) instead of polling on a wall clock.
_done_events: dict[int, threading.Event] = {}


def _default_generator(db: Session, guide: Guide) -> GuideDraft:
    # Lazy import avoids a module-load cycle and keeps the anthropic import off
    # code paths that never generate. Wired up in #526.
    from app.painting.services.generation import generate_guide_draft

    return generate_guide_draft(db, guide)


_generator: Generator = _default_generator


def set_generator(fn: Generator) -> None:
    """Install the real (or a fake, in tests) generator."""
    global _generator
    _generator = fn


def reset_generator() -> None:
    global _generator
    _generator = _default_generator


def _idle() -> dict:
    return {
        "status": "idle", "message": "", "unresolved": [],
        "draft": None, "flags": [], "error": None,
    }


def get_status(guide_id: int) -> dict:
    with _state_lock:
        return dict(_jobs.get(guide_id, _idle()))


def is_running(guide_id: int) -> bool:
    with _state_lock:
        return _jobs.get(guide_id, {}).get("status") == "running"


def _set(guide_id: int, **fields) -> None:
    with _state_lock:
        _jobs.setdefault(guide_id, _idle()).update(fields)


def start_generation(guide_id: int) -> bool:
    """Kick off generation for a guide. Returns False if one is already running
    (single-flight per guide), so the caller can surface a 409."""
    with _state_lock:
        if _jobs.get(guide_id, {}).get("status") == "running":
            return False
        _jobs[guide_id] = {
            "status": "running", "message": "generating", "unresolved": [],
            "draft": None, "flags": [], "error": None,
        }
        _done_events[guide_id] = threading.Event()
    threading.Thread(target=_run, args=(guide_id,), daemon=True).start()
    return True


def wait(guide_id: int, timeout: float = 10.0) -> bool:
    """Block until the guide's worker finishes, or `timeout` elapses.

    Returns True if the worker completed (or none was running). Lets tests await
    completion deterministically rather than polling the status endpoint on a
    timer — production code uses the async status endpoint and never calls this."""
    with _state_lock:
        event = _done_events.get(guide_id)
    if event is None:
        return True
    return event.wait(timeout)


def _run(guide_id: int) -> None:
    # Imported here so tests' monkeypatched SessionLocal (bound to the in-memory
    # engine) is picked up at call time, not at import time.
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        guide = db.get(Guide, guide_id)
        if guide is None:
            _set(guide_id, status="error", error="guide not found")
            return

        draft = _generator(db, guide)
        result = reconcile_draft_paints(db, draft)

        # Hold the candidate for review (#492) — do NOT touch the guide spine.
        # Validate the proposed tabs on a transient, unpersisted guide so the
        # review UI gets flags up front; build_tabs yields in-memory ORM objects
        # with their phase/step relationships populated, which is all the
        # validator walks (it never reads guide.id).
        candidate = Guide(tabs=build_tabs(result.draft.tabs))
        flags = validate_guide(db, candidate)

        _set(
            guide_id,
            status="done",
            message="draft ready for review",
            draft={"tabs": result.draft.model_dump()["tabs"]},
            flags=[f.model_dump() for f in flags],
            unresolved=[u.__dict__ for u in result.unresolved],
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 — surface any failure as job state
        db.rollback()
        _set(guide_id, status="error", error=str(exc))
    finally:
        db.close()
        # Signal completion last, so a waiter that wakes sees terminal state.
        with _state_lock:
            event = _done_events.get(guide_id)
        if event is not None:
            event.set()

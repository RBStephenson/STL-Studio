"""Async AI draft-generation jobs (#524, M4 §8.3).

A background job does the work while the request returns immediately, and the UI
polls a status endpoint. Generation produces a **candidate draft** that is held
for review (#492) — the job does NOT touch the guide's content spine. The
reconciled draft tabs, the validator flags computed on that candidate, and any
unresolved paints all ride in the job status so the review UI can diff the
proposal against the live guide before the user accepts it (a plain PATCH of the
tabs). Nothing is committed until then.

Runs on the shared background-job runner (services/job_runner.py, STUDIO-59),
keyed per guide so generation is single-flight per guide. The guide-facing status
shape ({status, message, unresolved, draft, flags, error}) is preserved as
aliases mapped out of the runner's uniform payload.

The actual model call is injected behind `Generator` so this plumbing can ship
and be tested with a fake before the real Claude call lands (#526). The default
generator raises until then.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from app.painting.models import Guide
from app.painting.schemas import GuideDraft
from app.painting.services.draft import reconcile_draft_paints
from app.painting.services.guides import build_tabs
from app.painting.services.validation import validate_guide
from app.services.job_runner import JobHandle, JobState, runner

# A generator turns a guide (its metadata/context) into a GuideDraft. Swapped for
# the real Claude-backed implementation in #526; tests inject a fake.
Generator = Callable[[Session, Guide], GuideDraft]

# Registry keys are namespaced so a consumer-scoped reset (tests) touches only
# this service's jobs, not the enrich/scan jobs sharing the same runner.
_KEY_PREFIX = "draft:"


def _key(guide_id: int) -> str:
    return f"{_KEY_PREFIX}{guide_id}"


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


def get_status(guide_id: int) -> dict:
    """Guide-facing status shape, mapped from the runner's uniform payload.

    ``status`` mirrors the job state (idle|running|done|error); the draft/flags/
    unresolved payload rides in the job's progress dict."""
    payload = runner.status(_key(guide_id))
    progress = payload["progress"]
    return {
        "status": payload["state"],
        "message": payload["message"],
        "unresolved": progress.get("unresolved", []),
        "draft": progress.get("draft"),
        "flags": progress.get("flags", []),
        "error": payload["error"],
    }


def is_running(guide_id: int) -> bool:
    return runner.is_running(_key(guide_id))


def start_generation(guide_id: int) -> bool:
    """Kick off generation for a guide. Returns False if one is already running
    (single-flight per guide), so the caller can surface a 409."""
    handle = runner.start(_key(guide_id), _run, guide_id=guide_id)
    return handle is not None


def wait(guide_id: int, timeout: float = 10.0) -> bool:
    """Block until the guide's worker finishes, or `timeout` elapses.

    Returns True if the worker completed (or none was running). Lets tests await
    completion deterministically rather than polling the status endpoint on a
    timer — production code uses the async status endpoint and never calls this."""
    return runner.wait(_key(guide_id), timeout)


def reset() -> None:
    """Drop every draft job from the shared registry. Test-only isolation hook —
    resets only ``draft:`` keys so sibling jobs (enrich/scan) are untouched."""
    for key in runner.keys():
        if key.startswith(_KEY_PREFIX):
            runner.reset(key)


def _run(job: JobHandle, *, guide_id: int) -> None:
    # Imported here so tests' monkeypatched SessionLocal (bound to the in-memory
    # engine) is picked up at call time, not at import time.
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        guide = db.get(Guide, guide_id)
        if guide is None:
            job.update(state=JobState.ERROR, error="guide not found")
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

        job.update(
            state=JobState.DONE,
            message="draft ready for review",
            draft={"tabs": result.draft.model_dump()["tabs"]},
            flags=[f.model_dump() for f in flags],
            unresolved=[u.__dict__ for u in result.unresolved],
        )
    except Exception:
        # Roll back this job's session, then re-raise so the runner records the
        # ERROR state + error string and logs the traceback.
        db.rollback()
        raise
    finally:
        db.close()

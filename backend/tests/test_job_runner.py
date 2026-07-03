"""Shared background-job runner (STUDIO-59, code-health F4)."""
import threading

import pytest

from app.services.job_runner import JobHandle, JobRunner, JobState


@pytest.fixture
def runner():
    return JobRunner()


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------

def test_status_of_unknown_key_is_idle(runner):
    assert runner.status("nope") == {
        "state": "idle", "progress": {}, "message": "", "error": None,
    }


def test_payload_shape_is_uniform(runner):
    def body(job: JobHandle) -> None:
        job.update(message="working", count=3)

    handle = runner.run_inline("k", body)
    payload = handle.payload()
    assert set(payload) == {"state", "progress", "message", "error"}
    assert payload["state"] == "done"
    assert payload["message"] == "working"
    assert payload["progress"] == {"count": 3}
    assert payload["error"] is None


def test_payload_progress_is_a_copy(runner):
    handle = runner.run_inline("k", lambda job: job.update(n=1))
    snap = handle.payload()
    snap["progress"]["n"] = 999
    assert handle.payload()["progress"]["n"] == 1


# ---------------------------------------------------------------------------
# Terminal state bookkeeping
# ---------------------------------------------------------------------------

def test_inline_marks_done_when_body_sets_no_terminal_state(runner):
    runner.run_inline("k", lambda job: job.update(message="hi"))
    assert runner.status("k")["state"] == "done"


def test_inline_records_error_on_exception(runner):
    def boom(job: JobHandle) -> None:
        raise RuntimeError("kaboom")

    handle = runner.run_inline("k", boom)
    assert handle.state is JobState.ERROR
    assert handle.error == "kaboom"
    assert runner.status("k")["state"] == "error"


def test_body_may_set_its_own_terminal_state(runner):
    def body(job: JobHandle) -> None:
        job.update(state=JobState.DONE, message="finished")

    handle = runner.run_inline("k", body)
    assert handle.state is JobState.DONE
    assert handle.message == "finished"


# ---------------------------------------------------------------------------
# Threaded start + single-flight
# ---------------------------------------------------------------------------

def test_start_runs_on_a_thread_and_completes(runner):
    ran = threading.Event()

    def body(job: JobHandle) -> None:
        job.update(message="go")
        ran.set()

    handle = runner.start("k", body)
    assert handle is not None
    assert runner.wait("k", timeout=2.0)
    assert ran.is_set()
    assert runner.status("k")["state"] == "done"


def test_start_forwards_kwargs(runner):
    seen = {}

    def body(job: JobHandle, *, name: str) -> None:
        seen["name"] = name

    runner.start("k", body, name="dragon")
    runner.wait("k", timeout=2.0)
    assert seen == {"name": "dragon"}


def test_single_flight_refuses_second_start_while_running(runner):
    release = threading.Event()

    def body(job: JobHandle) -> None:
        release.wait(2.0)

    first = runner.start("k", body)
    assert first is not None
    # Second start for the same key while the first is running is refused.
    assert runner.start("k", body) is None
    release.set()
    runner.wait("k", timeout=2.0)
    # Once finished, the key is free again.
    assert runner.start("k", lambda job: None) is not None


def test_non_single_flight_allows_replacement(runner):
    runner.run_inline("k", lambda job: None)
    handle = runner.start("k", lambda job: None, single_flight=False)
    assert handle is not None


def test_is_running_reflects_lifecycle(runner):
    release = threading.Event()
    runner.start("k", lambda job: release.wait(2.0))
    assert runner.is_running("k")
    release.set()
    runner.wait("k", timeout=2.0)
    assert not runner.is_running("k")


# ---------------------------------------------------------------------------
# Cancellation (cooperative)
# ---------------------------------------------------------------------------

def test_cancel_signals_running_job_and_body_observes_it(runner):
    observed = {}
    proceed = threading.Event()

    def body(job: JobHandle) -> None:
        proceed.wait(2.0)
        observed["cancelled"] = job.cancelled

    runner.start("k", body)
    assert runner.cancel("k") is True
    proceed.set()
    runner.wait("k", timeout=2.0)
    assert observed["cancelled"] is True
    # A body that returns after cancellation without a terminal state lands CANCELLED.
    assert runner.status("k")["state"] == "cancelled"


def test_cancel_unknown_or_finished_job_returns_false(runner):
    assert runner.cancel("nope") is False
    runner.run_inline("k", lambda job: None)
    assert runner.cancel("k") is False


# ---------------------------------------------------------------------------
# Concurrency — update() is atomic across threads
# ---------------------------------------------------------------------------

def test_concurrent_updates_do_not_lose_increments(runner):
    def body(job: JobHandle) -> None:
        def bump() -> None:
            for _ in range(1000):
                with job._lock:
                    job.progress["n"] = job.progress.get("n", 0) + 1

        threads = [threading.Thread(target=bump) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    handle = runner.run_inline("k", body)
    assert handle.payload()["progress"]["n"] == 4000


# ---------------------------------------------------------------------------
# wait / reset
# ---------------------------------------------------------------------------

def test_wait_on_unknown_key_returns_true(runner):
    assert runner.wait("nope", timeout=0.1) is True


def test_wait_times_out_while_running(runner):
    release = threading.Event()
    runner.start("k", lambda job: release.wait(2.0))
    assert runner.wait("k", timeout=0.05) is False
    release.set()
    assert runner.wait("k", timeout=2.0) is True


def test_reset_clears_a_single_key(runner):
    runner.run_inline("a", lambda job: None)
    runner.run_inline("b", lambda job: None)
    runner.reset("a")
    assert runner.status("a")["state"] == "idle"
    assert runner.status("b")["state"] == "done"


def test_reset_all_clears_registry(runner):
    runner.run_inline("a", lambda job: None)
    runner.reset()
    assert runner.status("a")["state"] == "idle"

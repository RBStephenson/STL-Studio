"""Tests for the smoke_boot poll/timeout/crash-detection logic (STUDIO-102).

Only wait_for_health and terminate are covered — actually spawning a real exe
is exercised by the CI build itself. A fake process/clock keeps this fast and
independent of any real subprocess or network I/O.
"""
import time

import smoke_boot


class _FakeProc:
    def __init__(self, exit_after_polls: int | None = None):
        self._polls = 0
        self._exit_after_polls = exit_after_polls
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.pid = 4242

    def poll(self):
        self._polls += 1
        if self._exit_after_polls is not None and self._polls > self._exit_after_polls:
            self.returncode = 1
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def test_wait_for_health_succeeds_on_first_healthy_probe():
    proc = _FakeProc()
    assert smoke_boot.wait_for_health(proc, 1234, prober=lambda port: True) is True


def test_wait_for_health_retries_until_healthy():
    calls = {"n": 0}

    def prober(port):
        calls["n"] += 1
        return calls["n"] >= 3

    proc = _FakeProc()
    assert smoke_boot.wait_for_health(proc, 1234, interval_s=0, prober=prober) is True
    assert calls["n"] == 3


def test_wait_for_health_times_out_when_never_healthy():
    proc = _FakeProc()
    start = time.monotonic()
    result = smoke_boot.wait_for_health(
        proc, 1234, timeout_s=0.05, interval_s=0.01, prober=lambda port: False
    )
    assert result is False
    assert time.monotonic() - start < 1  # didn't hang past the deadline


def test_wait_for_health_fails_fast_when_process_exits_early():
    """A crash (e.g. frozen-import ModuleNotFoundError) must not wait out the
    full timeout — that's the STUDIO-100 regression this script exists to catch."""
    proc = _FakeProc(exit_after_polls=0)
    start = time.monotonic()
    result = smoke_boot.wait_for_health(
        proc, 1234, timeout_s=30, interval_s=0.01, prober=lambda port: False
    )
    assert result is False
    assert time.monotonic() - start < 1


def test_terminate_is_noop_if_already_exited():
    proc = _FakeProc()
    proc.returncode = 0
    smoke_boot.terminate(proc)
    assert proc.terminated is False


def test_terminate_kills_a_live_process_posix(monkeypatch):
    monkeypatch.setattr(smoke_boot, "IS_WINDOWS", False)
    proc = _FakeProc()
    smoke_boot.terminate(proc)
    assert proc.terminated is True


def test_terminate_uses_taskkill_tree_kill_on_windows(monkeypatch):
    """A hung grandchild process must not survive termination — plain
    terminate() only kills the immediate child, so Windows needs a tree-kill."""
    monkeypatch.setattr(smoke_boot, "IS_WINDOWS", True)
    calls = []
    monkeypatch.setattr(
        smoke_boot.subprocess,
        "run",
        lambda cmd, **kwargs: calls.append(cmd),
    )
    proc = _FakeProc()
    smoke_boot.terminate(proc)
    assert calls == [["taskkill", "/T", "/F", "/PID", "4242"]]

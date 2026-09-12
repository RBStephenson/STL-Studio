"""
Cancel responsiveness and one definition of "busy" (STUDIO-450).

Before this ticket the app carried two unrelated notions of a busy library:

* the scan **job state** (``get_status()["running"]``), which knows nothing about
  a reorganize apply, an undo, or an install; and
* the **library write lock**, which is what actually refuses a write with 409.

Anything that gated on the first while the second did the refusing could tell a
user "nothing is running" and "a scan is in progress" in the same breath. These
tests pin the two together: ``get_status()["busy"]`` is the lock, and every
answer the API gives has to agree with it.

They also pin the second half of the ticket — a cancelled scan must stop the
regroup phase rather than grinding through every remaining creator, and must not
advance a partially-walked root's incremental baseline on the way out.
"""
import threading

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Creator, Model, ScanRoot
from app.services import grouping, scanner, write_lock
from app.services.job_runner import JobHandle, JobState
from app.services.write_lock import LibraryBusy
from app.utils import utcnow


PRUNES = (
    "_prune_stale_models",
    "_prune_stale_paths",
    "_prune_stale_stl_files",
    "_prune_ignored",
    "_prune_phantoms",
)


def _stub_prunes(monkeypatch):
    """Neutralise the post-walk prunes so a test can drive the roots loop without
    a real library behind it. Mirrors TestScanAllRootsMountGate in test_scanner."""
    for name in PRUNES:
        monkeypatch.setattr(scanner, name, lambda *a, **k: 0)
    monkeypatch.setattr(scanner, "_prune_slicer_files", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "prune_empty_creators", lambda *a, **k: None)


def _online_root(db, tmp_path, **kwargs) -> ScanRoot:
    """A scan root that passes _root_available (exists AND is non-empty)."""
    (tmp_path / "creator").mkdir(exist_ok=True)
    root = ScanRoot(path=str(tmp_path), enabled=True, **kwargs)
    db.add(root)
    db.commit()
    return root


# ---------------------------------------------------------------------------
# One definition of busy
# ---------------------------------------------------------------------------

class TestBusyIsTheLock:
    def test_idle_library_is_not_busy(self, db):
        assert scanner.get_status()["busy"] is False

    def test_busy_while_an_apply_holds_the_lock_though_no_scan_is_running(self, db):
        """The pairing the job state can never see.

        A reorganize apply, undo or install holds the write lock for its whole
        duration while no scan job exists at all — so ``running`` is False and
        stays False. That is the guaranteed, permanently reproducible version of
        the contradiction in this ticket: the screen says nothing is running and
        every write is refused. ``busy`` is the field that tells the truth.
        """
        with write_lock.library_write("reorganize_apply"):
            status = scanner.get_status()
            assert status["running"] is False, (
                "running is job state and must stay job state — repurposing it "
                "would make the Scan button offer Cancel during an apply"
            )
            assert status["busy"] is True

        assert scanner.get_status()["busy"] is False

    def test_busy_and_write_refusal_agree_while_a_cancelled_scan_drains(
        self, db, tmp_path, monkeypatch
    ):
        """Cancel, then write — the two answers must agree (acceptance criterion).

        A cancel is cooperative: the worker keeps the lock until it unwinds. This
        drives that window deterministically by blocking inside ``_scan_root``,
        and asserts that for as long as a write is refused, the status the UI
        polls says busy.
        """
        _online_root(db, tmp_path)
        _stub_prunes(monkeypatch)

        entered = threading.Event()
        finish = threading.Event()

        def _blocking_scan_root(root, _db, _rules):
            entered.set()
            assert finish.wait(10), "test did not release the blocked scan"
            return set()

        monkeypatch.setattr(scanner, "_scan_root", _blocking_scan_root)

        worker = threading.Thread(target=scanner.scan_all_roots, kwargs={"db": db})
        worker.start()
        try:
            assert entered.wait(5), "scan never reached _scan_root"
            scanner.request_cancel()

            # The UI is polling this while the worker unwinds.
            assert scanner.get_status()["busy"] is True
            # And this is what a write actually gets.
            with pytest.raises(LibraryBusy):
                with write_lock.library_write("database_reset"):
                    pass
        finally:
            finish.set()
            worker.join(10)

        assert not worker.is_alive()
        assert scanner.get_status()["busy"] is False
        # Once busy clears the write goes through — no lingering false refusal.
        with write_lock.library_write("database_reset"):
            pass


# ---------------------------------------------------------------------------
# Cancel actually stops the expensive stage
# ---------------------------------------------------------------------------

class TestCancelStopsRegroup:
    def _wire_scan_root(self, db, monkeypatch):
        """_scan_root opens its own sessions for the worker pool and the regroup
        pass; point them at this test's engine and skip the filesystem walk so the
        regroup loop is the only thing left to measure."""
        Session = sessionmaker(bind=db.get_bind())
        monkeypatch.setattr(scanner, "SessionLocal", Session)
        monkeypatch.setattr(scanner, "_walk_for_models", lambda *a, **k: None)

    def test_cancel_breaks_out_of_the_regroup_loop(self, db, tmp_path, monkeypatch):
        """On a cancelled scan the regroup loop must stop, not run every creator.

        Breaking out early is safe by design: the loop commits per creator
        (STUDIO-396), so creators already regrouped are durable, and the next scan
        re-derives auto groups wholesale.
        """
        for name in ("Alpha", "Bravo", "Charlie", "Delta"):
            (tmp_path / name / "model").mkdir(parents=True)
            (tmp_path / name / "model" / "part.stl").write_bytes(b"solid x\nendsolid x\n")
        root = ScanRoot(path=str(tmp_path), enabled=True)
        db.add(root)
        db.commit()
        self._wire_scan_root(db, monkeypatch)

        job = JobHandle(key="cancel-regroup", _lock=threading.Lock(), state=JobState.RUNNING)
        monkeypatch.setattr(scanner, "_active", job)

        calls: list[int] = []

        def _counting_regroup(_session, creator_id):
            calls.append(creator_id)
            job._cancel.set()  # the user hits Cancel during the first creator

        monkeypatch.setattr(grouping, "regroup_creator", _counting_regroup)
        pruned: list[bool] = []
        monkeypatch.setattr(
            grouping, "prune_empty_groups", lambda _s: pruned.append(True) or 0
        )

        scanner._scan_root(root, db, scanner.ScanRules())

        assert len(calls) == 1, (
            f"regroup ran for {len(calls)} creators after cancel — it must stop at "
            "the first check, not grind through the rest of the root"
        )
        assert pruned == [], "the empty-group prune is part of the stage cancel skips"

    def test_uncancelled_scan_still_regroups_every_creator(self, db, tmp_path, monkeypatch):
        """The guard must not cost a normal scan its regrouping."""
        for name in ("Alpha", "Bravo", "Charlie"):
            (tmp_path / name / "model").mkdir(parents=True)
            (tmp_path / name / "model" / "part.stl").write_bytes(b"solid x\nendsolid x\n")
        root = ScanRoot(path=str(tmp_path), enabled=True)
        db.add(root)
        db.commit()
        self._wire_scan_root(db, monkeypatch)

        job = JobHandle(key="clean-regroup", _lock=threading.Lock(), state=JobState.RUNNING)
        monkeypatch.setattr(scanner, "_active", job)

        calls: list[int] = []
        monkeypatch.setattr(
            grouping, "regroup_creator", lambda _s, cid: calls.append(cid)
        )
        pruned: list[bool] = []
        monkeypatch.setattr(
            grouping, "prune_empty_groups", lambda _s: pruned.append(True) or 0
        )

        scanner._scan_root(root, db, scanner.ScanRules())

        assert len(calls) == 3
        assert pruned == [True]


# ---------------------------------------------------------------------------
# A cancelled run must not advance the incremental baseline
# ---------------------------------------------------------------------------

class TestCancelledRunKeepsBaseline:
    """``last_scanned`` is the mtime floor the next scan skips unchanged folders
    against. A cancelled run only walked part of the root, so advancing it hides
    real changes: a folder already in the database, modified between the prior
    baseline and this run's start but never reached, reads as unchanged next time
    and keeps stale STL rows until something touches it again.

    Narrow, but the existing code already refuses to advance the baseline for an
    offline root or a failed creator walk (STUDIO-295/79) for exactly this reason
    — cancellation was simply never added to that list.
    """

    def test_cancelled_walk_leaves_last_scanned_untouched(self, db, tmp_path, monkeypatch):
        from datetime import timedelta

        prior = utcnow() - timedelta(days=1)
        root = _online_root(db, tmp_path, last_scanned=prior)
        _stub_prunes(monkeypatch)

        def _cancel_midway(_root, _db, _rules):
            scanner.request_cancel()
            return set()

        monkeypatch.setattr(scanner, "_scan_root", _cancel_midway)

        scanner.scan_all_roots(db)
        db.refresh(root)

        assert root.last_scanned == prior, (
            "a cancelled run walked only part of the root — advancing its baseline "
            "makes the next scan skip folders this one never reached"
        )

    def test_clean_walk_still_advances_last_scanned(self, db, tmp_path, monkeypatch):
        from datetime import timedelta

        prior = utcnow() - timedelta(days=1)
        root = _online_root(db, tmp_path, last_scanned=prior)
        _stub_prunes(monkeypatch)
        monkeypatch.setattr(scanner, "_scan_root", lambda *a, **k: set())

        scanner.scan_all_roots(db)
        db.refresh(root)

        assert root.last_scanned != prior


# ---------------------------------------------------------------------------
# The API answers agree with the lock
# ---------------------------------------------------------------------------

class TestRoutersAgreeWithTheLock:
    def test_scan_status_exposes_busy(self, client):
        r = client.get("/scan/status")
        assert r.status_code == 200
        assert r.json()["busy"] is False

    def test_database_reset_refuses_with_an_honest_message_during_an_apply(self, client):
        """The reported symptom, at the router level: no scan is running, so the
        old ``_require_idle`` waved the request through to ``library_write``,
        which refused it. The user was told a scan was in progress by an app
        reporting no scan. Now the pre-check owns the refusal and names the real
        state."""
        with write_lock.library_write("reorganize_apply"):
            assert client.get("/scan/status").json()["busy"] is True
            r = client.post("/database/reset")
            assert r.status_code == 409
            detail = r.json()["detail"]
            assert "scan is currently running" not in detail, (
                "no scan is running — the old message contradicted the status"
            )
            assert "busy" in detail.lower()

    def test_group_write_refused_while_the_lock_is_held_by_a_non_scan_op(
        self, client, db
    ):
        """Gates that only consulted the scan job state let writes through during
        an apply/undo/install — and during a cancelled scan's drain, racing the
        regroup pass they were meant to be excluded from."""
        creator = Creator(name="Creator")
        db.add(creator)
        db.flush()
        first = Model(name="A", folder_path="/lib/a", creator_id=creator.id)
        second = Model(name="B", folder_path="/lib/b", creator_id=creator.id)
        db.add_all([first, second])
        db.commit()

        with write_lock.library_write("reorganize_apply"):
            r = client.post(
                "/models/groups/merge", json={"model_ids": [first.id, second.id]}
            )
            assert r.status_code == 409
            assert "busy" in r.json()["detail"].lower()

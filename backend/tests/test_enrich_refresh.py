"""
Re-enrich / refresh-stale.

STUDIO-11 (#699 2.4): a library-wide refresh can take minutes, so the actual
work moved to services/enrich_refresh.py and runs off the request path in a
background thread (mirroring services/scanner.py). Most of the behavioural
coverage below calls ``enrich_refresh.run_refresh(..., db=db)`` directly —
same convention test_scanner.py uses for scan_all_roots — so tests run
synchronously against the test session instead of a real thread opening its
own SessionLocal() (which would point at a different, tableless in-memory DB;
see conftest.db). A separate section covers the /enrich/refresh HTTP route
itself: starting the thread, the 409-when-running guard, and the status
endpoint.
"""
import threading
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import sessionmaker

import app.routers.enrich as enrich
from app.services import enrich_refresh, secrets
from app.services.scrapers.base import ScrapedModel
from app.utils import utcnow
from tests.conftest import make_creator, make_model


@pytest.fixture(autouse=True)
def _fixed_secret_key(monkeypatch):
    """Encryption key for the secrets store (the MMF-key path resolves through it)."""
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    yield
    secrets.reset_cache()


@pytest.fixture(autouse=True)
def _reset_refresh_state():
    """The shared job registry persists the refresh job across tests otherwise."""
    yield
    enrich_refresh.runner.reset(enrich_refresh._JOB_KEY)


_URL = "https://www.myminifactory.com/object/dragon-123"


def _deep(**overrides) -> ScrapedModel:
    fields = dict(
        title="Dragon Deluxe",
        description="A fearsome dragon with full detail.",
        source_url=_URL,
        source_site="myminifactory",
        external_id="123",
        tags=["dragon", "fantasy"],
        category="Creatures",
        license="CC-BY",
        thumbnail_url=None,
    )
    fields.update(overrides)
    return ScrapedModel(**fields)


def _enriched_model(db, creator, *, name="dragon", url=_URL, last_fetched=None, **kw):
    """A model that's already been enriched once (has a source_url)."""
    m = make_model(db, creator, name=name, **kw)
    m.source_url = url
    m.source_site = "myminifactory"
    m.source_last_fetched = last_fetched
    return m


# ---------------------------------------------------------------------------
# Core refresh logic — run_refresh(db=...) directly, no thread
# ---------------------------------------------------------------------------

def test_refresh_library_wide(db, monkeypatch):
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="dragon a")
    b = _enriched_model(db, creator, name="dragon b", url="https://www.myminifactory.com/object/orc-9")
    db.commit()

    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    result = enrich_refresh.run_refresh(db=db)
    assert result == {
        "running": False, "message": result["message"],
        "candidates": 2, "refreshed": 2, "failed": 0, "errors": 0,
    }

    db.refresh(a); db.refresh(b)
    assert a.category == "Creatures"
    assert b.category == "Creatures"


def test_refresh_skips_models_without_source_url(db, monkeypatch):
    creator = make_creator(db)
    enriched = _enriched_model(db, creator, name="has url")
    make_model(db, creator, name="never enriched")  # no source_url
    db.commit()

    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", fetch)

    result = enrich_refresh.run_refresh(db=db)
    assert result["candidates"] == 1  # only the model with a source_url
    db.refresh(enriched)
    assert enriched.category == "Creatures"


def test_refresh_scopes_by_creator(db, monkeypatch):
    a = make_creator(db, name="Creator A")
    b = make_creator(db, name="Creator B")
    in_scope = _enriched_model(db, a, name="a model")
    out_scope = _enriched_model(db, b, name="b model", url="https://www.myminifactory.com/object/x-2")
    db.commit()

    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    result = enrich_refresh.run_refresh(creator_id=a.id, db=db)
    assert result["candidates"] == 1

    db.refresh(in_scope); db.refresh(out_scope)
    assert in_scope.category == "Creatures"
    assert out_scope.category is None  # untouched


def test_refresh_scopes_by_model_ids(db, monkeypatch):
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="a")
    b = _enriched_model(db, creator, name="b", url="https://www.myminifactory.com/object/x-2")
    db.commit()

    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    result = enrich_refresh.run_refresh(model_ids=[a.id], db=db)
    assert result["candidates"] == 1

    db.refresh(a); db.refresh(b)
    assert a.category == "Creatures"
    assert b.category is None


def test_refresh_staleness_filter(db, monkeypatch):
    """stale_days keeps only models not fetched within the window (or never)."""
    creator = make_creator(db)
    fresh = _enriched_model(
        db, creator, name="fresh", last_fetched=utcnow() - timedelta(days=2),
        url="https://www.myminifactory.com/object/fresh-1",
    )
    stale = _enriched_model(
        db, creator, name="stale", last_fetched=utcnow() - timedelta(days=40),
        url="https://www.myminifactory.com/object/stale-2",
    )
    never = _enriched_model(
        db, creator, name="never", last_fetched=None,
        url="https://www.myminifactory.com/object/never-3",
    )
    db.commit()

    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    result = enrich_refresh.run_refresh(stale_days=30, db=db)
    assert result["candidates"] == 2  # stale + never, not fresh

    db.refresh(fresh); db.refresh(stale); db.refresh(never)
    assert fresh.category is None  # skipped — fetched recently
    assert stale.category == "Creatures"
    assert never.category == "Creatures"


def test_refresh_overwrites_aggressively(db, monkeypatch):
    """Refresh overwrites an existing title (bulk enrich only fills an empty one)."""
    creator = make_creator(db)
    model = _enriched_model(db, creator, name="dragon")
    model.title = "My Edited Title"
    model.description = "old description"
    db.commit()

    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=_deep()))

    result = enrich_refresh.run_refresh(db=db)
    assert result["refreshed"] == 1

    db.refresh(model)
    assert model.title == "Dragon Deluxe"           # overwritten
    assert model.description == "A fearsome dragon with full detail."


def test_refresh_does_not_reassign_creator(db, monkeypatch):
    """#699 1.1: refresh must not re-point creator_id even though it overwrites
    other fields aggressively — a differently-spelled scraped creator_name would
    otherwise silently split the library on every periodic refresh."""
    creator = make_creator(db, name="abe3d")
    model = _enriched_model(db, creator, name="dragon")
    db.commit()

    monkeypatch.setattr(
        enrich_refresh.scrapers, "fetch_url",
        AsyncMock(return_value=_deep(creator_name="Abe 3D Prints")),
    )

    result = enrich_refresh.run_refresh(db=db)
    assert result["refreshed"] == 1

    db.refresh(model)
    assert model.creator_id == creator.id


def test_refresh_failed_fetch_leaves_model_untouched(db, monkeypatch):
    creator = make_creator(db)
    model = _enriched_model(db, creator, name="orphan")
    model.title = "Keep Me"
    db.commit()

    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=None))

    result = enrich_refresh.run_refresh(db=db)
    assert result["candidates"] == 1
    assert result["refreshed"] == 0
    assert result["failed"] == 1
    assert result["errors"] == 0

    db.refresh(model)
    assert model.title == "Keep Me"      # not clobbered with shallow data
    assert model.description is None


def test_refresh_one_fetch_per_unique_url(db, monkeypatch):
    """Variants share a product URL — fetch once, fan out to every model."""
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="variant a")
    b = _enriched_model(db, creator, name="variant b")  # same _URL
    db.commit()

    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", fetch)

    result = enrich_refresh.run_refresh(db=db)
    assert result["refreshed"] == 2
    assert fetch.await_count == 1

    db.refresh(a); db.refresh(b)
    assert a.category == "Creatures"
    assert b.category == "Creatures"


def test_refresh_empty_library_returns_zero(db, monkeypatch):
    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", fetch)

    result = enrich_refresh.run_refresh(db=db)
    assert result["candidates"] == 0
    assert result["refreshed"] == 0
    assert result["failed"] == 0
    assert result["errors"] == 0
    fetch.assert_not_awaited()


def test_refresh_passes_mmf_key_to_fetch(db, monkeypatch):
    creator = make_creator(db)
    _enriched_model(db, creator, name="dragon")
    db.commit()

    secrets.set_mmf_api_key(db, "test-mmf-key")
    fetch = AsyncMock(return_value=_deep())
    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", fetch)

    result = enrich_refresh.run_refresh(db=db)
    assert result["refreshed"] == 1
    fetch.assert_awaited_once_with(_URL, mmf_api_key="test-mmf-key")


def test_refresh_shared_scraped_model_not_mutated_across_siblings(db, monkeypatch):
    """#699 2.2: variant siblings on the same URL each get their own effective
    source identity — the cached ScrapedModel must not be mutated in place."""
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="variant a")
    b = _enriched_model(db, creator, name="variant b")  # same _URL
    a.external_id = None
    b.external_id = None
    db.commit()

    shared = _deep(external_id=None)
    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=shared))

    enrich_refresh.run_refresh(db=db)

    assert shared.external_id is None  # the shared object was never mutated


def test_refresh_error_isolation_reports_errors_and_keeps_others(db, monkeypatch):
    """#699 2.3: one model raising during apply must not abort the batch — it's
    counted in ``errors`` while the other model still refreshes."""
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="dragon a", url="https://www.myminifactory.com/object/a-1")
    b = _enriched_model(db, creator, name="dragon b", url="https://www.myminifactory.com/object/b-2")
    db.commit()

    async def _fetch(url, mmf_api_key=None):
        return _deep(source_url=url, external_id=url)

    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", _fetch)

    real_apply = enrich_refresh.apply_scraped_to_model

    async def _flaky(db_, model, scraped, **kw):
        if model.id == a.id:
            raise RuntimeError("boom")
        return await real_apply(db_, model, scraped, **kw)

    monkeypatch.setattr(enrich_refresh, "apply_scraped_to_model", _flaky)

    result = enrich_refresh.run_refresh(db=db)
    assert result["errors"] == 1
    assert result["refreshed"] == 1

    db.refresh(b)
    assert b.category == "Creatures"


def test_refresh_chunks_candidates_and_updates_progress_mid_job(db, monkeypatch):
    """STUDIO-89: candidates are processed in bounded pages, not materialized
    and committed all at once. With chunk size forced to 1, every model gets
    its own fetch/commit and progress counters advance across chunks."""
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="a", url="https://www.myminifactory.com/object/a-1")
    b = _enriched_model(db, creator, name="b", url="https://www.myminifactory.com/object/b-2")
    c = _enriched_model(db, creator, name="c", url="https://www.myminifactory.com/object/c-3")
    db.commit()

    monkeypatch.setattr(enrich_refresh, "_CHUNK_SIZE", 1)

    seen_progress = []

    async def _fetch(url, mmf_api_key=None):
        # Snapshot progress mid-job — later chunks must see earlier chunks' work.
        status = enrich_refresh.runner.status(enrich_refresh._JOB_KEY)
        seen_progress.append(status["progress"].get("refreshed", 0))
        return _deep(source_url=url, external_id=url)

    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", _fetch)

    result = enrich_refresh.run_refresh(db=db)
    assert result == {
        "running": False, "message": result["message"],
        "candidates": 3, "refreshed": 3, "failed": 0, "errors": 0,
    }
    # Each of the 3 chunks saw the running count from the chunks before it —
    # progress was visible mid-job, not just at the very end.
    assert seen_progress == [0, 1, 2]

    db.refresh(a); db.refresh(b); db.refresh(c)
    assert a.category == b.category == c.category == "Creatures"


def test_refresh_chunk_failure_does_not_block_later_chunks(db, monkeypatch):
    """STUDIO-89: a fetch failure in an earlier chunk must not prevent later
    chunks from being processed."""
    creator = make_creator(db)
    a = _enriched_model(db, creator, name="a", url="https://www.myminifactory.com/object/a-1")
    b = _enriched_model(db, creator, name="b", url="https://www.myminifactory.com/object/b-2")
    db.commit()

    monkeypatch.setattr(enrich_refresh, "_CHUNK_SIZE", 1)

    async def _fetch(url, mmf_api_key=None):
        if url.endswith("a-1"):
            return None  # first chunk's fetch fails
        return _deep(source_url=url, external_id=url)

    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", _fetch)

    result = enrich_refresh.run_refresh(db=db)
    assert result["candidates"] == 2
    assert result["failed"] == 1
    assert result["refreshed"] == 1

    db.refresh(a); db.refresh(b)
    assert a.category is None          # failed chunk left untouched
    assert b.category == "Creatures"   # later chunk still processed


def test_run_refresh_updates_status_while_and_after_running(db, monkeypatch):
    monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=_deep()))
    assert enrich_refresh.get_status()["running"] is False

    result = enrich_refresh.run_refresh(db=db)

    assert result["running"] is False
    assert enrich_refresh.get_status() == result


# ---------------------------------------------------------------------------
# HTTP route — starts a thread, doesn't block the request
# ---------------------------------------------------------------------------

class TestRefreshRoute:
    def test_start_returns_immediately_without_running_the_job(self, client, monkeypatch):
        """The route must not itself do the fetch/apply work — only launch it."""
        called = {}

        def _fake_start_refresh(**kwargs):
            called.update(kwargs)
            return True

        monkeypatch.setattr(enrich.enrich_refresh, "start_refresh", _fake_start_refresh)

        resp = client.post("/enrich/refresh", json={"creator_id": 3, "stale_days": 7})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "running": True, "message": "refresh started"}
        # start_refresh registers synchronously on the request thread (STUDIO-85) —
        # no polling needed, unlike the old raw-thread launch.
        assert called == {"creator_id": 3, "model_ids": None, "stale_days": 7}

    def test_409_when_already_running(self, client, monkeypatch):
        monkeypatch.setattr(enrich.enrich_refresh, "start_refresh", lambda **kw: False)
        resp = client.post("/enrich/refresh", json={})
        assert resp.status_code == 409

    def test_status_endpoint_delegates_to_service(self, client, monkeypatch):
        monkeypatch.setattr(
            enrich.enrich_refresh, "get_status",
            lambda: {"running": True, "message": "starting", "candidates": 5, "refreshed": 2, "failed": 0, "errors": 0},
        )
        resp = client.get("/enrich/refresh/status")
        assert resp.status_code == 200
        assert resp.json()["candidates"] == 5


class TestRefreshSingleFlight:
    """STUDIO-85: the race is closed by registering the job on the request
    thread (JobRunner.start under its lock) rather than checking get_status()
    and only registering later inside the background thread's body."""

    def test_concurrent_starts_one_wins_one_rejected(self, db, test_engine, monkeypatch):
        # start_refresh always opens its own session (db=None) — point that at
        # a fresh session bound to this test's in-memory engine (StaticPool,
        # check_same_thread=False, so it's safe to touch from the background
        # thread) rather than the test's shared `db` fixture session, matching
        # production's own-session lifecycle (opened and closed by the job).
        monkeypatch.setattr(enrich_refresh, "SessionLocal", sessionmaker(bind=test_engine))

        creator = make_creator(db)
        _enriched_model(db, creator, name="dragon")
        db.commit()

        release = threading.Event()

        async def _blocking_fetch_url(url, mmf_api_key=None):
            release.wait(timeout=5)
            return _deep()

        monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", _blocking_fetch_url)

        started_first = enrich_refresh.start_refresh()
        assert started_first is True
        # No sleep/poll required: runner.start registers RUNNING before returning.
        assert enrich_refresh.get_status()["running"] is True

        started_second = enrich_refresh.start_refresh()
        assert started_second is False

        release.set()
        assert enrich_refresh.runner.wait(enrich_refresh._JOB_KEY, timeout=5)

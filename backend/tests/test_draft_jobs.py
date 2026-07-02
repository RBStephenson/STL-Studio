"""Async AI draft-generation job + endpoints (#524, M4 §8.3).

The real Claude call lands in #526; here the generator is faked so the job
plumbing (kickoff → status polling → persist-as-draft → key gating) is exercised
end to end without a live API.
"""
import threading

import pytest
from cryptography.fernet import Fernet

from app.models import AppSetting  # noqa: F401 (ensures table import side effects)
from app.painting.schemas import GuideDraft
from app.painting.services import draft_jobs
from app.services import secrets

from tests.test_painting_guides import mk_paint


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())
    secrets.reset_cache()
    draft_jobs._jobs.clear()
    draft_jobs._done_events.clear()
    yield
    secrets.reset_cache()
    draft_jobs.reset_generator()
    draft_jobs._jobs.clear()
    draft_jobs._done_events.clear()


def _make_guide(client):
    return client.post(
        "/painting/guides", json={"slug": "g1", "title": "Guide One", "tabs": []}
    ).json()


def _shelf_paint(client, name="Coal Black"):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    line = client.post(
        "/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}
    ).json()
    return mk_paint(client, line["id"], name=name)


def _draft_with(swatch_name: str) -> GuideDraft:
    return GuideDraft.model_validate({
        "title": "Guide One",
        "tabs": [{
            "name": "Skin",
            "phases": [{"label": "Base", "steps": [{
                "title": "Basecoat",
                "swatches": [{"name": swatch_name, "value_pct": 20}],
            }]}],
        }],
    })


def _wait(client, gid, timeout=10.0):
    """Block on the worker's completion Event (deterministic — no poll race),
    then return the terminal status."""
    assert draft_jobs.wait(gid, timeout), "draft job did not finish in time"
    return client.get(f"/painting/guides/{gid}/draft/status").json()


def test_draft_requires_api_key(client):
    guide = _make_guide(client)
    # No key set → 503.
    r = client.post(f"/painting/guides/{guide['id']}/draft")
    assert r.status_code == 503
    assert "API key" in r.json()["detail"]


def test_generation_holds_draft_without_committing_spine(client, db):
    secrets.set_ai_api_key(db, "sk-test-key")
    _shelf_paint(client, "Coal Black")
    guide = _make_guide(client)

    # Fake generator: references one owned paint + one unknown.
    def fake_gen(_db, _guide):
        return GuideDraft.model_validate({
            "title": "Guide One",
            "tabs": [{
                "name": "Skin",
                "phases": [{"label": "Base", "steps": [{
                    "title": "Basecoat",
                    "swatches": [
                        {"name": "Coal Black", "value_pct": 20},
                        {"name": "Unknown Purple", "value_pct": 80},
                    ],
                }]}],
            }],
        })
    draft_jobs.set_generator(fake_gen)

    r = client.post(f"/painting/guides/{guide['id']}/draft")
    assert r.status_code == 202
    assert r.json()["status"] == "running"

    status = _wait(client, guide["id"])
    assert status["status"] == "done"
    assert [u["name"] for u in status["unresolved"]] == ["Unknown Purple"]

    # The candidate draft rides in the job status for the review UI to diff,
    # with the unresolved Coal Black swatch resolved to a paint_id.
    draft_tabs = status["draft"]["tabs"]
    assert draft_tabs[0]["name"] == "Skin"
    swatches = draft_tabs[0]["phases"][0]["steps"][0]["swatches"]
    assert any(s["paint_id"] is not None for s in swatches)  # Coal Black resolved

    # The live guide is untouched — nothing is committed until the user accepts.
    refreshed = client.get(f"/painting/guides/{guide['id']}").json()
    assert refreshed["tabs"] == []


def test_done_status_carries_validator_flags(client, db):
    secrets.set_ai_api_key(db, "sk-test-key")
    # A known-but-not-owned paint: validating the candidate yields a block flag.
    paint = _shelf_paint(client, "Coal Black")
    client.patch(f"/painting/paints/{paint['id']}", json={"owned": False})
    guide = _make_guide(client)

    draft_jobs.set_generator(lambda _db, _g: _draft_with("Coal Black"))
    client.post(f"/painting/guides/{guide['id']}/draft")

    status = _wait(client, guide["id"])
    assert status["status"] == "done"
    codes = [f["code"] for f in status["flags"]]
    assert "paint_not_owned" in codes


def test_generator_failure_surfaces_as_error(client, db):
    secrets.set_ai_api_key(db, "sk-test-key")
    guide = _make_guide(client)

    def boom(_db, _guide):
        raise RuntimeError("model exploded")
    draft_jobs.set_generator(boom)

    # A generator failure ends the job in error state, never a crash.
    r = client.post(f"/painting/guides/{guide['id']}/draft")
    assert r.status_code == 202
    status = _wait(client, guide["id"])
    assert status["status"] == "error"
    assert "model exploded" in status["error"]


def test_single_flight_409_while_running(client, db):
    secrets.set_ai_api_key(db, "sk-test-key")
    guide = _make_guide(client)

    release = threading.Event()

    def blocking_gen(_db, _guide):
        release.wait(timeout=5)
        return _draft_with("Coal Black")
    draft_jobs.set_generator(blocking_gen)

    first = client.post(f"/painting/guides/{guide['id']}/draft")
    assert first.status_code == 202
    # Second kickoff while the first is still running → 409.
    second = client.post(f"/painting/guides/{guide['id']}/draft")
    assert second.status_code == 409

    release.set()
    _wait(client, guide["id"])

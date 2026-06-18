"""Tests for the print-status lifecycle endpoint (#166)."""
import pytest
from tests.conftest import make_creator, make_model


def setup(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="Paladin")
    db.commit()
    return model


# ---------------------------------------------------------------------------
# PATCH /models/{id}/print-status
# ---------------------------------------------------------------------------

def test_set_status_to_queued(client, db):
    m = setup(db)
    r = client.patch(f"/models/{m.id}/print-status", json={"status": "queued"})
    assert r.status_code == 200
    body = r.json()
    assert body["print_status"] == "queued"
    db.refresh(m)
    assert m.print_status == "queued"
    assert m.queued_at is not None
    assert m.queue_position is not None


def test_set_status_to_printing(client, db):
    m = setup(db)
    client.patch(f"/models/{m.id}/print-status", json={"status": "queued"})
    r = client.patch(f"/models/{m.id}/print-status", json={"status": "printing"})
    assert r.status_code == 200
    db.refresh(m)
    assert m.print_status == "printing"
    assert m.queued_at is None
    assert m.queue_position is None


def test_set_status_to_printed_increments_count(client, db):
    m = setup(db)
    r = client.patch(f"/models/{m.id}/print-status", json={"status": "printed"})
    assert r.status_code == 200
    body = r.json()
    assert body["print_status"] == "printed"
    assert body["print_count"] == 1
    db.refresh(m)
    assert m.print_status == "printed"
    assert m.print_count == 1
    assert m.printed_at is not None
    assert m.queue_position is None


def test_reprint_after_revert_nets_single_count(client, db):
    """A printed -> none -> printed round trip nets one count, not two: the
    revert undoes the original print so accidental click-throughs can't pile up
    phantom prints (#379)."""
    m = setup(db)
    client.patch(f"/models/{m.id}/print-status", json={"status": "printed"})
    # Reverting to none undoes that print (decrement + clear timestamp).
    client.patch(f"/models/{m.id}/print-status", json={"status": "none"})
    r = client.patch(f"/models/{m.id}/print-status", json={"status": "printed"})
    db.refresh(m)
    assert m.print_count == 1
    assert r.json()["print_count"] == 1


def test_set_status_to_none_clears_queue(client, db):
    m = setup(db)
    client.patch(f"/models/{m.id}/print-status", json={"status": "queued"})
    r = client.patch(f"/models/{m.id}/print-status", json={"status": "none"})
    assert r.status_code == 200
    db.refresh(m)
    assert m.print_status == "none"
    assert m.queued_at is None


def test_invalid_status_returns_422(client, db):
    m = setup(db)
    r = client.patch(f"/models/{m.id}/print-status", json={"status": "flying"})
    assert r.status_code == 422


def test_unknown_model_returns_404(client, db):
    r = client.patch("/models/99999/print-status", json={"status": "queued"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /models — print_status filter
# ---------------------------------------------------------------------------

def test_filter_by_print_status(client, db):
    creator = make_creator(db, name="Sculptor A")
    m1 = make_model(db, creator, name="Knight")
    m2 = make_model(db, creator, name="Wizard")
    db.commit()
    client.patch(f"/models/{m1.id}/print-status", json={"status": "printing"})

    r = client.get("/models?print_status=printing")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert m1.id in ids
    assert m2.id not in ids


def test_filter_by_print_status_none(client, db):
    creator = make_creator(db, name="Sculptor B")
    m1 = make_model(db, creator, name="Barbarian")
    m2 = make_model(db, creator, name="Rogue")
    db.commit()
    client.patch(f"/models/{m1.id}/print-status", json={"status": "queued"})

    r = client.get("/models?print_status=none")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert m2.id in ids
    assert m1.id not in ids


# ---------------------------------------------------------------------------
# ModelRead schema includes print_status and print_count
# ---------------------------------------------------------------------------

def test_model_read_includes_print_fields(client, db):
    m = setup(db)
    r = client.get(f"/models/{m.id}")
    assert r.status_code == 200
    body = r.json()
    assert "print_status" in body
    assert body["print_status"] == "none"
    assert "print_count" in body
    assert body["print_count"] == 0

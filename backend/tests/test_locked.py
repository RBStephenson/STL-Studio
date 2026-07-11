"""Tests for the "organized" lock (#978): toggling it, and that it actually
blocks every write path it's supposed to (STL file edits, AI Organize apply,
Reorganize eligibility) — not just a status label.
"""
from tests.conftest import make_creator, make_model, make_stl_file


class TestToggleLocked:
    def test_locks_and_unlocks(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator)
        db.commit()

        r = client.patch(f"/models/{m.id}/locked", json={"locked": True})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "locked": True}

        r2 = client.patch(f"/models/{m.id}/locked", json={"locked": False})
        assert r2.status_code == 200
        assert r2.json() == {"ok": True, "locked": False}

    def test_unlocking_a_locked_model_always_succeeds(self, client, db):
        """The lock never blocks itself — a mistaken lock must always be
        undoable, even while the model is currently locked."""
        creator = make_creator(db)
        m = make_model(db, creator)
        m.locked = True
        db.commit()

        r = client.patch(f"/models/{m.id}/locked", json={"locked": False})
        assert r.status_code == 200
        assert r.json()["locked"] is False

    def test_defaults_to_false(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator)
        db.commit()
        r = client.get(f"/models/{m.id}")
        assert r.json()["locked"] is False

    def test_404_for_missing_model(self, client):
        r = client.patch("/models/999999/locked", json={"locked": True})
        assert r.status_code == 404


class TestLockedBlocksStlFileEdits:
    def test_patch_stl_file_rejected_when_model_locked(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator)
        f = make_stl_file(db, m)
        m.locked = True
        db.commit()

        r = client.patch(f"/models/stl-files/{f.id}", json={"part_type": "Weapon"})
        assert r.status_code == 409
        db.refresh(f)
        assert f.part_type is None

    def test_patch_stl_file_allowed_when_unlocked(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator)
        f = make_stl_file(db, m)
        db.commit()

        r = client.patch(f"/models/stl-files/{f.id}", json={"part_type": "Weapon"})
        assert r.status_code == 200
        db.refresh(f)
        assert f.part_type == "Weapon"

    def test_patch_stl_file_allowed_again_after_unlocking(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator)
        f = make_stl_file(db, m)
        m.locked = True
        db.commit()

        assert client.patch(f"/models/stl-files/{f.id}", json={"part_type": "Weapon"}).status_code == 409

        client.patch(f"/models/{m.id}/locked", json={"locked": False})
        r = client.patch(f"/models/stl-files/{f.id}", json={"part_type": "Weapon"})
        assert r.status_code == 200


class TestLockedBlocksAiOrganizeApply:
    def test_apply_rejected_when_model_locked(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator)
        f = make_stl_file(db, m)
        m.locked = True
        db.commit()

        r = client.post(
            f"/models/{m.id}/ai-organize/apply",
            json={"items": [{"id": f.id, "part_type": "Weapon"}]},
        )
        assert r.status_code == 409
        db.refresh(f)
        assert f.part_type is None

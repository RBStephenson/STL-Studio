"""Tests for PATCH /models/bulk/enrich (#429)."""
from tests.conftest import make_creator, make_model


def _setup(db):
    creator = make_creator(db, name="Original Creator")
    a = make_model(db, creator, name="Alpha")
    b = make_model(db, creator, name="Bravo")
    c = make_model(db, creator, name="Charlie")
    db.commit()
    return creator, a, b, c


class TestBulkEnrich:
    def test_sets_creator_on_selected_models(self, client, db):
        creator, a, b, c = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id, b.id], "creator_name": "New Creator"})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "updated": 2}
        db.refresh(a); db.refresh(b); db.refresh(c)
        assert a.creator_id != creator.id
        assert b.creator_id != creator.id
        assert c.creator_id == creator.id  # unselected — unchanged

    def test_sets_character_on_selected_models(self, client, db):
        _, a, b, c = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id, b.id], "character": "Dragon"})
        assert r.status_code == 200
        db.refresh(a); db.refresh(b); db.refresh(c)
        assert a.character == "Dragon"
        assert b.character == "Dragon"
        assert c.character is None

    def test_sets_title_on_selected_models(self, client, db):
        _, a, b, _ = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id, b.id], "title": "Epic Set"})
        assert r.status_code == 200
        db.refresh(a); db.refresh(b)
        assert a.title == "Epic Set"
        assert b.title == "Epic Set"

    def test_partial_fields_only_touches_provided(self, client, db):
        creator, a, _, _ = _setup(db)
        client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": "Elf"})
        db.refresh(a)
        assert a.character == "Elf"
        assert a.creator_id == creator.id  # unchanged

    def test_creates_new_creator_when_name_unknown(self, client, db):
        _, a, _, _ = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id], "creator_name": "Brand New Creator"})
        assert r.status_code == 200
        db.refresh(a)
        detail = client.get(f"/models/{a.id}").json()
        assert detail["creator"]["name"] == "Brand New Creator"

    def test_empty_ids_returns_400(self, client, db):
        _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [], "character": "Orc"})
        assert r.status_code == 400

    def test_no_fields_returns_400(self, client, db):
        _, a, _, _ = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id]})
        assert r.status_code == 400

    def test_unknown_ids_are_ignored(self, client, db):
        _, a, _, _ = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id, 99999], "character": "Troll"})
        assert r.status_code == 200
        assert r.json()["updated"] == 1

    def test_blank_character_clears_field(self, client, db):
        _, a, _, _ = _setup(db)
        client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": "Elf"})
        client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": ""})
        db.refresh(a)
        assert a.character is None

    def test_route_not_matched_as_model_id(self, client, db):
        """Guard: /bulk/enrich must not be swallowed by /{model_id}/enrich."""
        _, a, _, _ = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": "Dwarf"})
        assert r.status_code == 200  # not 422 from int("bulk")

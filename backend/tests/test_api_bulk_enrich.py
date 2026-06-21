"""Tests for PATCH /models/bulk/enrich (#429, #437)."""
from unittest.mock import patch

from app.models import Creator, GroupOverride
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

    def test_sets_notes_on_selected_models(self, client, db):
        _, a, b, c = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id, b.id], "notes": "From pack X"})
        assert r.status_code == 200
        db.refresh(a); db.refresh(b); db.refresh(c)
        assert a.notes == "From pack X"
        assert b.notes == "From pack X"
        assert c.notes is None  # unselected — unchanged

    def test_sets_source_url_on_selected_models(self, client, db):
        _, a, b, _ = _setup(db)
        url = "https://www.myminifactory.com/object/123"
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id, b.id], "source_url": url})
        assert r.status_code == 200
        db.refresh(a); db.refresh(b)
        assert a.source_url == url
        assert b.source_url == url

    def test_blank_notes_clears_field(self, client, db):
        _, a, _, _ = _setup(db)
        client.patch("/models/bulk/enrich", json={"ids": [a.id], "notes": "temp"})
        client.patch("/models/bulk/enrich", json={"ids": [a.id], "notes": "  "})
        db.refresh(a)
        assert a.notes is None  # whitespace-only collapses to NULL

    def test_notes_only_is_a_valid_update(self, client, db):
        """notes/source_url count toward the 'at least one field' guard (#458)."""
        _, a, _, _ = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id], "notes": "n"})
        assert r.status_code == 200

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

    def test_whitespace_only_creator_rejected(self, client, db):
        """Regression (#439): a whitespace-only creator_name must 400 and
        create no Creator row."""
        _, a, _, _ = _setup(db)
        before = db.query(Creator).count()
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id], "creator_name": "   "})
        assert r.status_code == 400
        assert db.query(Creator).count() == before

    def test_creator_name_trimmed_before_resolution(self, client, db):
        """Leading/trailing whitespace is stripped before lookup/creation, so a
        padded name resolves to the existing creator rather than a new row."""
        _, a, _, _ = _setup(db)
        before = db.query(Creator).count()
        r = client.patch(
            "/models/bulk/enrich",
            json={"ids": [a.id], "creator_name": "  Original Creator  "},
        )
        assert r.status_code == 200
        assert db.query(Creator).count() == before  # no duplicate created
        db.refresh(a)
        detail = client.get(f"/models/{a.id}").json()
        assert detail["creator"]["name"] == "Original Creator"

    def test_differently_cased_creator_resolves_to_existing(self, client, db):
        """Case-insensitive matching is preserved after trimming."""
        _, a, _, _ = _setup(db)
        before = db.query(Creator).count()
        r = client.patch(
            "/models/bulk/enrich",
            json={"ids": [a.id], "creator_name": "ORIGINAL creator"},
        )
        assert r.status_code == 200
        assert db.query(Creator).count() == before
        db.refresh(a)
        detail = client.get(f"/models/{a.id}").json()
        assert detail["creator"]["name"] == "Original Creator"

    def test_route_not_matched_as_model_id(self, client, db):
        """Guard: /bulk/enrich must not be swallowed by /{model_id}/enrich."""
        _, a, _, _ = _setup(db)
        r = client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": "Dwarf"})
        assert r.status_code == 200  # not 422 from int("bulk")

    def test_character_creates_group_override(self, client, db):
        """Setting character must persist a GroupOverride so rescans don't overwrite it."""
        _, a, _, _ = _setup(db)
        client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": "Dragon"})
        override = db.query(GroupOverride).filter(GroupOverride.path == a.folder_path).first()
        assert override is not None
        assert override.character == "Dragon"

    def test_blank_character_creates_ungroup_override(self, client, db):
        """Clearing character must write a NULL GroupOverride, not just clear the column."""
        _, a, _, _ = _setup(db)
        client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": "Elf"})
        client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": ""})
        override = db.query(GroupOverride).filter(GroupOverride.path == a.folder_path).first()
        assert override is not None
        assert override.character is None  # explicit ungroup — not deleted

    def test_character_survives_rescan(self, client, db):
        """Regression: bulk-enriched character must not be overwritten by a subsequent scan."""
        from app.services import scanner

        _, a, _, _ = _setup(db)
        client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": "Orc"})

        # Simulate what _index_model does: load overrides then apply them.
        scanner._load_group_overrides(db)
        # The override must be present in the scanner's in-memory map.
        assert a.folder_path in scanner._group_overrides
        assert scanner._group_overrides[a.folder_path] == "Orc"

    def test_409_when_scan_running(self, client, db):
        """Returns 409 when a scan is in progress, matching set-group / batch-set-group behaviour."""
        _, a, _, _ = _setup(db)
        with patch("app.routers.models.scanner.get_status", return_value={"running": True}):
            r = client.patch("/models/bulk/enrich", json={"ids": [a.id], "character": "Troll"})
        assert r.status_code == 409

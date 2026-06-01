"""
Tests for the /models API endpoints.

Covers: listing, search, variant grouping, variants endpoint,
        stats, bulk tag, model patch, STL file part_type.
"""
import pytest
from tests.conftest import make_creator, make_model, make_stl_file
from app.services.tag_sync import sync_model_tags


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def commit_all(db):
    """Flush + commit so API queries see the data."""
    db.commit()


# ---------------------------------------------------------------------------
# Basic listing
# ---------------------------------------------------------------------------

class TestListModels:
    def test_empty_db_returns_empty(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_returns_created_model(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Dragon Warrior")
        commit_all(db)

        resp = client.get("/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Dragon Warrior"

    def test_pagination(self, client, db):
        creator = make_creator(db)
        for i in range(5):
            make_model(db, creator, name=f"Model {i}")
        commit_all(db)

        resp = client.get("/models?page=1&page_size=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 3

    def test_search_by_name(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Undead Knight")
        make_model(db, creator, name="Dragon Warrior")
        commit_all(db)

        resp = client.get("/models?q=undead")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Undead Knight"

    def test_filter_needs_review(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Clean Model", needs_review=False)
        make_model(db, creator, name="Flagged Model", needs_review=True)
        commit_all(db)

        resp = client.get("/models?needs_review=true")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Flagged Model"

    def test_filter_by_creator(self, client, db):
        creator_a = make_creator(db, "Creator A")
        creator_b = make_creator(db, "Creator B")
        make_model(db, creator_a, name="A Model")
        make_model(db, creator_b, name="B Model")
        commit_all(db)

        resp = client.get(f"/models?creator_id={creator_a.id}")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "A Model"


# ---------------------------------------------------------------------------
# Variant grouping
# ---------------------------------------------------------------------------

class TestVariantGrouping:
    def _make_variant_group(self, db):
        """Create a creator with 3 variants under character='Akuma'."""
        creator = make_creator(db, "PolyMind")
        v1 = make_model(db, creator, name="Full_cutted", character="Akuma")
        v2 = make_model(db, creator, name="No_cuts", character="Akuma")
        v3 = make_model(db, creator, name="Semi_cutted", character="Akuma")
        commit_all(db)
        return creator, [v1, v2, v3]

    def test_grouped_returns_one_card(self, client, db):
        self._make_variant_group(db)
        resp = client.get("/models?group_variants=true")
        data = resp.json()
        assert data["total"] == 1

    def test_grouped_card_has_variant_count(self, client, db):
        self._make_variant_group(db)
        resp = client.get("/models?group_variants=true")
        item = resp.json()["items"][0]
        assert item["variant_count"] == 3

    def test_ungrouped_returns_all(self, client, db):
        self._make_variant_group(db)
        resp = client.get("/models?group_variants=false")
        data = resp.json()
        assert data["total"] == 3

    def test_models_without_character_unaffected(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Solo Model A")
        make_model(db, creator, name="Solo Model B")
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        data = resp.json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["variant_count"] == 1

    def test_single_character_model_not_grouped(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Unique", character="OnlyOne")
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["variant_count"] == 1

    def test_group_representative_prefers_thumbnail(self, client, db):
        creator = make_creator(db, "Creator")
        # v1 has no thumbnail, v2 has one — v2 should be representative
        make_model(db, creator, name="No_thumb", character="Hero", thumbnail_path=None)
        v2 = make_model(db, creator, name="Has_thumb", character="Hero", thumbnail_path="/tmp/thumb.jpg")
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        item = resp.json()["items"][0]
        assert item["id"] == v2.id


# ---------------------------------------------------------------------------
# Variants endpoint
# ---------------------------------------------------------------------------

class TestVariantsEndpoint:
    def test_returns_all_variants(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Full_cutted", character="Akuma")
        make_model(db, creator, name="No_cuts", character="Akuma")
        make_model(db, creator, name="Semi_cutted", character="Akuma")
        commit_all(db)

        resp = client.get(f"/models/variants?creator_id={creator.id}&character=Akuma")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        names = {item["name"] for item in data["items"]}
        assert names == {"Full_cutted", "No_cuts", "Semi_cutted"}

    def test_wrong_creator_returns_empty(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Full_cutted", character="Akuma")
        commit_all(db)

        resp = client.get(f"/models/variants?creator_id=9999&character=Akuma")
        assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_counts(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Normal")
        make_model(db, creator, name="Review", needs_review=True)
        make_model(db, creator, name="Thumb", thumbnail_path="/tmp/t.jpg")
        commit_all(db)

        resp = client.get("/models/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["needs_review"] == 1
        assert data["no_thumbnail"] == 2


# ---------------------------------------------------------------------------
# Model PATCH
# ---------------------------------------------------------------------------

class TestModelUpdate:
    def test_patch_title(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        commit_all(db)

        resp = client.patch(f"/models/{model.id}", json={"title": "New Title"})
        assert resp.status_code == 200

        resp = client.get(f"/models/{model.id}")
        assert resp.json()["title"] == "New Title"

    def test_patch_unknown_model_returns_404(self, client):
        resp = client.patch("/models/99999", json={"title": "X"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# STL file part_type
# ---------------------------------------------------------------------------

class TestSTLFilePartType:
    def test_set_part_type(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        stl = make_stl_file(db, model, filename="Head_01.stl")
        commit_all(db)

        resp = client.patch(f"/models/stl-files/{stl.id}", json={"part_type": "Head"})
        assert resp.status_code == 200

        # Verify it's stored normalized (lowercase)
        db.refresh(stl)
        assert stl.part_type == "head"

    def test_clear_part_type(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        stl = make_stl_file(db, model, filename="Head_01.stl", part_type="head")
        commit_all(db)

        resp = client.patch(f"/models/stl-files/{stl.id}", json={"part_type": ""})
        assert resp.status_code == 200

        db.refresh(stl)
        assert stl.part_type is None

    def test_part_type_visible_in_model_detail(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        make_stl_file(db, model, filename="Arm_01.stl", part_type="right arm")
        commit_all(db)

        resp = client.get(f"/models/{model.id}")
        assert resp.status_code == 200
        files = resp.json()["stl_files"]
        assert any(f["part_type"] == "right arm" for f in files)

    def test_unknown_file_returns_404(self, client):
        resp = client.patch("/models/stl-files/99999", json={"part_type": "head"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Print queue ordering
# ---------------------------------------------------------------------------

class TestQueueOrdering:
    def _queue_names(self, client):
        resp = client.get("/models?in_queue=true&sort=queue&group_variants=false")
        assert resp.status_code == 200
        return [i["name"] for i in resp.json()["items"]]

    def test_favorites_float_to_top(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        c = make_model(db, creator, name="C")
        for m, pos in ((a, 0), (b, 1), (c, 2)):
            m.in_queue = True
            m.queue_position = pos
        c.is_favorite = True   # favorite jumps to the front despite position 2
        commit_all(db)

        assert self._queue_names(client) == ["C", "A", "B"]

    def test_reorder_persists(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        c = make_model(db, creator, name="C")
        commit_all(db)
        for m in (a, b, c):
            client.patch(f"/models/{m.id}/queue", json={"in_queue": True})

        # Default order is insertion order A, B, C.
        assert self._queue_names(client) == ["A", "B", "C"]

        resp = client.patch("/models/queue/reorder", json={"ids": [c.id, a.id, b.id]})
        assert resp.status_code == 200
        assert resp.json()["updated"] == 3

        assert self._queue_names(client) == ["C", "A", "B"]

    def test_favorite_overrides_manual_order(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        commit_all(db)
        for m in (a, b):
            client.patch(f"/models/{m.id}/queue", json={"in_queue": True})
        # Manual order A, B; favorite B -> B floats to top.
        client.patch(f"/models/{b.id}/favorite", json={"is_favorite": True})

        assert self._queue_names(client) == ["B", "A"]

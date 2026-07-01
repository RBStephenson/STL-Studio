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

    def test_variant_count_skips_excluded_models(self, client, db):
        # Excluding a variant must drop it from the badge count (#215),
        # matching what the variant-group page shows.
        _, variants = self._make_variant_group(db)
        variants[2].excluded = True
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        item = resp.json()["items"][0]
        assert item["variant_count"] == 2

    def test_variant_count_correct_on_later_page(self, client, db):
        # vc_map is scoped to the current page's (creator_id, character) pairs
        # (#393); a representative that lands on page 2 must still get its count.
        filler = make_creator(db, "Aaa Filler")
        for i in range(3):
            make_model(db, filler, name=f"Filler {i}", character=f"Solo{i}")
        zed = make_creator(db, "Zzz Group")
        for i in range(4):
            make_model(db, zed, name=f"Variant {i}", character="Boss")
        commit_all(db)

        resp = client.get("/models?group_variants=true&page=2&page_size=2&sort=creator")
        items = resp.json()["items"]
        boss = next(i for i in items if i["character"] == "Boss")
        assert boss["variant_count"] == 4

    def test_group_representative_prefers_thumbnail(self, client, db):
        creator = make_creator(db, "Creator")
        # v1 has no thumbnail, v2 has one — v2 should be representative
        make_model(db, creator, name="No_thumb", character="Hero", thumbnail_path=None)
        v2 = make_model(db, creator, name="Has_thumb", character="Hero", thumbnail_path="/tmp/thumb.jpg")
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        item = resp.json()["items"][0]
        assert item["id"] == v2.id

    def test_group_representative_promotes_favorited(self, client, db):
        # #302 auto-promotion: a favorited member outranks a merely-thumbnailed
        # one so its ⭐ chip shows on the Library card.
        creator = make_creator(db, "Creator")
        make_model(db, creator, name="Has_thumb", character="Hero", thumbnail_path="/tmp/t.jpg")
        fav = make_model(db, creator, name="Favorited", character="Hero")
        fav.is_favorite = True
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        assert resp.json()["items"][0]["id"] == fav.id

    def test_group_representative_promotes_queued(self, client, db):
        # A queued member also auto-promotes so its 🖨 chip is visible.
        creator = make_creator(db, "Creator")
        make_model(db, creator, name="Has_thumb", character="Hero", thumbnail_path="/tmp/t.jpg")
        queued = make_model(db, creator, name="Queued", character="Hero")
        queued.print_status = "queued"
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        assert resp.json()["items"][0]["id"] == queued.id

    def test_designated_rep_still_wins_over_favorited(self, client, db):
        # An explicit user-set rep (#193) outranks auto-promotion (#302).
        creator = make_creator(db, "Creator")
        pick = make_model(db, creator, name="Designated", character="Hero")
        fav = make_model(db, creator, name="Favorited", character="Hero")
        fav.is_favorite = True
        commit_all(db)

        client.patch(f"/models/{pick.id}/group-rep", json={"is_group_rep": True})
        resp = client.get("/models?group_variants=true")
        assert resp.json()["items"][0]["id"] == pick.id


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

    def test_thumbnailed_models_sort_before_no_thumbnail(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="A_no_thumb", character="Rocky")
        make_model(db, creator, name="B_has_thumb", character="Rocky", thumbnail_path="/img/b.jpg")
        make_model(db, creator, name="C_no_thumb", character="Rocky")
        commit_all(db)

        resp = client.get(f"/models/variants?creator_id={creator.id}&character=Rocky")
        assert resp.status_code == 200
        names = [item["name"] for item in resp.json()["items"]]
        # B has a thumbnail — must appear before both no-thumb models
        assert names.index("B_has_thumb") < names.index("A_no_thumb")
        assert names.index("B_has_thumb") < names.index("C_no_thumb")


# ---------------------------------------------------------------------------
# Manual variant ordering (#399)
# ---------------------------------------------------------------------------

class TestGroupReorder:
    def _trio(self, db):
        creator = make_creator(db, "Creator")
        v1 = make_model(db, creator, name="V1", character="Hero")
        v2 = make_model(db, creator, name="V2", character="Hero")
        v3 = make_model(db, creator, name="V3", character="Hero")
        commit_all(db)
        return creator, v1, v2, v3

    def test_reorder_sets_rep_and_group_order(self, client, db):
        creator, v1, v2, v3 = self._trio(db)
        resp = client.patch(
            "/models/group/reorder",
            json={"creator_id": creator.id, "character": "Hero", "ids": [v3.id, v1.id, v2.id]},
        )
        assert resp.status_code == 200 and resp.json()["updated"] == 3

        # The dragged front model represents the group on the Library grid.
        grid = client.get("/models?group_variants=true").json()["items"]
        assert grid[0]["id"] == v3.id
        # The group page shows the manual order.
        order = [m["id"] for m in client.get(
            f"/models/variants?creator_id={creator.id}&character=Hero"
        ).json()["items"]]
        assert order == [v3.id, v1.id, v2.id]

    def test_empty_ids_resets_to_heuristic(self, client, db):
        creator, v1, v2, v3 = self._trio(db)
        client.patch(
            "/models/group/reorder",
            json={"creator_id": creator.id, "character": "Hero", "ids": [v3.id, v1.id, v2.id]},
        )
        reset = client.patch(
            "/models/group/reorder",
            json={"creator_id": creator.id, "character": "Hero", "ids": []},
        )
        assert reset.status_code == 200 and reset.json()["reset"] is True

        # Heuristic resumes — lowest id (no thumbnails/flags) represents the group.
        grid = client.get("/models?group_variants=true").json()["items"]
        assert grid[0]["id"] == v1.id

    def test_designated_rep_still_wins_over_manual_order(self, client, db):
        creator, v1, v2, v3 = self._trio(db)
        client.patch(f"/models/{v2.id}/group-rep", json={"is_group_rep": True})
        client.patch(
            "/models/group/reorder",
            json={"creator_id": creator.id, "character": "Hero", "ids": [v3.id, v1.id, v2.id]},
        )
        grid = client.get("/models?group_variants=true").json()["items"]
        assert grid[0]["id"] == v2.id  # explicit rep beats drag order

    def test_foreign_ids_ignored(self, client, db):
        creator, v1, v2, v3 = self._trio(db)
        other = make_model(db, creator, name="Loner", character="Villain")
        commit_all(db)
        resp = client.patch(
            "/models/group/reorder",
            json={"creator_id": creator.id, "character": "Hero", "ids": [v2.id, other.id]},
        )
        # Only the 3 Hero members are touched; the foreign id is silently skipped.
        assert resp.status_code == 200 and resp.json()["updated"] == 3


# ---------------------------------------------------------------------------
# Group display thumbnail / representative override (#193)
# ---------------------------------------------------------------------------

class TestGroupRepOverride:
    def test_designated_rep_overrides_thumbnail_heuristic(self, client, db):
        creator = make_creator(db, "Creator")
        # v_other has a thumbnail and the lower id, so it would win by default.
        v_other = make_model(db, creator, name="A_has_thumb", character="Hero", thumbnail_path="/tmp/a.jpg")
        v_pick = make_model(db, creator, name="B_pick", character="Hero", thumbnail_path="/tmp/b.jpg")
        commit_all(db)

        # Default: lowest-id thumbnailed model represents the group.
        item = client.get("/models?group_variants=true").json()["items"][0]
        assert item["id"] == v_other.id

        resp = client.patch(f"/models/{v_pick.id}/group-rep", json={"is_group_rep": True})
        assert resp.status_code == 200
        assert resp.json()["is_group_rep"] is True

        item = client.get("/models?group_variants=true").json()["items"][0]
        assert item["id"] == v_pick.id

    def test_designating_rep_clears_siblings(self, client, db):
        creator = make_creator(db, "Creator")
        v1 = make_model(db, creator, name="V1", character="Hero")
        v2 = make_model(db, creator, name="V2", character="Hero")
        commit_all(db)

        client.patch(f"/models/{v1.id}/group-rep", json={"is_group_rep": True})
        client.patch(f"/models/{v2.id}/group-rep", json={"is_group_rep": True})

        # Only one member may carry the flag.
        data = client.get(f"/models/variants?creator_id={creator.id}&character=Hero").json()
        flagged = [m["id"] for m in data["items"] if m["is_group_rep"]]
        assert flagged == [v2.id]
        # The rep sorts first on the variants page.
        assert data["items"][0]["id"] == v2.id

    def test_clearing_rep_falls_back_to_heuristic(self, client, db):
        creator = make_creator(db, "Creator")
        v_thumb = make_model(db, creator, name="A_thumb", character="Hero", thumbnail_path="/tmp/a.jpg")
        v_pick = make_model(db, creator, name="B_pick", character="Hero")
        commit_all(db)

        client.patch(f"/models/{v_pick.id}/group-rep", json={"is_group_rep": True})
        assert client.get("/models?group_variants=true").json()["items"][0]["id"] == v_pick.id

        resp = client.patch(f"/models/{v_pick.id}/group-rep", json={"is_group_rep": False})
        assert resp.json()["is_group_rep"] is False
        # Heuristic resumes — the thumbnailed member represents the group.
        assert client.get("/models?group_variants=true").json()["items"][0]["id"] == v_thumb.id

    def test_rep_on_ungrouped_model_rejected(self, client, db):
        creator = make_creator(db, "Creator")
        loner = make_model(db, creator, name="Loner", character=None)
        commit_all(db)

        resp = client.patch(f"/models/{loner.id}/group-rep", json={"is_group_rep": True})
        assert resp.status_code == 400

    def test_rep_missing_model_404(self, client, db):
        resp = client.patch("/models/999999/group-rep", json={"is_group_rep": True})
        assert resp.status_code == 404


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
# Exclude / restore
# ---------------------------------------------------------------------------

class TestExclude:
    def test_excluded_model_hidden_from_list(self, client, db):
        creator = make_creator(db)
        keep = make_model(db, creator, name="Keep")
        drop = make_model(db, creator, name="Drop")
        commit_all(db)

        resp = client.patch(f"/models/{drop.id}/exclude", json={"excluded": True})
        assert resp.status_code == 200
        assert resp.json()["excluded"] is True

        data = client.get("/models").json()
        names = {i["name"] for i in data["items"]}
        assert names == {"Keep"}
        assert data["total"] == 1
        # The kept model is untouched.
        assert keep.id is not None

    def test_excluded_view_lists_only_excluded(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Keep")
        drop = make_model(db, creator, name="Drop")
        commit_all(db)
        client.patch(f"/models/{drop.id}/exclude", json={"excluded": True})

        data = client.get("/models?excluded=true").json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Drop"

    def test_restore_brings_model_back(self, client, db):
        creator = make_creator(db)
        drop = make_model(db, creator, name="Drop")
        commit_all(db)
        client.patch(f"/models/{drop.id}/exclude", json={"excluded": True})
        assert client.get("/models").json()["total"] == 0

        client.patch(f"/models/{drop.id}/exclude", json={"excluded": False})
        assert client.get("/models").json()["total"] == 1

    def test_excluded_drops_from_stats(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="A")
        drop = make_model(db, creator, name="B")
        commit_all(db)
        client.patch(f"/models/{drop.id}/exclude", json={"excluded": True})

        stats = client.get("/models/stats").json()
        assert stats["total"] == 1
        assert stats["excluded"] == 1

    def test_excluding_clears_queue_state(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="Queued")
        commit_all(db)
        client.patch(f"/models/{m.id}/print-status", json={"status": "queued"})

        client.patch(f"/models/{m.id}/exclude", json={"excluded": True})
        db.refresh(m)
        assert m.print_status == "none"
        assert m.queue_position is None

    def test_exclude_unknown_model_returns_404(self, client):
        resp = client.patch("/models/99999/exclude", json={"excluded": True})
        assert resp.status_code == 404


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

        # Verify it's stored with original casing (no longer lowercased)
        db.refresh(stl)
        assert stl.part_type == "Head"

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
        resp = client.get("/models?print_status=queued&sort=queue&group_variants=false")
        assert resp.status_code == 200
        return [i["name"] for i in resp.json()["items"]]

    def test_favorites_float_to_top(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        c = make_model(db, creator, name="C")
        for m, pos in ((a, 0), (b, 1), (c, 2)):
            m.print_status = "queued"
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
            client.patch(f"/models/{m.id}/print-status", json={"status": "queued"})

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
            client.patch(f"/models/{m.id}/print-status", json={"status": "queued"})
        # Manual order A, B; favorite B -> B floats to top.
        client.patch(f"/models/{b.id}/favorite", json={"is_favorite": True})

        assert self._queue_names(client) == ["B", "A"]


class TestPrintStatusLifecycle:
    """Print count must reflect real prints, not click history (#379)."""

    def _set(self, client, model_id, status):
        resp = client.patch(f"/models/{model_id}/print-status", json={"status": status})
        assert resp.status_code == 200
        return resp.json()

    def test_marking_printed_sets_count_and_timestamp(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="A")
        commit_all(db)

        body = self._set(client, m.id, "printed")
        assert body["print_count"] == 1
        db.refresh(m)
        assert m.printed_at is not None

    def test_re_setting_printed_does_not_inflate_count(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="A")
        commit_all(db)

        self._set(client, m.id, "printed")
        body = self._set(client, m.id, "printed")
        assert body["print_count"] == 1

    def test_reverting_from_printed_decrements_and_clears_timestamp(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="A")
        commit_all(db)

        self._set(client, m.id, "printed")
        body = self._set(client, m.id, "none")
        assert body["print_count"] == 0
        db.refresh(m)
        assert m.printed_at is None
        assert m.print_status == "none"

    def test_revert_never_drives_count_negative(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="A")
        commit_all(db)

        # Two accidental advances through to printed, then back out.
        self._set(client, m.id, "printed")
        self._set(client, m.id, "none")
        body = self._set(client, m.id, "printing")  # leaving 'none', not 'printed'
        assert body["print_count"] == 0


# ---------------------------------------------------------------------------
# Neighbors endpoint
# ---------------------------------------------------------------------------

class TestGetNeighbors:
    def test_middle_model_has_both_neighbors(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        c = make_model(db, creator, name="Gamma")
        commit_all(db)

        resp = client.get(f"/models/{b.id}/neighbors?group_variants=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["prev_id"] == a.id
        assert data["next_id"] == c.id

    def test_first_model_has_no_prev(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        make_model(db, creator, name="Beta")
        commit_all(db)

        resp = client.get(f"/models/{a.id}/neighbors?group_variants=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["prev_id"] is None
        assert data["next_id"] is not None

    def test_last_model_has_no_next(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Alpha")
        b = make_model(db, creator, name="Beta")
        commit_all(db)

        resp = client.get(f"/models/{b.id}/neighbors?group_variants=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["prev_id"] is not None
        assert data["next_id"] is None

    def test_only_model_has_no_neighbors(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Solo")
        commit_all(db)

        resp = client.get(f"/models/{a.id}/neighbors?group_variants=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["prev_id"] is None
        assert data["next_id"] is None

    def test_respects_search_filter(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha Dragon")
        make_model(db, creator, name="Beta Goblin")
        c = make_model(db, creator, name="Gamma Dragon")
        commit_all(db)

        # With "dragon" filter, only Alpha and Gamma are in the list.
        resp = client.get(f"/models/{c.id}/neighbors?q=dragon&group_variants=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["prev_id"] == a.id
        assert data["next_id"] is None

    def test_unknown_model_returns_nulls(self, client):
        resp = client.get("/models/99999/neighbors?group_variants=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["prev_id"] is None
        assert data["next_id"] is None

    def test_grouped_variant_resolved_to_representative(self, client, db):
        creator = make_creator(db)
        # Two standalone models (no character) and a variant group (Rep + NonRep).
        ace = make_model(db, creator, name="Ace")
        rep = make_model(db, creator, name="Rep", character="Hero")
        non_rep = make_model(db, creator, name="NonRep", character="Hero")
        zed = make_model(db, creator, name="Zed")
        commit_all(db)

        # Default sort: ORDER BY character, name. SQLite NULLs sort first (ASC),
        # so the grouped visible list is: Ace, Zed (both NULL-character), then Rep.
        resp = client.get(f"/models/{non_rep.id}/neighbors")
        assert resp.status_code == 200
        data = resp.json()
        # non_rep resolves to rep; rep is last, so prev=Zed, next=None.
        assert data["prev_id"] == zed.id
        assert data["next_id"] is None


# ---------------------------------------------------------------------------
# Thumbnail upload
# ---------------------------------------------------------------------------

class TestThumbnailUpload:
    def test_upload_png_sets_thumbnail_path(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator, name="NoThumb")
        db.commit()

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # minimal fake PNG header
        resp = client.post(
            f"/models/{model.id}/thumbnail/upload",
            files={"file": ("capture.png", png_bytes, "image/png")},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        db.refresh(model)
        assert model.thumbnail_path is not None
        assert model.thumbnail_path.endswith(".png")
        assert model.thumbnail_url is None

    def test_upload_clears_existing_url(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator, name="HasURL")
        model.thumbnail_url = "https://example.com/thumb.jpg"
        db.commit()

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        resp = client.post(
            f"/models/{model.id}/thumbnail/upload",
            files={"file": ("capture.png", png_bytes, "image/png")},
        )
        assert resp.status_code == 200

        db.refresh(model)
        assert model.thumbnail_url is None
        assert model.thumbnail_path is not None

    def test_upload_unknown_model_returns_404(self, client):
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        resp = client.post(
            "/models/99999/thumbnail/upload",
            files={"file": ("capture.png", png_bytes, "image/png")},
        )
        assert resp.status_code == 404

    def test_upload_rejects_non_image(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        db.commit()

        resp = client.post(
            f"/models/{model.id}/thumbnail/upload",
            files={"file": ("bad.txt", b"not an image", "text/plain")},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Exclude filters (#204 / #205)
# ---------------------------------------------------------------------------

class TestExcludeFilters:
    def _tagged_model(self, db, creator, name, tags):
        m = make_model(db, creator, name=name, tags=tags)
        sync_model_tags(m, db)
        return m

    def test_exclude_creator_hides_their_models(self, client, db):
        creator_a = make_creator(db, "Creator A")
        creator_b = make_creator(db, "Creator B")
        make_model(db, creator_a, name="A Model")
        make_model(db, creator_b, name="B Model")
        commit_all(db)

        resp = client.get(f"/models?exclude_creator_id={creator_a.id}")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "B Model"

    def test_exclude_creator_keeps_creatorless_models(self, client, db):
        """SQL != drops NULL rows — models without a creator must stay visible."""
        creator = make_creator(db, "Creator A")
        make_model(db, creator, name="A Model")
        orphan = make_model(db, creator, name="Orphan Model")
        orphan.creator_id = None
        commit_all(db)

        resp = client.get(f"/models?exclude_creator_id={creator.id}")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Orphan Model"

    def test_exclude_tag_hides_tagged_models(self, client, db):
        creator = make_creator(db)
        self._tagged_model(db, creator, "Statue Model", ["statue"])
        self._tagged_model(db, creator, "Mini Model", ["miniature"])
        make_model(db, creator, name="Untagged Model")
        commit_all(db)

        resp = client.get("/models?exclude_tag=statue")
        data = resp.json()
        assert data["total"] == 2
        names = {m["name"] for m in data["items"]}
        assert names == {"Mini Model", "Untagged Model"}

    def test_exclude_tag_normalizes_case_and_whitespace(self, client, db):
        creator = make_creator(db)
        self._tagged_model(db, creator, "Statue Model", ["statue"])
        make_model(db, creator, name="Other Model")
        commit_all(db)

        resp = client.get("/models?exclude_tag=%20Statue%20")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Other Model"

    def test_include_and_exclude_combine(self, client, db):
        """creator_id=A + exclude_tag narrows within the included creator."""
        creator_a = make_creator(db, "Creator A")
        creator_b = make_creator(db, "Creator B")
        self._tagged_model(db, creator_a, "A Statue", ["statue"])
        make_model(db, creator_a, name="A Plain")
        make_model(db, creator_b, name="B Plain")
        commit_all(db)

        resp = client.get(f"/models?creator_id={creator_a.id}&exclude_tag=statue")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "A Plain"

    def test_neighbors_honor_exclude_filters(self, client, db):
        """Prev/Next must skip models hidden by the exclude filters."""
        creator_a = make_creator(db, "Creator A")
        creator_b = make_creator(db, "Creator B")
        # Names sort alphabetically: Alpha < Bravo < Charlie.
        first = make_model(db, creator_a, name="Alpha")
        middle = make_model(db, creator_b, name="Bravo")
        last = make_model(db, creator_a, name="Charlie")
        commit_all(db)

        resp = client.get(
            f"/models/{first.id}/neighbors?exclude_creator_id={creator_b.id}"
        )
        data = resp.json()
        assert data["next_id"] == last.id

        # Same skip via exclude_tag: tag the middle model and exclude that tag.
        middle.tags = ["statue"]
        sync_model_tags(middle, db)
        commit_all(db)
        resp = client.get(f"/models/{first.id}/neighbors?exclude_tag=statue")
        assert resp.json()["next_id"] == last.id

    def test_exclude_printed_hides_printed_models(self, client, db):
        creator = make_creator(db)
        printed = make_model(db, creator, name="Printed Model")
        printed.print_status = "printed"
        make_model(db, creator, name="Queued Model").print_status = "queued"
        make_model(db, creator, name="Unprinted Model")
        commit_all(db)

        resp = client.get("/models?exclude_printed=true")
        data = resp.json()
        assert data["total"] == 2
        names = {m["name"] for m in data["items"]}
        assert names == {"Queued Model", "Unprinted Model"}

    def test_exclude_printed_off_by_default(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Printed Model").print_status = "printed"
        make_model(db, creator, name="Unprinted Model")
        commit_all(db)

        resp = client.get("/models")
        assert resp.json()["total"] == 2

    def test_neighbors_honor_exclude_printed(self, client, db):
        """Prev/Next must skip printed models when exclude_printed is set."""
        creator = make_creator(db)
        first = make_model(db, creator, name="Alpha")
        make_model(db, creator, name="Bravo").print_status = "printed"
        last = make_model(db, creator, name="Charlie")
        commit_all(db)

        resp = client.get(f"/models/{first.id}/neighbors?exclude_printed=true")
        assert resp.json()["next_id"] == last.id


# ---------------------------------------------------------------------------
# Recently added (#170)
# ---------------------------------------------------------------------------

class TestRecentlyAdded:
    def _seed(self, db, ages_days):
        """Create one model per age (in days), named m0, m1, ... Returns the models."""
        from datetime import timedelta
        from app.utils import utcnow

        creator = make_creator(db)
        models = []
        for i, age in enumerate(ages_days):
            m = make_model(db, creator, name=f"m{i}")
            m.created_at = utcnow() - timedelta(days=age)
            models.append(m)
        commit_all(db)
        return models

    def test_added_within_days_excludes_older_models(self, client, db):
        self._seed(db, ages_days=[0, 3, 30])

        resp = client.get("/models?added_within_days=7")
        assert resp.status_code == 200
        names = {i["name"] for i in resp.json()["items"]}
        assert names == {"m0", "m1"}

    def test_sort_added_returns_newest_first(self, client, db):
        self._seed(db, ages_days=[5, 0, 2])

        resp = client.get("/models?sort=added")
        assert resp.status_code == 200
        names = [i["name"] for i in resp.json()["items"]]
        assert names == ["m1", "m2", "m0"]

    def test_added_within_days_bounds_rejected(self, client, db):
        assert client.get("/models?added_within_days=0").status_code == 422
        assert client.get("/models?added_within_days=366").status_code == 422

    def test_neighbors_respect_added_window(self, client, db):
        models = self._seed(db, ages_days=[0, 30, 1])

        # Within a 7-day window only m0 and m2 exist; sorted by added,
        # m0 (today) precedes m2 (yesterday) — m1 must be skipped entirely.
        resp = client.get(f"/models/{models[0].id}/neighbors?added_within_days=7&sort=added")
        assert resp.status_code == 200
        body = resp.json()
        assert body["prev_id"] is None
        assert body["next_id"] == models[2].id


class TestSortByCreator:
    def _seed(self, db):
        """Models across creators Zeta/Alpha plus one orphan (no creator)."""
        zeta = make_creator(db, "Zeta Studio")
        alpha = make_creator(db, "Alpha Forge")
        make_model(db, zeta, name="z-model")
        make_model(db, alpha, name="a-model")
        orphan = make_model(db, zeta, name="orphan")
        orphan.creator_id = None
        commit_all(db)

    def test_sort_creator_orders_alphabetically_orphan_last(self, client, db):
        self._seed(db)

        resp = client.get("/models?sort=creator&group_variants=false")
        assert resp.status_code == 200
        names = [i["name"] for i in resp.json()["items"]]
        # Alpha Forge before Zeta Studio; the creatorless model sorts last.
        assert names == ["a-model", "z-model", "orphan"]

    def test_neighbors_follow_creator_sort(self, client, db):
        self._seed(db)
        a_model = next(i for i in client.get("/models?sort=creator").json()["items"]
                       if i["name"] == "a-model")

        resp = client.get(f"/models/{a_model['id']}/neighbors?sort=creator&group_variants=false")
        assert resp.status_code == 200
        body = resp.json()
        assert body["prev_id"] is None  # first in creator order
        assert body["next_id"] is not None


# ---------------------------------------------------------------------------
# Bulk group assignment (#374) — rename / merge / split / ungroup primitive
# ---------------------------------------------------------------------------

class TestBatchSetGroup:
    def _override_for(self, db, model):
        from app.models import GroupOverride
        return (
            db.query(GroupOverride)
            .filter(GroupOverride.path == model.folder_path)
            .first()
        )

    def test_assigns_group_to_many(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        commit_all(db)

        resp = client.post(
            "/models/group/batch-set",
            json={"model_ids": [a.id, b.id], "character": "Goblin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["character"] == "Goblin"
        assert sorted(data["updated"]) == sorted([a.id, b.id])
        assert data["missing"] == []

        db.refresh(a); db.refresh(b)
        assert a.character == "Goblin"
        assert b.character == "Goblin"
        # Override persisted so the assignment survives a rescan.
        assert self._override_for(db, a).character == "Goblin"

    def test_merge_groups(self, client, db):
        """Members of group A reassigned to group B's character."""
        creator = make_creator(db)
        a1 = make_model(db, creator, name="A1", character="Akuma")
        a2 = make_model(db, creator, name="A2", character="Akuma")
        commit_all(db)

        resp = client.post(
            "/models/group/batch-set",
            json={"model_ids": [a1.id, a2.id], "character": "Ryu"},
        )
        assert resp.status_code == 200
        db.refresh(a1); db.refresh(a2)
        assert a1.character == "Ryu"
        assert a2.character == "Ryu"

    def test_ungroup_writes_null_override(self, client, db):
        """character=null is sticky ungroup (NULL override row), not deletion."""
        creator = make_creator(db)
        m = make_model(db, creator, name="M", character="Akuma")
        commit_all(db)

        resp = client.post(
            "/models/group/batch-set",
            json={"model_ids": [m.id], "character": None},
        )
        assert resp.status_code == 200
        assert resp.json()["character"] is None
        db.refresh(m)
        assert m.character is None
        ov = self._override_for(db, m)
        assert ov is not None and ov.character is None

    def test_blank_character_normalized_to_ungroup(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="M", character="Akuma")
        commit_all(db)

        resp = client.post(
            "/models/group/batch-set",
            json={"model_ids": [m.id], "character": "   "},
        )
        assert resp.status_code == 200
        assert resp.json()["character"] is None

    def test_empty_ids_is_400(self, client, db):
        resp = client.post(
            "/models/group/batch-set",
            json={"model_ids": [], "character": "Goblin"},
        )
        assert resp.status_code == 400

    def test_missing_ids_reported_others_updated(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="M")
        commit_all(db)

        resp = client.post(
            "/models/group/batch-set",
            json={"model_ids": [m.id, 999999], "character": "Goblin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == [m.id]
        assert data["missing"] == [999999]

    def test_409_when_scan_running(self, client, db, monkeypatch):
        from app.services import scanner
        creator = make_creator(db)
        m = make_model(db, creator, name="M")
        commit_all(db)

        monkeypatch.setattr(scanner, "get_status", lambda: {"running": True})
        resp = client.post(
            "/models/group/batch-set",
            json={"model_ids": [m.id], "character": "Goblin"},
        )
        assert resp.status_code == 409

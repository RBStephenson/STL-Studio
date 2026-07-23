"""
Tests for the /models API endpoints.

Covers: listing, search, variant grouping, variants endpoint,
        stats, bulk tag, model patch, STL file part_type.
"""
import pytest
from tests.conftest import make_creator, make_model, make_stl_file, make_variant_group
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

    def test_character_filter_underscore_not_wildcard(self, client, db):
        """STUDIO-34: `_` in the character query param must be matched
        literally, not as a SQL LIKE single-char wildcard."""
        creator = make_creator(db)
        make_model(db, creator, name="A", character="My_Guy")
        make_model(db, creator, name="B", character="MyXGuy")
        commit_all(db)

        resp = client.get("/models?character=My_Guy")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.json()["items"]}
        assert names == {"A"}

    def test_search_by_name(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Undead Knight")
        make_model(db, creator, name="Dragon Warrior")
        commit_all(db)

        resp = client.get("/models?q=undead")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Undead Knight"

    def test_search_ignores_description(self, client, db):
        """STUDIO-310: description is prose (scraped blurbs) and must not be
        substring-matched — "hank" matching "Thanks for downloading!" flooded
        results with unrelated models."""
        creator = make_creator(db)
        make_model(db, creator, name="Hank", description="A friendly fisherman.")
        make_model(
            db, creator, name="Unrelated Warrior",
            description="Thanks for downloading! Hope you enjoy.",
        )
        commit_all(db)

        resp = client.get("/models?q=hank")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Hank"

    def test_search_by_character_still_substring(self, client, db):
        """Non-prose identity fields (title/name/character) keep substring
        matching — e.g. "hulk" must still match "Hulkbuster"."""
        creator = make_creator(db)
        make_model(db, creator, name="A", character="Hulkbuster")
        make_model(db, creator, name="B", character="Someone Else")
        commit_all(db)

        resp = client.get("/models?q=hulk")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "A"

    def test_search_percent_not_wildcard(self, client, db):
        """STUDIO-87: `%` in the q query param must be matched literally,
        not as a SQL LIKE any-sequence wildcard."""
        creator = make_creator(db)
        make_model(db, creator, name="A", character="50% off today")
        make_model(db, creator, name="B", character="no discount here")
        commit_all(db)

        resp = client.get("/models?q=50%25")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.json()["items"]}
        assert names == {"A"}

    def test_search_underscore_not_wildcard(self, client, db):
        """STUDIO-87: `_` in the q query param must be matched literally,
        not as a SQL LIKE single-char wildcard."""
        creator = make_creator(db)
        make_model(db, creator, name="A", character="My_Guy stats")
        make_model(db, creator, name="B", character="MyXGuy stats")
        commit_all(db)

        resp = client.get("/models?q=My_Guy")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.json()["items"]}
        assert names == {"A"}

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
        """Create a creator with 3 durably-grouped variants under character='Akuma'
        (#678 Phase 3: a durable VariantGroup, not bare `character`, is what
        collapses at the read path — mirrors what a scan's regroup_creator pass
        leaves behind)."""
        creator = make_creator(db, "PolyMind")
        v1 = make_model(db, creator, name="Full_cutted", character="Akuma")
        v2 = make_model(db, creator, name="No_cuts", character="Akuma")
        v3 = make_model(db, creator, name="Semi_cutted", character="Akuma")
        db.flush()
        make_variant_group(db, creator, [v1, v2, v3], label="Akuma")
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
        # vc_map is scoped to the current page's variant_group_id set (#393);
        # a representative that lands on page 2 must still get its count.
        filler = make_creator(db, "Aaa Filler")
        for i in range(3):
            make_model(db, filler, name=f"Filler {i}", character=f"Solo{i}")
        zed = make_creator(db, "Zzz Group")
        boss_models = [make_model(db, zed, name=f"Variant {i}", character="Boss") for i in range(4)]
        db.flush()
        make_variant_group(db, zed, boss_models, label="Boss")
        commit_all(db)

        resp = client.get("/models?group_variants=true&page=2&page_size=2&sort=creator")
        items = resp.json()["items"]
        boss = next(i for i in items if i["character"] == "Boss")
        assert boss["variant_count"] == 4

    def test_group_representative_prefers_thumbnail(self, client, db):
        creator = make_creator(db, "Creator")
        # v1 has no thumbnail, v2 has one — v2 should be representative
        v1 = make_model(db, creator, name="No_thumb", character="Hero", thumbnail_path=None)
        v2 = make_model(db, creator, name="Has_thumb", character="Hero", thumbnail_path="/tmp/thumb.jpg")
        db.flush()
        make_variant_group(db, creator, [v1, v2], label="Hero", heuristic_rep=True)
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        item = resp.json()["items"][0]
        assert item["id"] == v2.id

    def test_group_representative_promotes_favorited(self, client, db):
        # #302 auto-promotion: a favorited member outranks a merely-thumbnailed
        # one so its ⭐ chip shows on the Library card.
        creator = make_creator(db, "Creator")
        v1 = make_model(db, creator, name="Has_thumb", character="Hero", thumbnail_path="/tmp/t.jpg")
        fav = make_model(db, creator, name="Favorited", character="Hero")
        fav.is_favorite = True
        db.flush()
        make_variant_group(db, creator, [v1, fav], label="Hero", heuristic_rep=True)
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        assert resp.json()["items"][0]["id"] == fav.id

    def test_group_representative_promotes_queued(self, client, db):
        # A queued member also auto-promotes so its 🖨 chip is visible.
        creator = make_creator(db, "Creator")
        v1 = make_model(db, creator, name="Has_thumb", character="Hero", thumbnail_path="/tmp/t.jpg")
        queued = make_model(db, creator, name="Queued", character="Hero")
        queued.print_status = "queued"
        db.flush()
        make_variant_group(db, creator, [v1, queued], label="Hero", heuristic_rep=True)
        commit_all(db)

        resp = client.get("/models?group_variants=true")
        assert resp.json()["items"][0]["id"] == queued.id

    def test_designated_rep_still_wins_over_favorited(self, client, db):
        # An explicit user-set rep (#193) outranks auto-promotion (#302).
        creator = make_creator(db, "Creator")
        pick = make_model(db, creator, name="Designated", character="Hero")
        fav = make_model(db, creator, name="Favorited", character="Hero")
        fav.is_favorite = True
        db.flush()
        make_variant_group(db, creator, [pick, fav], label="Hero", heuristic_rep=True)
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

        resp = client.get("/models/variants?creator_id=9999&character=Akuma")
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
        db.flush()
        make_variant_group(db, creator, [v1, v2, v3], label="Hero", heuristic_rep=True)
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
        db.flush()
        make_variant_group(db, creator, [v_other, v_pick], label="Hero", heuristic_rep=True)
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
        db.flush()
        make_variant_group(db, creator, [v1, v2], label="Hero", heuristic_rep=True)
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
        db.flush()
        make_variant_group(db, creator, [v_thumb, v_pick], label="Hero", heuristic_rep=True)
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

    def test_designating_rep_updates_durable_group_rep(self, client, db):
        """STUDIO-7: rep resolution for durable groups reads
        VariantGroup.rep_model_id, not the legacy is_group_rep flag (#678).
        Designating a new rep via the group-rep button must flip the durable
        field too, or Library/Prev-Next paging keep showing the old rep."""
        from app.models import VariantGroup

        creator = make_creator(db, "Creator")
        v_other = make_model(db, creator, name="A_rep", character="Hero")
        v_pick = make_model(db, creator, name="B_pick", character="Hero")
        db.flush()
        group = make_variant_group(db, creator, [v_other, v_pick], label="Hero", rep=v_other)
        commit_all(db)
        assert group.rep_model_id == v_other.id

        resp = client.patch(f"/models/{v_pick.id}/group-rep", json={"is_group_rep": True})
        assert resp.status_code == 200

        db.expire_all()
        assert db.get(VariantGroup, group.id).rep_model_id == v_pick.id
        # Reflected everywhere rep resolution is authoritative, not just the flag.
        assert client.get("/models?group_variants=true").json()["items"][0]["id"] == v_pick.id


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

    def test_reassigning_creator_prunes_the_now_empty_old_one(self, client, db):
        """Regression (#1108): single-pack import creates a placeholder
        Creator named after the pack folder. Editing a model's creator here
        (a single-model equivalent of Import Preview's bulk-enrich Creator
        field) must not leave that now-empty placeholder behind."""
        from app.models import Creator
        old_creator = make_creator(db, name="Ignisaurus Clan Warriors Tactical Squad")
        model = make_model(db, old_creator)
        commit_all(db)

        resp = client.patch(f"/models/{model.id}", json={"creator_name": "dakkadakka.store"})
        assert resp.status_code == 200
        assert db.query(Creator).filter_by(id=old_creator.id).first() is None

    def test_reassigning_creator_leaves_a_still_used_one_alone(self, client, db):
        from app.models import Creator
        shared_creator = make_creator(db, name="Shared Creator")
        model = make_model(db, shared_creator)
        other_model = make_model(db, shared_creator, name="Other")
        commit_all(db)

        resp = client.patch(f"/models/{model.id}", json={"creator_name": "New Creator"})
        assert resp.status_code == 200
        assert db.query(Creator).filter_by(id=shared_creator.id).first() is not None
        assert other_model.creator_id == shared_creator.id


# ---------------------------------------------------------------------------
# DELETE /models/{id}/other-files (#880)
# ---------------------------------------------------------------------------

def _register_root(db, path) -> None:
    from app.models import ScanRoot
    db.add(ScanRoot(path=str(path), enabled=True))
    db.commit()


class TestDeleteOtherFile:
    def test_deletes_file_from_disk_and_db(self, client, db, tmp_path):
        _register_root(db, tmp_path)
        creator = make_creator(db)
        model = make_model(db, creator)
        doc = tmp_path / "datapackage.json"
        doc.write_text("{}")
        model.other_files = [str(doc)]
        commit_all(db)

        resp = client.request(
            "DELETE", f"/models/{model.id}/other-files", json={"path": str(doc)},
        )
        assert resp.status_code == 200
        assert not doc.exists()

        detail = client.get(f"/models/{model.id}").json()
        assert detail["other_files"] == []

    def test_missing_file_on_disk_still_clears_the_db_entry(self, client, db, tmp_path):
        """Regression: a file removed outside the app (or by a prior partial
        operation) must not leave a stale entry that can never be cleared."""
        _register_root(db, tmp_path)
        creator = make_creator(db)
        model = make_model(db, creator)
        gone = tmp_path / "datapackage.json"  # never created on disk
        model.other_files = [str(gone)]
        commit_all(db)

        resp = client.request(
            "DELETE", f"/models/{model.id}/other-files", json={"path": str(gone)},
        )
        assert resp.status_code == 200

        detail = client.get(f"/models/{model.id}").json()
        assert detail["other_files"] == []

    def test_rejects_path_outside_known_roots(self, client, db, tmp_path):
        creator = make_creator(db)
        model = make_model(db, creator)
        outside = tmp_path / "outside" / "datapackage.json"
        (tmp_path / "outside").mkdir()
        outside.write_text("{}")
        model.other_files = [str(outside)]
        commit_all(db)
        # No scan root registered → guard rejects.

        resp = client.request(
            "DELETE", f"/models/{model.id}/other-files", json={"path": str(outside)},
        )
        assert resp.status_code == 400
        assert outside.exists()  # untouched

        detail = client.get(f"/models/{model.id}").json()
        assert detail["other_files"] == [str(outside)]  # untouched

    def test_rejects_path_not_on_this_model(self, client, db, tmp_path):
        _register_root(db, tmp_path)
        creator = make_creator(db)
        model = make_model(db, creator)
        model.other_files = []
        commit_all(db)

        resp = client.request(
            "DELETE", f"/models/{model.id}/other-files",
            json={"path": str(tmp_path / "not-listed.json")},
        )
        assert resp.status_code == 404

    def test_unknown_model_returns_404(self, client):
        resp = client.request(
            "DELETE", "/models/99999/other-files", json={"path": "/x/y.json"},
        )
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
# STL file sup_of_id validation
# ---------------------------------------------------------------------------

class TestSTLFileSupOfId:
    def test_valid_same_model_link_accepted(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        base = make_stl_file(db, model, filename="Body.stl")
        sup = make_stl_file(db, model, filename="Sup_Body.stl")
        commit_all(db)

        resp = client.patch(f"/models/stl-files/{sup.id}", json={"sup_of_id": base.id})
        assert resp.status_code == 200
        db.refresh(sup)
        assert sup.sup_of_id == base.id

    def test_clear_sup_link_accepted(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        base = make_stl_file(db, model, filename="Body.stl")
        sup = make_stl_file(db, model, filename="Sup_Body.stl")
        sup.sup_of_id = base.id
        commit_all(db)

        resp = client.patch(f"/models/stl-files/{sup.id}", json={"sup_of_id": None})
        assert resp.status_code == 200
        db.refresh(sup)
        assert sup.sup_of_id is None

    def test_self_link_rejected(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        stl = make_stl_file(db, model, filename="Body.stl")
        commit_all(db)

        resp = client.patch(f"/models/stl-files/{stl.id}", json={"sup_of_id": stl.id})
        assert resp.status_code == 400
        assert "itself" in resp.json()["detail"]

    def test_nonexistent_target_rejected(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        stl = make_stl_file(db, model, filename="Body.stl")
        commit_all(db)

        resp = client.patch(f"/models/stl-files/{stl.id}", json={"sup_of_id": 99999})
        assert resp.status_code == 400
        assert "nonexistent" in resp.json()["detail"]

    def test_cross_model_link_rejected(self, client, db):
        creator = make_creator(db)
        model_a = make_model(db, creator, name="ModelA")
        model_b = make_model(db, creator, name="ModelB")
        base = make_stl_file(db, model_a, filename="Body.stl")
        sup = make_stl_file(db, model_b, filename="Sup_Body.stl")
        commit_all(db)

        resp = client.patch(f"/models/stl-files/{sup.id}", json={"sup_of_id": base.id})
        assert resp.status_code == 400
        assert "same model" in resp.json()["detail"]


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

    def test_neighbors_hide_inbox_models_by_default(self, client, db):
        """STUDIO-325: the grid hides inbox models by default (list_models
        is_inbox=False); neighbors must walk the same set, not skip through
        inbox cards the grid never showed."""
        creator = make_creator(db)
        a = make_model(db, creator, name="Alpha")
        boxed = make_model(db, creator, name="Boxed")
        boxed.is_inbox = True
        c = make_model(db, creator, name="Gamma")
        commit_all(db)

        resp = client.get(f"/models/{a.id}/neighbors?group_variants=false")
        assert resp.status_code == 200
        # Next hops straight to Gamma — the inbox model is invisible, exactly
        # as it is on the grid.
        assert resp.json()["next_id"] == c.id

        # Explicit inbox view still works: the inbox model is the whole set.
        resp = client.get(f"/models/{boxed.id}/neighbors?group_variants=false&is_inbox=true")
        assert resp.status_code == 200
        assert resp.json() == {"prev_id": None, "next_id": None}

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
        # Two standalone models (no character) and a durable variant group (Rep + NonRep).
        make_model(db, creator, name="Ace")
        rep = make_model(db, creator, name="Rep", character="Hero")
        non_rep = make_model(db, creator, name="NonRep", character="Hero")
        zed = make_model(db, creator, name="Zed")
        db.flush()
        make_variant_group(db, creator, [rep, non_rep], label="Hero", rep=rep)
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
# Thumbnail update
# ---------------------------------------------------------------------------

class TestThumbnailUpdate:
    def test_patch_updates_timestamp_for_cache_busting(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator, name="NoThumb")
        db.commit()
        before = model.updated_at

        resp = client.patch(
            f"/models/{model.id}/thumbnail",
            json={"thumbnail_path": "/data/thumbnails/new.png", "thumbnail_url": None},
        )

        assert resp.status_code == 200
        db.refresh(model)
        assert model.thumbnail_path == "/data/thumbnails/new.png"
        assert model.updated_at > before


# ---------------------------------------------------------------------------
# Thumbnail upload
# ---------------------------------------------------------------------------

class TestThumbnailUpload:
    def test_upload_png_sets_thumbnail_path(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator, name="NoThumb")
        db.commit()
        before = model.updated_at

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
        assert model.updated_at > before

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

    def test_upload_jpeg_uses_matching_extension(self, client, db):
        """A non-PNG upload must be saved with its own extension, not mislabeled
        .png — otherwise the stored bytes and the file's extension disagree."""
        creator = make_creator(db)
        model = make_model(db, creator, name="JpegUpload")
        db.commit()

        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 16
        resp = client.post(
            f"/models/{model.id}/thumbnail/upload",
            files={"file": ("photo.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 200

        db.refresh(model)
        assert model.thumbnail_path.endswith(".jpg")

    def test_upload_gif_is_accepted(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator, name="GifUpload")
        db.commit()

        gif_bytes = b"GIF89a" + b"\x00" * 16
        resp = client.post(
            f"/models/{model.id}/thumbnail/upload",
            files={"file": ("anim.gif", gif_bytes, "image/gif")},
        )
        assert resp.status_code == 200

        db.refresh(model)
        assert model.thumbnail_path.endswith(".gif")

    def test_upload_rejects_oversized_file(self, client, db):
        creator = make_creator(db)
        model = make_model(db, creator, name="TooBig")
        db.commit()

        oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (15 * 1024 * 1024 + 1)
        resp = client.post(
            f"/models/{model.id}/thumbnail/upload",
            files={"file": ("big.png", oversized, "image/png")},
        )
        assert resp.status_code == 413


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

    def test_bounded_query_does_not_materialize_full_id_list(self, client, db, monkeypatch):
        """#86: neighbors must resolve via a bounded LAG/LEAD query, not by pulling
        every filtered ID into Python. Fail the test if that materialization path
        (Query.all() on an id-only query) is ever invoked again."""
        creator = make_creator(db)
        models = [make_model(db, creator, name=f"m{i:02d}") for i in range(20)]
        commit_all(db)

        from sqlalchemy.orm import Query as SAQuery

        original_all = SAQuery.all

        def _guarded_all(self):
            cols = getattr(self, "column_descriptions", [])
            if len(cols) == 1 and cols[0].get("name") == "id":
                pytest.fail("get_neighbors materialized the full filtered ID list")
            return original_all(self)

        monkeypatch.setattr(SAQuery, "all", _guarded_all)

        mid = models[10]
        resp = client.get(f"/models/{mid.id}/neighbors?group_variants=false")
        assert resp.status_code == 200
        body = resp.json()
        assert body["prev_id"] == models[9].id
        assert body["next_id"] == models[11].id


# ---------------------------------------------------------------------------
# Bulk group assignment (#374) — rename / merge / split / ungroup primitive
# ---------------------------------------------------------------------------

class TestParsedAttributeFilters:
    def _mk(self, db, creator, name, attrs):
        m = make_model(db, creator, name=name)
        m.parsed_attributes = attrs
        return m

    def test_filter_support_status(self, client, db):
        creator = make_creator(db)
        self._mk(db, creator, "Unsup", {"support_status": "unsupported"})
        self._mk(db, creator, "Presup", {"support_status": "pre-supported"})
        self._mk(db, creator, "Plain", {})
        commit_all(db)

        resp = client.get("/models?support_status=unsupported")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Unsup"

    def test_filter_slicer(self, client, db):
        creator = make_creator(db)
        self._mk(db, creator, "Lych", {"slicer": "lychee"})
        self._mk(db, creator, "Chitu", {"slicer": "chitubox"})
        commit_all(db)

        resp = client.get("/models?slicer=chitubox")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Chitu"

    def test_parsed_attributes_serialized(self, client, db):
        creator = make_creator(db)
        self._mk(db, creator, "M", {"support_status": "unsupported", "slicer": "lychee"})
        commit_all(db)

        resp = client.get("/models")
        item = resp.json()["items"][0]
        assert item["parsed_attributes"] == {"support_status": "unsupported", "slicer": "lychee"}

    def test_no_filter_returns_all(self, client, db):
        creator = make_creator(db)
        self._mk(db, creator, "A", {"support_status": "unsupported"})
        self._mk(db, creator, "B", {})
        commit_all(db)

        resp = client.get("/models")
        assert resp.json()["total"] == 2


class TestVariantGroupReadPath:
    """P2 (#616) / #678 Phase 3: grouping read path is driven solely by
    variant_group_id — character is no longer a grouping key."""

    def _group(self, db, creator, members, label="G", rep=None, source="auto"):
        from app.models import VariantGroup
        g = VariantGroup(creator_id=creator.id, label=label, source=source)
        db.add(g)
        db.flush()
        for m in members:
            m.variant_group_id = g.id
        g.rep_model_id = (rep or members[0]).id
        db.flush()
        return g

    def test_collapse_by_group_across_different_characters(self, client, db):
        # Two models with distinct characters but the same variant_group_id collapse
        # to one card — grouping is now driven by the group, not the character string.
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        self._group(db, creator, [a, b], rep=a)
        commit_all(db)

        data = client.get("/models?group_variants=true").json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == a.id
        assert data["items"][0]["variant_count"] == 2

    def test_null_group_no_longer_falls_back_to_character(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="x1", character="Goblin")
        make_model(db, creator, name="x2", character="Goblin")
        commit_all(db)

        data = client.get("/models?group_variants=true").json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["variant_count"] == 1

    def test_rep_model_id_is_the_survivor(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        self._group(db, creator, [a, b], rep=b)  # b designated rep
        commit_all(db)

        data = client.get("/models?group_variants=true").json()
        assert data["items"][0]["id"] == b.id

    def test_variants_endpoint_by_group_id(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        g = self._group(db, creator, [a, b])
        commit_all(db)

        data = client.get(f"/models/variants?group_id={g.id}").json()
        assert {it["id"] for it in data["items"]} == {a.id, b.id}

    def test_variants_endpoint_still_supports_character(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="x1", character="Goblin")
        make_model(db, creator, name="x2", character="Goblin")
        commit_all(db)

        data = client.get(f"/models/variants?creator_id={creator.id}&character=Goblin").json()
        assert data["total"] == 2


class TestGroupingKeyGoldens678:
    """#678 Phase 3 — `_group_key_sql` is now `vg:`-only; the `ch:` legacy
    fallback is gone. State 4 below is the deliberate, reviewed flip from the
    Phase 0 goldens this class replaces: a bare `character` value with no
    durable `variant_group_id` no longer collapses at the read path — by this
    point Phases 1-2 durably group every live character grouping on the next
    scan, so a bare `character` with no group is stale/pre-scan data, not a
    live grouping signal. (Phase 5 retired the user-character-override
    mechanism itself, so the old "state 3" — an override present but not yet
    durably grouped — no longer exists as a distinct case.)

    Grouping-key states (see models.py `_group_key_sql`):
      1. durable auto group     -> vg:<id>   (collapses)
      2. durable manual group   -> vg:<id>   (collapses)
      4. scanner-derived character, no durable group -> NULL key (never collapses)
      5. explicit ungroup / no character -> NULL key (never collapses)
    """

    def _group(self, db, creator, members, label="G", rep=None, source="auto"):
        from app.models import VariantGroup
        g = VariantGroup(creator_id=creator.id, label=label, source=source)
        db.add(g)
        db.flush()
        for m in members:
            m.variant_group_id = g.id
        g.rep_model_id = (rep or members[0]).id
        db.flush()
        return g

    def test_state1_auto_group_collapses_by_vg(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        self._group(db, creator, [a, b], source="auto")
        commit_all(db)
        data = client.get("/models?group_variants=true").json()
        assert data["total"] == 1
        assert data["items"][0]["variant_count"] == 2

    def test_state2_manual_group_collapses_by_vg(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        self._group(db, creator, [a, b], source="manual")
        commit_all(db)
        data = client.get("/models?group_variants=true").json()
        assert data["total"] == 1
        assert data["items"][0]["variant_count"] == 2

    def test_state4_scanner_derived_character_no_longer_collapses(self, client, db):
        # A bare shared character string with no durable variant_group_id (as the
        # scanner's name parser sets pre-scan-engine) no longer collapses.
        creator = make_creator(db)
        make_model(db, creator, name="x1", character="Goblin")
        make_model(db, creator, name="x2", character="Goblin")
        commit_all(db)
        data = client.get("/models?group_variants=true").json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["variant_count"] == 1

    def test_state5_no_character_never_collapses(self, client, db):
        creator = make_creator(db)
        make_model(db, creator, name="Solo A", character=None)
        make_model(db, creator, name="Solo B", character=None)
        commit_all(db)
        data = client.get("/models?group_variants=true").json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["variant_count"] == 1

    def test_vg_wins_over_character_when_both_present(self, client, db):
        # A model in a durable group whose members carry differing character values
        # still collapses by the group — character has no bearing on the key at all.
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        self._group(db, creator, [a, b], source="manual")
        commit_all(db)
        data = client.get("/models?group_variants=true").json()
        assert data["total"] == 1
        assert data["items"][0]["variant_count"] == 2


class TestManualGroupEndpoints:
    """P3 (#617): manual merge / split / relabel."""

    def test_merge_creates_manual_group(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        commit_all(db)

        resp = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id], "label": "My Group"})
        assert resp.status_code == 200
        g = resp.json()
        assert g["source"] == "manual"
        assert g["label"] == "My Group"
        db.refresh(a); db.refresh(b)
        assert a.variant_group_id == g["id"] == b.variant_group_id
        # character is a scanner-derived display attribute (#678 Phase 5) — the
        # durable group's own label carries the group name, not model.character.
        assert a.character == "Alpha"
        assert b.character == "Beta"

    def test_merge_clears_no_group_pin(self, client, db):
        """An explicit merge overrides an earlier "keep me out" pin (#678 Phase 5)."""
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        a.no_group = True
        commit_all(db)

        resp = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id]})
        assert resp.status_code == 200
        db.refresh(a)
        assert a.no_group is False

    def test_merge_requires_two_without_group_id(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        commit_all(db)
        resp = client.post("/models/groups/merge", json={"model_ids": [a.id]})
        assert resp.status_code == 400

    def test_merge_rejects_cross_creator(self, client, db):
        c1 = make_creator(db, "C1"); c2 = make_creator(db, "C2")
        a = make_model(db, c1, name="A")
        b = make_model(db, c2, name="B")
        commit_all(db)
        resp = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id]})
        assert resp.status_code == 400

    def test_merge_prunes_orphaned_auto_group(self, client, db):
        from app.models import VariantGroup
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        # a + b are in an auto group of two
        auto = VariantGroup(creator_id=creator.id, label="Auto", source="auto")
        db.add(auto); db.flush()
        a.variant_group_id = auto.id; b.variant_group_id = auto.id
        c = make_model(db, creator, name="C")
        commit_all(db)

        # Merge a + c into a new group → auto group drops to 1 member (b) → pruned.
        resp = client.post("/models/groups/merge", json={"model_ids": [a.id, c.id]})
        assert resp.status_code == 200
        assert db.get(VariantGroup, auto.id) is None
        db.refresh(b)
        assert b.variant_group_id is None

    def test_merge_repairs_dangling_rep_on_surviving_orphan_group(self, client, db):
        """STUDIO-26: if the model an old group's rep_model_id points to is the
        one that just got merged elsewhere, and the old group still has 2+
        members left, it must not keep pointing at a model it no longer has."""
        from app.models import VariantGroup
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        c = make_model(db, creator, name="C")
        auto = VariantGroup(creator_id=creator.id, label="Auto", source="auto", rep_model_id=None)
        db.add(auto); db.flush()
        a.variant_group_id = auto.id
        b.variant_group_id = auto.id
        c.variant_group_id = auto.id
        auto.rep_model_id = a.id  # rep is the model about to be merged away
        d = make_model(db, creator, name="D")
        commit_all(db)

        # Merge a + d into a new group → auto group drops to [b, c] (still 2+,
        # so it survives) but its rep_model_id still pointed at a.
        resp = client.post("/models/groups/merge", json={"model_ids": [a.id, d.id]})
        assert resp.status_code == 200

        db.expire_all()
        survivor = db.get(VariantGroup, auto.id)
        assert survivor is not None
        assert survivor.rep_model_id in {b.id, c.id}

    def test_merge_locked_from_rescan(self, client, db):
        from app.services import grouping
        from app.models import VariantGroup
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        commit_all(db)
        gid = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id]}).json()["id"]

        grouping.regroup_creator(db, creator.id)
        db.commit()

        grp = db.get(VariantGroup, gid)
        assert grp is not None and grp.source == "manual"
        db.refresh(a); db.refresh(b)
        assert a.variant_group_id == gid == b.variant_group_id

    def test_split_removes_members_and_keeps_group(self, client, db):
        from app.models import VariantGroup
        creator = make_creator(db)
        a = make_model(db, creator, name="A"); b = make_model(db, creator, name="B"); c = make_model(db, creator, name="C")
        commit_all(db)
        gid = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id, c.id]}).json()["id"]

        resp = client.post(f"/models/groups/{gid}/split", json={"model_ids": [c.id]})
        assert resp.status_code == 200
        db.refresh(c)
        assert c.variant_group_id is None
        assert db.get(VariantGroup, gid) is not None  # 2 left → survives

    def test_split_pins_removed_member_as_no_group(self, client, db):
        """#678 Phase 5: a split member must be pinned no_group=True, or the
        proposal engine would happily re-propose the same auto group on the
        next rescan. character is untouched — it's a scanner-owned display
        attribute now, not a grouping key."""
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Foo"); b = make_model(db, creator, name="B"); c = make_model(db, creator, name="C", character="Bar")
        commit_all(db)
        gid = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id, c.id], "label": "My Group"}).json()["id"]

        resp = client.post(f"/models/groups/{gid}/split", json={"model_ids": [c.id]})
        assert resp.status_code == 200
        db.refresh(c)
        assert c.no_group is True
        assert c.character == "Bar"  # untouched
        # Remaining members are unaffected — only the split model is pinned.
        db.refresh(a)
        assert a.no_group is False
        assert a.character == "Foo"

    def test_split_dissolves_group_below_two(self, client, db):
        from app.models import VariantGroup
        creator = make_creator(db)
        a = make_model(db, creator, name="A"); b = make_model(db, creator, name="B")
        commit_all(db)
        gid = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id]}).json()["id"]

        resp = client.post(f"/models/groups/{gid}/split", json={"model_ids": [b.id]})
        assert resp.status_code == 200
        assert db.get(VariantGroup, gid) is None
        db.refresh(a)
        assert a.variant_group_id is None

    def test_split_dissolve_pins_last_member_as_no_group_too(self, client, db):
        """When a split drops the group below 2 members, _prune_empty_group nulls
        variant_group_id on whoever is left — they must be pinned no_group=True
        too, not just the explicitly-split member."""
        creator = make_creator(db)
        a = make_model(db, creator, name="A"); b = make_model(db, creator, name="B")
        commit_all(db)
        gid = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id], "label": "My Group"}).json()["id"]

        resp = client.post(f"/models/groups/{gid}/split", json={"model_ids": [b.id]})
        assert resp.status_code == 200
        db.refresh(a)
        assert a.no_group is True

    def test_patch_label_and_rep(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A"); b = make_model(db, creator, name="B")
        commit_all(db)
        gid = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id]}).json()["id"]

        resp = client.patch(f"/models/groups/{gid}", json={"label": "Renamed", "rep_model_id": b.id})
        assert resp.status_code == 200
        g = resp.json()
        assert g["label"] == "Renamed"
        assert g["rep_model_id"] == b.id

    def test_patch_rep_must_be_member(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A"); b = make_model(db, creator, name="B")
        outsider = make_model(db, creator, name="Z")
        commit_all(db)
        gid = client.post("/models/groups/merge", json={"model_ids": [a.id, b.id]}).json()["id"]

        resp = client.patch(f"/models/groups/{gid}", json={"rep_model_id": outsider.id})
        assert resp.status_code == 400

    def test_group_rep_uses_durable_group_not_character(self, client, db):
        """Renamed/manual groups can contain members with different scanner
        characters. Setting the display thumbnail must clear siblings by
        variant_group_id, not by stale character labels."""
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        commit_all(db)
        client.post("/models/groups/merge", json={"model_ids": [a.id, b.id], "label": "Manual"})

        assert (
            client.patch(f"/models/{a.id}/group-rep", json={"is_group_rep": True}).status_code
            == 200
        )
        assert (
            client.patch(f"/models/{b.id}/group-rep", json={"is_group_rep": True}).status_code
            == 200
        )

        db.refresh(a); db.refresh(b)
        assert a.is_group_rep is False
        assert b.is_group_rep is True

    def test_reorder_uses_group_id_when_character_is_stale(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A", character="Alpha")
        b = make_model(db, creator, name="B", character="Beta")
        commit_all(db)
        gid = client.post(
            "/models/groups/merge",
            json={"model_ids": [a.id, b.id], "label": "Manual"},
        ).json()["id"]

        resp = client.patch(
            "/models/group/reorder",
            json={"group_id": gid, "ids": [b.id, a.id]},
        )

        assert resp.status_code == 200
        db.refresh(a); db.refresh(b)
        assert b.variant_order == 0
        assert a.variant_order == 1


class TestGroupingStrategy:
    """P4 (#618): per-subtree grouping strategy."""

    def test_set_off_ungroups_subtree(self, client, db):
        from app.models import VariantGroup, GroupingStrategy
        creator = make_creator(db)
        a = make_model(db, creator, name="Goblin Supported", character="Goblin")
        b = make_model(db, creator, name="Goblin Unsupported", character="Goblin")
        # Put them in an auto group so we can see "off" tear it down.
        g = VariantGroup(creator_id=creator.id, label="Goblin", source="auto")
        db.add(g); db.flush()
        a.variant_group_id = g.id; b.variant_group_id = g.id
        commit_all(db)
        parent = a.folder_path.rsplit("/", 1)[0]

        resp = client.post("/models/grouping-strategy", json={"path": parent, "strategy": "off"})
        assert resp.status_code == 200
        assert db.query(GroupingStrategy).filter_by(path=parent).count() == 1
        db.refresh(a); db.refresh(b)
        assert a.variant_group_id is None and b.variant_group_id is None

    def test_set_auto_clears_override(self, client, db):
        from app.models import GroupingStrategy
        creator = make_creator(db)
        a = make_model(db, creator, name="X")
        commit_all(db)
        parent = a.folder_path.rsplit("/", 1)[0]
        db.add(GroupingStrategy(path=parent, strategy="off")); commit_all(db)

        resp = client.post("/models/grouping-strategy", json={"path": parent, "strategy": "auto"})
        assert resp.status_code == 200
        assert db.query(GroupingStrategy).filter_by(path=parent).count() == 0

    def test_get_effective_strategy_nearest_ancestor(self, client, db):
        from app.models import GroupingStrategy
        db.add(GroupingStrategy(path="/lib/Creator", strategy="off"))
        db.add(GroupingStrategy(path="/lib/Creator/sub", strategy="auto"))
        commit_all(db)

        r1 = client.get("/models/grouping-strategy", params={"path": "/lib/Creator/sub/Model"}).json()
        assert r1["strategy"] == "auto"
        r2 = client.get("/models/grouping-strategy", params={"path": "/lib/Creator/other/Model"}).json()
        assert r2["strategy"] == "off"
        r3 = client.get("/models/grouping-strategy", params={"path": "/elsewhere/Model"}).json()
        assert r3["strategy"] == "auto"

    def test_invalid_strategy_rejected(self, client, db):
        resp = client.post("/models/grouping-strategy", json={"path": "/x", "strategy": "bogus"})
        assert resp.status_code == 400

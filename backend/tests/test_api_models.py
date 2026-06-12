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
        client.patch(f"/models/{m.id}/queue", json={"in_queue": True})

        client.patch(f"/models/{m.id}/exclude", json={"excluded": True})
        db.refresh(m)
        assert m.in_queue is False
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

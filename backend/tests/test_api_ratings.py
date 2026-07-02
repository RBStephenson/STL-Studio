"""Tests for user star ratings: set/clear, filter, and sort (#167)."""
from tests.conftest import make_creator, make_model


# ---------------------------------------------------------------------------
# PATCH /models/{id}/rating
# ---------------------------------------------------------------------------

class TestSetRating:
    def test_set_rating(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="Hero")
        db.commit()
        r = client.patch(f"/models/{m.id}/rating", json={"rating": 4})
        assert r.status_code == 200
        assert r.json()["user_rating"] == 4
        db.refresh(m)
        assert m.user_rating == 4

    def test_clear_rating(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="Hero")
        db.commit()
        client.patch(f"/models/{m.id}/rating", json={"rating": 5})
        r = client.patch(f"/models/{m.id}/rating", json={"rating": None})
        assert r.status_code == 200
        assert r.json()["user_rating"] is None
        db.refresh(m)
        assert m.user_rating is None

    def test_rating_in_model_read(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="Hero")
        db.commit()
        client.patch(f"/models/{m.id}/rating", json={"rating": 3})
        body = client.get(f"/models/{m.id}").json()
        assert body["user_rating"] == 3

    def test_rating_below_range_rejected(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="Hero")
        db.commit()
        assert client.patch(f"/models/{m.id}/rating", json={"rating": 0}).status_code == 422

    def test_rating_above_range_rejected(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="Hero")
        db.commit()
        assert client.patch(f"/models/{m.id}/rating", json={"rating": 6}).status_code == 422

    def test_unknown_model_returns_404(self, client):
        assert client.patch("/models/99999/rating", json={"rating": 3}).status_code == 404


# ---------------------------------------------------------------------------
# GET /models?min_rating=
# ---------------------------------------------------------------------------

class TestRatingFilter:
    def _rated_set(self, client, db):
        creator = make_creator(db)
        low = make_model(db, creator, name="Low")
        mid = make_model(db, creator, name="Mid")
        high = make_model(db, creator, name="High")
        unrated = make_model(db, creator, name="Unrated")
        db.commit()
        client.patch(f"/models/{low.id}/rating", json={"rating": 2})
        client.patch(f"/models/{mid.id}/rating", json={"rating": 3})
        client.patch(f"/models/{high.id}/rating", json={"rating": 5})
        return low, mid, high, unrated

    def test_min_rating_filters_below(self, client, db):
        self._rated_set(client, db)
        names = {i["name"] for i in client.get("/models?min_rating=3").json()["items"]}
        assert names == {"Mid", "High"}

    def test_min_rating_excludes_unrated(self, client, db):
        self._rated_set(client, db)
        names = {i["name"] for i in client.get("/models?min_rating=1").json()["items"]}
        assert "Unrated" not in names
        assert names == {"Low", "Mid", "High"}

    def test_min_rating_out_of_range_rejected(self, client, db):
        self._rated_set(client, db)
        assert client.get("/models?min_rating=6").status_code == 422


# ---------------------------------------------------------------------------
# GET /models?sort=rating
# ---------------------------------------------------------------------------

class TestRatingSort:
    def test_sort_by_rating_desc_unrated_last(self, client, db):
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        make_model(db, creator, name="C")
        db.commit()
        client.patch(f"/models/{a.id}/rating", json={"rating": 2})
        client.patch(f"/models/{b.id}/rating", json={"rating": 5})
        # c left unrated
        names = [i["name"] for i in client.get("/models?sort=rating").json()["items"]]
        assert names[0] == "B"   # 5 stars first
        assert names[1] == "A"   # 2 stars next
        assert names[2] == "C"   # unrated last

"""Guide CRUD (M2, #258): the relational Tab->Phase->Step->Swatch/Mix spine,
JSON display blocks, whole-guide upsert + tab-subtree replace, slug/status
lifecycle, and FK/paint reference validation.
"""
import pytest

from tests.conftest import make_creator, make_model


def mk_paint(client, line_id, code="002", name="Coal Black"):
    return client.post(
        "/painting/paints",
        json={"paint_line_id": line_id, "code": code, "name": name,
              "hex": "#2A2A2A", "finish": "matte"},
    ).json()


@pytest.fixture
def paint(client):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    line = client.post(
        "/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}
    ).json()
    return mk_paint(client, line["id"])


def guide_body(paint_id, **over):
    body = {
        "slug": "robocop-1987",
        "title": "RoboCop",
        "scale": "1:6",
        "technique_tags": ["TMM", "OSL"],
        "character_brief": {
            "philosophy": "value first",
            "light_source": "warm key, upper-left",
            "priority_materials": ["metal", "visor"],
        },
        "theme": {"accent": "#c0a060", "hero_gradient": "linear-gradient(...)"},
        "tabs": [
            {
                "name": "Metals",
                "sort_order": 0,
                "value_map": {"chips": [
                    {"hex": "#101010", "value_pct": 10, "zone_label": "deep shadow"},
                ]},
                "phases": [
                    {
                        "label": "Base",
                        "steps": [
                            {
                                "title": "Gloss black base",
                                "technique_tag": "airbrush",
                                "body": "Lay down a gloss black.",
                                "tip": "Thin to milk.",
                                "swatches": [
                                    {"paint_id": paint_id, "role_label": "shadow base",
                                     "value_pct": 10},
                                ],
                                "mix_components": [
                                    {"paint_id": paint_id, "parts": 2.0},
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    }
    body.update(over)
    return body


class TestCreateAndRead:
    def test_create_full_tree_round_trips(self, client, paint):
        r = client.post("/painting/guides", json=guide_body(paint["id"]))
        assert r.status_code == 201, r.text
        g = r.json()

        assert g["slug"] == "robocop-1987"
        assert g["status"] == "draft"
        assert g["character_brief"]["priority_materials"] == ["metal", "visor"]
        assert g["theme"]["accent"] == "#c0a060"
        step = g["tabs"][0]["phases"][0]["steps"][0]
        assert step["title"] == "Gloss black base"
        assert step["swatches"][0]["paint_id"] == paint["id"]
        assert step["swatches"][0]["role_label"] == "shadow base"
        assert step["mix_components"][0]["parts"] == 2.0
        assert g["tabs"][0]["value_map"]["chips"][0]["zone_label"] == "deep shadow"

        # GET by id returns the same tree.
        got = client.get(f"/painting/guides/{g['id']}").json()
        assert got["tabs"][0]["phases"][0]["steps"][0]["title"] == "Gloss black base"

    def test_get_missing_guide_404(self, client):
        assert client.get("/painting/guides/999").status_code == 404

    def test_list_returns_cards_without_spine(self, client, paint):
        client.post("/painting/guides", json=guide_body(paint["id"]))
        listed = client.get("/painting/guides").json()
        assert listed["total"] == 1
        card = listed["items"][0]
        assert card["title"] == "RoboCop"
        assert "tabs" not in card

    def test_list_filters_by_status_and_model(self, client, paint, db):
        creator = make_creator(db)
        model = make_model(db, creator)
        client.post("/painting/guides", json=guide_body(paint["id"]))
        client.post("/painting/guides", json=guide_body(
            paint["id"], slug="batman", title="Batman", model_id=model.id, status="published"))

        assert client.get("/painting/guides?status=published").json()["total"] == 1
        assert client.get(f"/painting/guides?model_id={model.id}").json()["total"] == 1
        assert client.get("/painting/guides?q=robo").json()["total"] == 1


class TestValidation:
    def test_duplicate_slug_409(self, client, paint):
        client.post("/painting/guides", json=guide_body(paint["id"]))
        r = client.post("/painting/guides", json=guide_body(paint["id"]))
        assert r.status_code == 409

    def test_unknown_paint_id_422(self, client, paint):
        r = client.post("/painting/guides", json=guide_body(paint["id"] + 999))
        assert r.status_code == 422
        assert "unknown paint" in r.json()["detail"].lower()

    def test_unknown_model_fk_422(self, client, paint):
        r = client.post("/painting/guides", json=guide_body(paint["id"], model_id=12345))
        assert r.status_code == 422
        assert "model" in r.json()["detail"].lower()

    def test_bad_scale_rejected_422(self, client, paint):
        r = client.post("/painting/guides", json=guide_body(paint["id"], scale="1:9"))
        assert r.status_code == 422

    def test_extra_field_forbidden(self, client, paint):
        r = client.post("/painting/guides", json=guide_body(paint["id"], bogus="x"))
        assert r.status_code == 422


class TestUpdate:
    def test_patch_scalar_leaves_spine_intact(self, client, paint):
        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        r = client.patch(f"/painting/guides/{g['id']}", json={"title": "RoboCop ED-209"})
        assert r.status_code == 200
        updated = r.json()
        assert updated["title"] == "RoboCop ED-209"
        # tabs omitted from the PATCH -> content spine untouched.
        assert len(updated["tabs"][0]["phases"][0]["steps"]) == 1

    def test_patch_tabs_replaces_subtree(self, client, paint):
        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        r = client.patch(f"/painting/guides/{g['id']}", json={
            "tabs": [{"name": "Skin", "phases": [
                {"label": "Anchor", "steps": [{"title": "Midtone"}]},
            ]}],
        })
        assert r.status_code == 200
        tabs = r.json()["tabs"]
        assert len(tabs) == 1
        assert tabs[0]["name"] == "Skin"
        assert tabs[0]["phases"][0]["steps"][0]["title"] == "Midtone"

    def test_patch_empty_tabs_clears_spine(self, client, paint):
        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        r = client.patch(f"/painting/guides/{g['id']}", json={"tabs": []})
        assert r.status_code == 200
        assert r.json()["tabs"] == []

    def test_patch_null_clears_nullable_block(self, client, paint):
        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        r = client.patch(f"/painting/guides/{g['id']}", json={"character_brief": None})
        assert r.status_code == 200
        assert r.json()["character_brief"] is None

    def test_patch_duplicate_slug_409(self, client, paint):
        client.post("/painting/guides", json=guide_body(paint["id"], slug="taken", title="A"))
        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        r = client.patch(f"/painting/guides/{g['id']}", json={"slug": "taken"})
        assert r.status_code == 409

    def test_patch_same_slug_allowed(self, client, paint):
        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        r = client.patch(f"/painting/guides/{g['id']}", json={"slug": "robocop-1987"})
        assert r.status_code == 200

    def test_patch_unknown_paint_422(self, client, paint):
        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        r = client.patch(f"/painting/guides/{g['id']}", json={
            "tabs": [{"name": "X", "phases": [{"label": "p", "steps": [
                {"title": "s", "swatches": [{"paint_id": 99999}]},
            ]}]}],
        })
        assert r.status_code == 422


class TestStatusLifecycle:
    def test_publish_stamps_published_at(self, client, paint):
        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        assert g["published_at"] is None
        r = client.patch(f"/painting/guides/{g['id']}", json={"status": "published"})
        assert r.json()["status"] == "published"
        assert r.json()["published_at"] is not None

    def test_publish_at_create(self, client, paint):
        g = client.post(
            "/painting/guides", json=guide_body(paint["id"], status="published")
        ).json()
        assert g["published_at"] is not None

    def test_republish_keeps_original_timestamp(self, client, paint):
        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        first = client.patch(
            f"/painting/guides/{g['id']}", json={"status": "published"}
        ).json()["published_at"]
        client.patch(f"/painting/guides/{g['id']}", json={"status": "archived"})
        again = client.patch(
            f"/painting/guides/{g['id']}", json={"status": "published"}
        ).json()["published_at"]
        assert again == first


class TestDelete:
    def test_delete_cascades_spine(self, client, paint, db):
        from app.painting.models import GuideStep, GuideSwatch

        g = client.post("/painting/guides", json=guide_body(paint["id"])).json()
        assert db.query(GuideSwatch).count() == 1

        r = client.delete(f"/painting/guides/{g['id']}")
        assert r.status_code == 200
        assert client.get(f"/painting/guides/{g['id']}").status_code == 404
        assert db.query(GuideStep).count() == 0
        assert db.query(GuideSwatch).count() == 0


class TestCategoriesAndSeries:
    def test_category_create_list_with_counts(self, client, paint):
        cat = client.post(
            "/painting/categories", json={"slug": "film-tv", "display_name": "Film & TV"}
        ).json()
        client.post("/painting/guides", json=guide_body(paint["id"], category_id=cat["id"]))

        listed = client.get("/painting/categories").json()
        assert listed[0]["slug"] == "film-tv"
        assert listed[0]["guide_count"] == 1

    def test_duplicate_category_slug_409(self, client):
        client.post("/painting/categories", json={"slug": "film-tv", "display_name": "A"})
        r = client.post("/painting/categories", json={"slug": "film-tv", "display_name": "B"})
        assert r.status_code == 409

    def test_guide_unknown_category_422(self, client, paint):
        r = client.post("/painting/guides", json=guide_body(paint["id"], category_id=777))
        assert r.status_code == 422

    def test_series_create_and_list(self, client):
        client.post("/painting/series", json={"slug": "batman-1966", "display_name": "Batman 1966"})
        listed = client.get("/painting/series").json()
        assert listed[0]["slug"] == "batman-1966"

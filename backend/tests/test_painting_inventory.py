"""Paint Shelf inventory CRUD (#240): brands, lines, paints, and the derived
matchable flag (spec §8.6)."""
import pytest


def mk_brand(client, name="Monument Hobbies"):
    return client.post("/painting/brands", json={"name": name}).json()


def mk_line(client, brand_id, name="Pro Acryl Standard", code_pattern=None):
    return client.post(
        "/painting/lines",
        json={"brand_id": brand_id, "name": name, "code_pattern": code_pattern},
    ).json()


def mk_paint(client, line_id, **over):
    body = {
        "paint_line_id": line_id,
        "code": "002",
        "name": "Coal Black",
        "hex": "#2A2A2A",
        "finish": "matte",
        **over,
    }
    return client.post("/painting/paints", json=body)


@pytest.fixture
def line(client):
    brand = mk_brand(client)
    return mk_line(client, brand["id"])


class TestBrandsAndLines:
    def test_brand_create_and_list_with_lines(self, client):
        brand = mk_brand(client)
        mk_line(client, brand["id"], name="Signature Series")

        listed = client.get("/painting/brands").json()
        assert [b["name"] for b in listed] == ["Monument Hobbies"]
        assert listed[0]["lines"][0]["name"] == "Signature Series"

    def test_duplicate_brand_409_case_insensitive(self, client):
        mk_brand(client, "Vallejo")
        assert client.post("/painting/brands", json={"name": "vallejo"}).status_code == 409

    def test_line_requires_existing_brand(self, client):
        r = client.post("/painting/lines", json={"brand_id": 999, "name": "Ghost Line"})
        assert r.status_code == 404

    def test_duplicate_line_within_brand_409(self, client):
        brand = mk_brand(client)
        mk_line(client, brand["id"], name="AMP")
        r = client.post("/painting/lines", json={"brand_id": brand["id"], "name": "amp"})
        assert r.status_code == 409

    def test_line_patch_code_pattern(self, client, line):
        r = client.patch(f"/painting/lines/{line['id']}", json={"code_pattern": r"^MPA-\d{3}$"})
        assert r.status_code == 200
        assert r.json()["code_pattern"] == r"^MPA-\d{3}$"


class TestPaintCRUD:
    def test_create_and_get(self, client, line):
        created = mk_paint(client, line["id"])
        assert created.status_code == 201
        paint = created.json()
        assert paint["name"] == "Coal Black"

        fetched = client.get(f"/painting/paints/{paint['id']}").json()
        assert fetched == paint

    def test_duplicate_code_within_line_409(self, client, line):
        mk_paint(client, line["id"])
        assert mk_paint(client, line["id"], name="Other").status_code == 409

    def test_create_requires_existing_line(self, client):
        assert mk_paint(client, 999).status_code == 404

    def test_patch_updates_fields_and_clears_nullable(self, client, line):
        paint = mk_paint(client, line["id"]).json()
        r = client.patch(
            f"/painting/paints/{paint['id']}",
            json={"name": "Coal Black v2", "hex": None, "owned": False},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Coal Black v2"
        assert body["hex"] is None
        assert body["owned"] is False

    def test_bad_hex_rejected(self, client, line):
        assert mk_paint(client, line["id"], hex="2A2A2A").status_code == 422
        assert mk_paint(client, line["id"], hex="#GGGGGG").status_code == 422

    def test_unknown_finish_rejected(self, client, line):
        assert mk_paint(client, line["id"], finish="sparkly").status_code == 422

    def test_delete(self, client, line):
        paint = mk_paint(client, line["id"]).json()
        assert client.delete(f"/painting/paints/{paint['id']}").status_code == 200
        assert client.get(f"/painting/paints/{paint['id']}").status_code == 404

    def test_delete_blocked_when_guide_references_it(self, client, db, line):
        from app.painting.models import Guide, GuidePhase, GuideStep, GuideSwatch, GuideTab

        paint = mk_paint(client, line["id"]).json()
        guide = Guide(slug="g", title="G")
        db.add(guide)
        db.flush()
        tab = GuideTab(guide_id=guide.id, name="Skin")
        db.add(tab)
        db.flush()
        phase = GuidePhase(tab_id=tab.id, label="Base")
        db.add(phase)
        db.flush()
        step = GuideStep(phase_id=phase.id, title="Prime")
        db.add(step)
        db.flush()
        db.add(GuideSwatch(step_id=step.id, paint_id=paint["id"]))
        db.commit()

        assert client.delete(f"/painting/paints/{paint['id']}").status_code == 409


class TestMatchableDerivation:
    @pytest.mark.parametrize("finish,expected", [
        ("matte", True), ("satin", True), ("gloss", True),
        ("metallic", False), ("ink", False), ("wash", False), ("fluor", False),
        ("primer", False), ("medium", False), ("pigment", False), ("texture", False),
    ])
    def test_derived_from_finish_on_create(self, client, line, finish, expected):
        paint = mk_paint(client, line["id"], code=finish, finish=finish).json()
        assert paint["matchable"] is expected

    def test_client_cannot_set_matchable(self, client, line):
        assert mk_paint(client, line["id"], matchable=True, finish="wash").status_code == 422

        paint = mk_paint(client, line["id"]).json()
        r = client.patch(f"/painting/paints/{paint['id']}", json={"matchable": False})
        assert r.status_code == 422

    def test_rederived_when_finish_changes(self, client, line):
        paint = mk_paint(client, line["id"]).json()
        assert paint["matchable"] is True

        r = client.patch(f"/painting/paints/{paint['id']}", json={"finish": "metallic"})
        assert r.json()["matchable"] is False

        r = client.patch(f"/painting/paints/{paint['id']}", json={"finish": "satin"})
        assert r.json()["matchable"] is True


class TestPaintListing:
    def _seed(self, client):
        brand_a = mk_brand(client, "Monument Hobbies")
        brand_b = mk_brand(client, "Army Painter")
        line_a = mk_line(client, brand_a["id"], "Pro Acryl Standard")
        line_b = mk_line(client, brand_b["id"], "Warpaints Fanatic")
        mk_paint(client, line_a["id"], code="002", name="Coal Black", finish="matte")
        mk_paint(client, line_a["id"], code="018", name="Bold Pyrrole Red", finish="matte")
        mk_paint(client, line_b["id"], code="WP3001", name="Matt Black", finish="matte", owned=False)
        mk_paint(client, line_b["id"], code="WP3017", name="Shining Silver", finish="metallic")
        return line_a, line_b

    def test_search_matches_name_and_code(self, client):
        self._seed(client)
        assert {p["name"] for p in client.get("/painting/paints?q=black").json()["items"]} == \
            {"Coal Black", "Matt Black"}
        assert client.get("/painting/paints?q=WP3017").json()["items"][0]["name"] == "Shining Silver"

    def test_filter_by_line_brand_finish_owned(self, client):
        line_a, _ = self._seed(client)
        assert client.get(f"/painting/paints?line_id={line_a['id']}").json()["total"] == 2

        brands = client.get("/painting/brands").json()
        ap = next(b for b in brands if b["name"] == "Army Painter")
        assert client.get(f"/painting/paints?brand_id={ap['id']}").json()["total"] == 2

        assert client.get("/painting/paints?finish=metallic").json()["total"] == 1
        assert client.get("/painting/paints?owned=false").json()["total"] == 1

    def test_pagination(self, client):
        self._seed(client)
        page = client.get("/painting/paints?page=1&page_size=3").json()
        assert page["total"] == 4
        assert len(page["items"]) == 3
        page2 = client.get("/painting/paints?page=2&page_size=3").json()
        assert len(page2["items"]) == 1

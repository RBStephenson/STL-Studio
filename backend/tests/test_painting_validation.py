"""Guide validator + publish gate (#489, spec §8.4).

`validate_guide` walks the content tree and returns block/warn flags; publish is
gated on block flags. Domain colour checks are deferred (#506) and not covered
here. Reuses the guide-body helper from the CRUD tests.
"""
import pytest

from app.painting.models import Guide, GuideSwatch, Paint, PaintLine
from tests.test_painting_guides import guide_body, mk_paint


@pytest.fixture
def owned_paint(client):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    line = client.post("/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}).json()
    return mk_paint(client, line["id"])


def _make_guide(client, paint_id, **over):
    return client.post("/painting/guides", json=guide_body(paint_id, **over)).json()


def _validate(client, gid):
    r = client.get(f"/painting/guides/{gid}/validation")
    assert r.status_code == 200
    return r.json()


def _codes(result):
    return {f["code"] for f in result["flags"]}


class TestValidator:
    def test_clean_guide_has_no_flags(self, client, owned_paint):
        g = _make_guide(client, owned_paint["id"])
        res = _validate(client, g["id"])
        assert res["ok"] is True
        assert res["flags"] == []

    def test_unowned_paint_is_a_block_flag(self, client, owned_paint, db):
        g = _make_guide(client, owned_paint["id"])
        db.query(Paint).filter(Paint.id == owned_paint["id"]).update({"owned": False})
        db.commit()

        res = _validate(client, g["id"])
        assert res["ok"] is False
        assert "paint_not_owned" in _codes(res)
        flag = next(f for f in res["flags"] if f["code"] == "paint_not_owned")
        assert flag["severity"] == "block"
        # Locator points at the node so the editor can jump to it.
        assert flag["tab_index"] == 0 and flag["step_index"] == 0

    def test_code_pattern_violation_is_a_block_flag(self, client, owned_paint, db):
        g = _make_guide(client, owned_paint["id"])
        # Impose a pattern the existing "002" code can't satisfy (hand-edited DB).
        db.query(PaintLine).filter(PaintLine.id == owned_paint["paint_line_id"]).update(
            {"code_pattern": r"^MPA-\d{3}$"}
        )
        db.commit()

        res = _validate(client, g["id"])
        assert res["ok"] is False
        assert "paint_code_invalid" in _codes(res)

    def test_empty_tab_warns(self, client, owned_paint):
        body_tabs = guide_body(owned_paint["id"])["tabs"]
        body_tabs.append({"name": "Empty", "sort_order": 1, "phases": []})
        g = _make_guide(client, owned_paint["id"], tabs=body_tabs)
        res = _validate(client, g["id"])
        assert "empty_tab" in _codes(res)
        assert res["ok"] is True  # warn-only doesn't block

    def test_step_without_swatches_warns(self, client, owned_paint):
        tabs = guide_body(owned_paint["id"])["tabs"]
        tabs[0]["phases"][0]["steps"].append({"title": "Dry brush", "swatches": [], "mix_components": []})
        g = _make_guide(client, owned_paint["id"], tabs=tabs)
        res = _validate(client, g["id"])
        assert "step_no_swatches" in _codes(res)

    def test_value_compression_warns(self, client, owned_paint):
        tabs = guide_body(owned_paint["id"])["tabs"]
        # Two valued swatches only 5% apart in one step → compressed range.
        tabs[0]["phases"][0]["steps"][0]["swatches"] = [
            {"paint_id": owned_paint["id"], "value_pct": 50, "role_label": "mid"},
            {"paint_id": owned_paint["id"], "value_pct": 55, "role_label": "hi"},
        ]
        g = _make_guide(client, owned_paint["id"], tabs=tabs)
        res = _validate(client, g["id"])
        assert "value_compression" in _codes(res)

    def test_value_out_of_range_warns(self, client, owned_paint, db):
        g = _make_guide(client, owned_paint["id"])
        sw = db.query(GuideSwatch).join(GuideSwatch.step).first()
        db.query(GuideSwatch).filter(GuideSwatch.id == sw.id).update({"value_pct": 150})
        db.commit()
        res = _validate(client, g["id"])
        assert "value_out_of_range" in _codes(res)


class TestPublishGate:
    def test_block_flag_prevents_publish(self, client, owned_paint, db):
        g = _make_guide(client, owned_paint["id"])
        db.query(Paint).filter(Paint.id == owned_paint["id"]).update({"owned": False})
        db.commit()

        r = client.patch(f"/painting/guides/{g['id']}", json={"status": "published"})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert any(f["code"] == "paint_not_owned" for f in detail["flags"])
        # Still a draft — the publish was rejected.
        assert db.get(Guide, g["id"]).status != "published"

    def test_warn_only_guide_publishes(self, client, owned_paint):
        # A compressed-value warning must not block publishing.
        tabs = guide_body(owned_paint["id"])["tabs"]
        tabs[0]["phases"][0]["steps"][0]["swatches"] = [
            {"paint_id": owned_paint["id"], "value_pct": 50},
            {"paint_id": owned_paint["id"], "value_pct": 55},
        ]
        g = _make_guide(client, owned_paint["id"], tabs=tabs)

        r = client.patch(f"/painting/guides/{g['id']}", json={"status": "published"})
        assert r.status_code == 200
        assert r.json()["status"] == "published"

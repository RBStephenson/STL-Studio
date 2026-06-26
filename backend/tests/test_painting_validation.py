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


class TestDomainRules:
    """Figure-painting domain rules ported into the validator (#498, #506 fold)."""

    def _step_swatches(self, owned_paint, swatches, **step_over):
        tabs = guide_body(owned_paint["id"])["tabs"]
        step = tabs[0]["phases"][0]["steps"][0]
        step["swatches"] = swatches
        step.update(step_over)
        return tabs

    def test_near_white_without_specular_role_warns(self, client, owned_paint):
        tabs = self._step_swatches(owned_paint, [
            {"paint_id": owned_paint["id"], "value_pct": 99, "role_label": "mid-tone"},
        ])
        g = _make_guide(client, owned_paint["id"], tabs=tabs)
        assert "white_misuse" in _codes(_validate(client, g["id"]))

    def test_near_white_with_specular_role_is_clean(self, client, owned_paint):
        tabs = self._step_swatches(owned_paint, [
            {"paint_id": owned_paint["id"], "value_pct": 99, "role_label": "final specular"},
        ])
        g = _make_guide(client, owned_paint["id"], tabs=tabs)
        assert "white_misuse" not in _codes(_validate(client, g["id"]))

    def test_near_black_without_shadow_role_warns(self, client, owned_paint):
        tabs = self._step_swatches(owned_paint, [
            {"paint_id": owned_paint["id"], "value_pct": 1, "role_label": "base coat"},
        ])
        g = _make_guide(client, owned_paint["id"], tabs=tabs)
        assert "black_misuse" in _codes(_validate(client, g["id"]))

    def test_near_black_with_occlusion_role_is_clean(self, client, owned_paint):
        tabs = self._step_swatches(owned_paint, [
            {"paint_id": owned_paint["id"], "value_pct": 1, "role_label": "deepest occlusion"},
        ])
        g = _make_guide(client, owned_paint["id"], tabs=tabs)
        assert "black_misuse" not in _codes(_validate(client, g["id"]))

    def test_missing_value_intent_warns(self, client, owned_paint):
        tabs = self._step_swatches(
            owned_paint,
            [{"paint_id": owned_paint["id"], "value_pct": 40, "role_label": "mid"}],
            value_intent="",
        )
        g = _make_guide(client, owned_paint["id"], tabs=tabs)
        res = _validate(client, g["id"])
        assert "value_intent_missing" in _codes(res)
        assert res["ok"] is True  # advisory

    def test_value_intent_present_is_clean(self, client, owned_paint):
        g = _make_guide(client, owned_paint["id"])  # default step carries value_intent
        assert "value_intent_missing" not in _codes(_validate(client, g["id"]))

    def test_high_contrast_scale_flags_wider_spread(self, client, owned_paint):
        # Spread of 20% passes at 1:6 (min 15) but fails at 28mm (min 25).
        swatches = [
            {"paint_id": owned_paint["id"], "value_pct": 40, "role_label": "mid"},
            {"paint_id": owned_paint["id"], "value_pct": 60, "role_label": "hi"},
        ]
        ok = _make_guide(client, owned_paint["id"],
                         tabs=self._step_swatches(owned_paint, swatches), scale="1:6")
        assert "value_compression" not in _codes(_validate(client, ok["id"]))

        tight = _make_guide(client, owned_paint["id"], slug="rc-28",
                            tabs=self._step_swatches(owned_paint, swatches), scale="28mm")
        assert "value_compression" in _codes(_validate(client, tight["id"]))


class TestSkinAnchorBand:
    """Skin-anchor band check (skill Step 2, folded from #506)."""

    def _skin_guide(self, client, anchor_paint_id, *, band, slug="diana"):
        body = guide_body(anchor_paint_id, slug=slug)
        body["tabs"] = [{
            "name": "Skin",
            "sort_order": 0,
            "skin_config": {"complexion_band": band} if band else None,
            "phases": [{"label": "Base", "steps": [{
                "title": "Anchor",
                "value_intent": "reads ~30% value",
                "swatches": [
                    {"paint_id": anchor_paint_id, "role_label": "mid-tone anchor", "value_pct": 30},
                ],
            }]}],
        }]
        return client.post("/painting/guides", json=body).json()

    def test_light_anchor_on_deep_skin_flags(self, client, owned_paint):
        # Shadow Flesh anchors the very-fair band — wrong for deep-brown skin (Diana).
        shadow_flesh = mk_paint(client, owned_paint["paint_line_id"],
                                code="042", name="Shadow Flesh")
        g = self._skin_guide(client, shadow_flesh["id"], band="deep")
        assert "skin_anchor_too_light" in _codes(_validate(client, g["id"]))

    def test_band_appropriate_anchor_is_clean(self, client, owned_paint):
        dark_flesh = mk_paint(client, owned_paint["paint_line_id"],
                              code="068", name="Dark Flesh")
        g = self._skin_guide(client, dark_flesh["id"], band="deep")
        assert "skin_anchor_too_light" not in _codes(_validate(client, g["id"]))

    def test_no_stated_band_skips_the_check(self, client, owned_paint):
        shadow_flesh = mk_paint(client, owned_paint["paint_line_id"],
                                code="042", name="Shadow Flesh")
        g = self._skin_guide(client, shadow_flesh["id"], band=None)
        assert "skin_anchor_too_light" not in _codes(_validate(client, g["id"]))


def _hex_paint(client, line_id, code, name, hex_):
    return client.post(
        "/painting/paints",
        json={"paint_line_id": line_id, "code": code, "name": name,
              "hex": hex_, "finish": "matte"},
    ).json()


class TestHighlightDirection:
    """Highlight-direction check (skill Step 3, #506)."""

    def _skin_guide(self, client, paint_id, *, band, role="bright highlight",
                    light=None, slug="hl"):
        body = guide_body(paint_id, slug=slug)
        if light:
            body["light_source"] = light
        body["tabs"] = [{
            "name": "Skin",
            "sort_order": 0,
            "skin_config": {"complexion_band": band} if band else None,
            "phases": [{"label": "Light", "steps": [{
                "title": "Highlight",
                "value_intent": "reads ~70% value",
                "swatches": [{"paint_id": paint_id, "role_label": role, "value_pct": 70}],
            }]}],
        }]
        return client.post("/painting/guides", json=body).json()

    def test_pink_highlight_on_deep_skin_flags(self, client, owned_paint):
        # Rose-triad paint named as the wrong highlight on deep skin.
        pearl = _hex_paint(client, owned_paint["paint_line_id"], "S01", "Pearl Skin", "#E8C9C0")
        g = self._skin_guide(client, pearl["id"], band="deep")
        assert "highlight_direction" in _codes(_validate(client, g["id"]))

    def test_warm_golden_highlight_on_deep_skin_is_clean(self, client, owned_paint):
        amber = _hex_paint(client, owned_paint["paint_line_id"], "S17", "Advanced Flesh Tone", "#C8923C")
        g = self._skin_guide(client, amber["id"], band="deep")
        assert "highlight_direction" not in _codes(_validate(client, g["id"]))

    def test_cool_highlight_flags_by_hue(self, client, owned_paint):
        # Neutral name, but a cool (blue) tinted highlight → flagged on deep skin.
        cool = _hex_paint(client, owned_paint["paint_line_id"], "X01", "Sky Tint", "#8AA0C8")
        g = self._skin_guide(client, cool["id"], band="deep")
        assert "highlight_direction" in _codes(_validate(client, g["id"]))

    def test_cool_highlight_allowed_under_cool_light(self, client, owned_paint):
        cool = _hex_paint(client, owned_paint["paint_line_id"], "X01", "Sky Tint", "#8AA0C8")
        g = self._skin_guide(client, cool["id"], band="deep", light="cool moonlight")
        assert "highlight_direction" not in _codes(_validate(client, g["id"]))

    def test_lighter_band_is_not_gated(self, client, owned_paint):
        pearl = _hex_paint(client, owned_paint["paint_line_id"], "S01", "Pearl Skin", "#E8C9C0")
        g = self._skin_guide(client, pearl["id"], band="fair")
        assert "highlight_direction" not in _codes(_validate(client, g["id"]))

    def test_non_highlight_role_is_ignored(self, client, owned_paint):
        pearl = _hex_paint(client, owned_paint["paint_line_id"], "S01", "Pearl Skin", "#E8C9C0")
        g = self._skin_guide(client, pearl["id"], band="deep", role="mid-tone anchor")
        assert "highlight_direction" not in _codes(_validate(client, g["id"]))

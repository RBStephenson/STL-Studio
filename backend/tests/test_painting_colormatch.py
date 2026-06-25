"""Color-match studio (spec §8.6, #493).

Behaviour, not colour-science exactness (success criterion S5): a sampled
opaque region should surface the correct owned-paint *family*, value-first,
with honest ΔE bands and inks/metallics handled per their class.
"""
import io

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mk_brand(client, name="Monument Hobbies"):
    return client.post("/painting/brands", json={"name": name}).json()


def mk_line(client, brand_id, name="Pro Acryl Standard"):
    return client.post(
        "/painting/lines", json={"brand_id": brand_id, "name": name}
    ).json()


def mk_paint(client, line_id, code, name, hex_, finish="matte", owned=True):
    return client.post(
        "/painting/paints",
        json={
            "paint_line_id": line_id,
            "code": code,
            "name": name,
            "hex": hex_,
            "finish": finish,
            "owned": owned,
        },
    ).json()


def solid_png(rgb, size=(32, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


def two_block_png(top_rgb, bottom_rgb, size=(32, 32)) -> bytes:
    img = Image.new("RGB", size, top_rgb)
    img.paste(Image.new("RGB", (size[0], size[1] // 2), bottom_rgb), (0, size[1] // 2))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def post_match(client, png, **form):
    return client.post(
        "/painting/colormatch",
        files={"file": ("ref.png", png, "image/png")},
        data=form,
    )


@pytest.fixture
def line(client):
    return mk_line(client, mk_brand(client)["id"])["id"]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestMatching:
    def test_solid_region_surfaces_nearest_hue_family(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        mk_paint(client, line, "B01", "Deep Blue", "#1E3CC8")

        resp = post_match(client, solid_png((200, 30, 30)), k=1)
        assert resp.status_code == 200
        body = resp.json()

        region = body["regions"][0]
        top = region["hue_candidates"][0]
        assert top["name"] == "Bold Red"
        assert top["delta_e"] is not None
        assert top["band"] in {"very_close", "close", "family"}

    def test_value_candidates_lead_and_include_metallic(self, client, line):
        # A metallic is excluded from hue (its hex lies) but must appear in the
        # value ranking — value is honest even for metals (spec §8.6).
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        mk_paint(client, line, "M01", "Gunmetal", "#5A5A5A", finish="metallic")

        body = post_match(client, solid_png((90, 90, 90)), k=1).json()
        region = body["regions"][0]

        value_names = {c["name"] for c in region["value_candidates"]}
        hue_names = {c["name"] for c in region["hue_candidates"]}
        assert "Gunmetal" in value_names
        assert "Gunmetal" not in hue_names  # metallic never hue-ranked
        assert region["value_candidates"][0]["delta_e"] is None

    def test_inks_surface_as_glaze_options_only(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        mk_paint(client, line, "I01", "Red Shade", "#7A1010", finish="ink")

        body = post_match(client, solid_png((200, 30, 30)), k=1).json()
        region = body["regions"][0]

        glaze_names = {c["name"] for c in region["glaze_options"]}
        hue_names = {c["name"] for c in region["hue_candidates"]}
        value_names = {c["name"] for c in region["value_candidates"]}
        assert "Red Shade" in glaze_names
        assert "Red Shade" not in hue_names
        assert "Red Shade" not in value_names

    def test_k_controls_region_count(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        body = post_match(client, two_block_png((200, 30, 30), (30, 30, 200)), k=2).json()
        assert len(body["regions"]) == 2
        # Two distinct blocks → two distinct centroids.
        assert body["regions"][0]["hex"] != body["regions"][1]["hex"]

    def test_deterministic_for_same_image(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        png = two_block_png((200, 30, 30), (30, 30, 200))
        first = post_match(client, png, k=3).json()
        second = post_match(client, png, k=3).json()
        assert first == second

    def test_unowned_paint_excluded(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E", owned=False)
        body = post_match(client, solid_png((200, 30, 30)), k=1).json()
        region = body["regions"][0]
        assert region["hue_candidates"] == []

    def test_result_carries_caveat(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        body = post_match(client, solid_png((200, 30, 30)), k=1).json()
        assert "confirm by eye" in body["caveat"].lower()

    def test_very_close_band_for_exact_hex(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        # Image painted with the paint's exact hex → ΔE near zero.
        body = post_match(client, solid_png((0xC8, 0x1E, 0x1E)), k=1).json()
        assert body["regions"][0]["hue_candidates"][0]["band"] == "very_close"


# ---------------------------------------------------------------------------
# Validation / edge cases
# ---------------------------------------------------------------------------

class TestValidation:
    def test_non_image_rejected(self, client, line):
        resp = client.post(
            "/painting/colormatch",
            files={"file": ("x.png", b"not an image", "image/png")},
        )
        assert resp.status_code == 422

    def test_empty_file_rejected(self, client, line):
        resp = post_match(client, b"")
        assert resp.status_code == 422

    def test_k_is_clamped(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        # k far above the cap must not error; region count is bounded.
        body = post_match(client, solid_png((200, 30, 30)), k=999).json()
        assert 1 <= len(body["regions"]) <= 12

    def test_null_hex_paint_ignored(self, client, line):
        # A paint with no hex can't be matched but must not crash the ranking.
        client.post(
            "/painting/paints",
            json={
                "paint_line_id": line,
                "code": "N01",
                "name": "No Hex",
                "finish": "matte",
            },
        )
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        body = post_match(client, solid_png((200, 30, 30)), k=1).json()
        names = {c["name"] for c in body["regions"][0]["hue_candidates"]}
        assert "No Hex" not in names
        assert "Bold Red" in names

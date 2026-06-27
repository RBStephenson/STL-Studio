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


def ladder_names(region):
    """All paint names across the region's value ladder (shadow + mid + highlight)."""
    lad = region["ladder"]
    return {c["name"] for c in lad["shadow"] + lad["mid"] + lad["highlight"]}


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

    def test_metallic_in_ladder_not_hue(self, client, line):
        # A metallic is excluded from hue (its hex lies) but stays in the value
        # ladder — value is honest even for metals (spec §8.6).
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        mk_paint(client, line, "M01", "Gunmetal", "#5A5A5A", finish="metallic")

        body = post_match(client, solid_png((90, 90, 90)), k=1).json()
        region = body["regions"][0]

        hue_names = {c["name"] for c in region["hue_candidates"]}
        assert "Gunmetal" in ladder_names(region)
        assert "Gunmetal" not in hue_names  # metallic never hue-ranked

    def test_inks_surface_as_glaze_options_only(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        mk_paint(client, line, "I01", "Red Shade", "#7A1010", finish="ink")

        body = post_match(client, solid_png((200, 30, 30)), k=1).json()
        region = body["regions"][0]

        glaze_names = {c["name"] for c in region["glaze_options"]}
        hue_names = {c["name"] for c in region["hue_candidates"]}
        assert "Red Shade" in glaze_names
        assert "Red Shade" not in hue_names
        assert "Red Shade" not in ladder_names(region)

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
# Value-ladder hue family gate (#561 review / #569)
# ---------------------------------------------------------------------------

class TestValueHueFamily:
    def test_offhue_chromatic_paint_excluded_from_ladder(self, client, line):
        # A green region must not offer a red in its ladder, but a same-hue green
        # at a different value should appear.
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")       # off-hue
        mk_paint(client, line, "G01", "Deep Green", "#0F5A14")     # same family

        region = post_match(client, solid_png((40, 170, 60)), k=1).json()["regions"][0]
        assert "Deep Green" in ladder_names(region)
        assert "Bold Red" not in ladder_names(region)

    def test_metallic_kept_regardless_of_hue(self, client, line):
        # Metallics are value-only by design — hue gate must not drop them.
        mk_paint(client, line, "M01", "Warm Steel", "#9A6A50", finish="metallic")

        region = post_match(client, solid_png((40, 170, 60)), k=1).json()["regions"][0]
        assert "Warm Steel" in ladder_names(region)

    def test_neutral_paint_kept_regardless_of_hue(self, client, line):
        mk_paint(client, line, "GY1", "Neutral Grey", "#808080")

        region = post_match(client, solid_png((40, 170, 60)), k=1).json()["regions"][0]
        assert "Neutral Grey" in ladder_names(region)

    def test_neutral_region_keeps_all_hues(self, client, line):
        # A grey region has no meaningful hue → full value ladder, any hue.
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")

        region = post_match(client, solid_png((130, 130, 130)), k=1).json()["regions"][0]
        assert "Bold Red" in ladder_names(region)


class TestValueLadder:
    """The ladder splits the family into shadow → mid → highlight (#569)."""

    def test_shadow_mid_highlight_ordering(self, client, line):
        # Three greens at distinct values; sampling the mid green should place the
        # dark one in shadow, the bright one in highlight, the match in mid.
        mk_paint(client, line, "G_S", "Dark Camo Green", "#14320F")
        mk_paint(client, line, "G_M", "Green", "#2E8B2E")
        mk_paint(client, line, "G_H", "Bright Yellow Green", "#9ACD32")

        region = post_match(client, solid_png((0x2E, 0x8B, 0x2E)), k=1).json()["regions"][0]
        lad = region["ladder"]
        assert "Dark Camo Green" in {c["name"] for c in lad["shadow"]}
        assert "Green" in {c["name"] for c in lad["mid"]}
        assert "Bright Yellow Green" in {c["name"] for c in lad["highlight"]}


# ---------------------------------------------------------------------------
# Background exclusion + eyedropper (#561 review)
# ---------------------------------------------------------------------------

def bordered_png(bg, fg, size=(48, 48), margin=10) -> bytes:
    """An image that's `bg` at the edges with an `fg` block in the centre."""
    img = Image.new("RGB", size, bg)
    img.paste(Image.new("RGB", (size[0] - 2 * margin, size[1] - 2 * margin), fg),
              (margin, margin))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def post_point(client, png, x, y):
    return client.post(
        "/painting/colormatch/point",
        files={"file": ("ref.png", png, "image/png")},
        data={"x": x, "y": y},
    )


class TestBackgroundExclusion:
    def test_corner_backdrop_dropped_so_subject_leads(self, client, line):
        # Near-black border (the studio backdrop) surrounds a green subject. With
        # the backdrop excluded, the dominant region is the green, not the black.
        mk_paint(client, line, "G01", "Deep Green", "#0F5A14")
        mk_paint(client, line, "K01", "Coal Black", "#101010")

        body = post_match(client, bordered_png((8, 8, 8), (40, 170, 60)), k=1).json()
        region = body["regions"][0]
        assert region["value_l"] > 30  # green, not the ~near-black backdrop
        assert region["hue_candidates"][0]["name"] == "Deep Green"


class TestEyedropper:
    def test_point_sample_matches_clicked_color(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        mk_paint(client, line, "B01", "Deep Blue", "#1E3CC8")

        body = post_point(client, solid_png((200, 30, 30)), 0.5, 0.5).json()
        assert len(body["regions"]) == 1
        assert body["regions"][0]["hue_candidates"][0]["name"] == "Bold Red"

    def test_point_samples_the_region_under_the_click(self, client, line):
        mk_paint(client, line, "R01", "Bold Red", "#C81E1E")
        mk_paint(client, line, "B01", "Deep Blue", "#1E3CC8")
        # Red top half, blue bottom half — clicking each half picks that colour.
        png = two_block_png((200, 30, 30), (30, 30, 200))

        top = post_point(client, png, 0.5, 0.1).json()["regions"][0]
        bottom = post_point(client, png, 0.5, 0.9).json()["regions"][0]
        assert top["hue_candidates"][0]["name"] == "Bold Red"
        assert bottom["hue_candidates"][0]["name"] == "Deep Blue"

    def test_point_rejects_bad_image(self, client, line):
        resp = client.post(
            "/painting/colormatch/point",
            files={"file": ("x.png", b"not an image", "image/png")},
            data={"x": 0.5, "y": 0.5},
        )
        assert resp.status_code == 422


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

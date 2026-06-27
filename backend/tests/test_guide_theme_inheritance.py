"""New guides inherit the app-level default theme (#514).

The default lives in the app_settings key/value store; create_guide seeds a
guide's `theme` from it only when the guide doesn't carry its own.
"""
from app.painting.models import Guide

from tests.test_painting_guides import mk_paint
from tests.test_painting_guide_schema import presto_body


def _paint(client):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    line = client.post(
        "/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}
    ).json()
    return mk_paint(client, line["id"])


def _set_default_theme(client, theme: dict):
    r = client.patch("/settings", json={"guide_theme_defaults": theme})
    assert r.status_code == 200


def test_new_guide_inherits_default_theme(client, db):
    paint = _paint(client)
    _set_default_theme(client, {"accent": "#a8cc66", "bg": "#101010"})

    body = presto_body(paint["id"])
    body.pop("theme", None)  # no per-guide theme → inherit the default
    gid = client.post("/painting/guides", json=body).json()["id"]

    guide = db.get(Guide, gid)
    assert guide.theme["accent"] == "#a8cc66"
    assert guide.theme["bg"] == "#101010"


def test_explicit_theme_overrides_default(client, db):
    paint = _paint(client)
    _set_default_theme(client, {"accent": "#a8cc66"})

    body = presto_body(paint["id"])
    body["theme"] = {"accent": "#ff0000"}
    gid = client.post("/painting/guides", json=body).json()["id"]

    guide = db.get(Guide, gid)
    assert guide.theme["accent"] == "#ff0000"


def test_no_default_leaves_theme_none(client, db):
    paint = _paint(client)
    # No default configured (all-None counts as unset).
    body = presto_body(paint["id"])
    body.pop("theme", None)
    gid = client.post("/painting/guides", json=body).json()["id"]

    guide = db.get(Guide, gid)
    assert guide.theme is None

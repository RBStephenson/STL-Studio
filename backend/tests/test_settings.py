"""Tests for the app_settings key/value store (#180) and preferences (#32)."""

DEFAULTS = {
    "painting_guides_enabled": False,
    "show_nsfw": False,
    "library_page_size": 48,
    "filter_presets": [],
}


def test_get_settings_returns_defaults(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert r.json() == DEFAULTS


def test_patch_updates_and_persists(client):
    r = client.patch("/settings", json={"painting_guides_enabled": True})
    assert r.status_code == 200
    assert r.json()["painting_guides_enabled"] is True

    # Stored, not just echoed — a fresh GET reads it back from the DB.
    assert client.get("/settings").json()["painting_guides_enabled"] is True


def test_patch_toggle_back_off(client):
    client.patch("/settings", json={"painting_guides_enabled": True})
    r = client.patch("/settings", json={"painting_guides_enabled": False})
    assert r.status_code == 200
    assert client.get("/settings").json()["painting_guides_enabled"] is False


def test_patch_empty_body_is_a_noop(client):
    r = client.patch("/settings", json={})
    assert r.status_code == 200
    assert r.json() == DEFAULTS


def test_patch_unknown_key_rejected(client):
    r = client.patch("/settings", json={"bogus_key": 1})
    assert r.status_code == 422


def test_patch_non_bool_value_rejected(client):
    r = client.patch("/settings", json={"painting_guides_enabled": "definitely"})
    assert r.status_code == 422


def test_patch_null_value_leaves_setting_unchanged(client):
    client.patch("/settings", json={"painting_guides_enabled": True})
    r = client.patch("/settings", json={"painting_guides_enabled": None})
    assert r.status_code == 200
    assert r.json()["painting_guides_enabled"] is True


# --- Preferences (#32) ---


def test_show_nsfw_round_trips(client):
    r = client.patch("/settings", json={"show_nsfw": True})
    assert r.status_code == 200
    assert client.get("/settings").json()["show_nsfw"] is True


def test_page_size_round_trips(client):
    r = client.patch("/settings", json={"library_page_size": 96})
    assert r.status_code == 200
    assert client.get("/settings").json()["library_page_size"] == 96


def test_page_size_bounds_rejected(client):
    assert client.patch("/settings", json={"library_page_size": 4}).status_code == 422
    assert client.patch("/settings", json={"library_page_size": 999}).status_code == 422
    # Failed PATCH must not have stored anything.
    assert client.get("/settings").json()["library_page_size"] == 48


def test_filter_presets_round_trip(client):
    presets = [
        {"name": "Favorites", "qs": "is_favorite=1"},
        {"name": "DM Stash minis", "qs": "creator_id=5&tag=mini"},
    ]
    r = client.patch("/settings", json={"filter_presets": presets})
    assert r.status_code == 200
    assert client.get("/settings").json()["filter_presets"] == presets


def test_filter_presets_replace_and_clear(client):
    client.patch("/settings", json={"filter_presets": [{"name": "A", "qs": "q=a"}]})
    # A PATCH replaces the whole list; an empty list clears it.
    r = client.patch("/settings", json={"filter_presets": []})
    assert r.status_code == 200
    assert client.get("/settings").json()["filter_presets"] == []


def test_filter_preset_shape_enforced(client):
    # Missing qs
    assert client.patch("/settings", json={"filter_presets": [{"name": "X"}]}).status_code == 422
    # Unknown field inside a preset
    bad = [{"name": "X", "qs": "q=x", "color": "red"}]
    assert client.patch("/settings", json={"filter_presets": bad}).status_code == 422

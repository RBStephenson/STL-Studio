"""Tests for the app_settings key/value store (#180) and preferences (#32)."""

_THEME_KEYS = [
    "bg", "surface", "surface2", "surface3", "border",
    "text", "text_muted", "text_dim", "accent", "hero_gradient",
]
DEFAULTS = {
    "painting_guides_enabled": False,
    "show_nsfw": False,
    "library_page_size": 48,
    "filter_presets": [],
    "recent_days": 7,
    "library_sort": "name",
    "scan_ignore_patterns": [],
    "scan_tag_rules": [],
    "scan_parts_names": [],
    "guide_theme_defaults": {k: None for k in _THEME_KEYS},
    "ai_model": "",
    "ai_effort": "low",
    "part_categories_enabled": False,
    "horizontal_parts_layout": True,
    "gallery_enabled": True,
    "gallery_auto_rotate": True,
    "gallery_rotation_seconds": 10,
    "ai_organize_enabled": False,
    "ai_organize_url": "",
    "ai_organize_model": "",
    "ai_guides_enabled": False,
    "ai_guides_api": None,
    "ai_organize_api": None,
    "log_level": "INFO",
}


def test_ai_effort_round_trips_and_rejects_bad_value(client):
    assert client.patch("/settings", json={"ai_effort": "high"}).status_code == 200
    assert client.get("/settings").json()["ai_effort"] == "high"
    assert client.patch("/settings", json={"ai_effort": "turbo"}).status_code == 422


def test_guide_theme_defaults_round_trip(client):
    # Partial theme: only the fields the user set come back populated (#514).
    r = client.patch(
        "/settings",
        json={"guide_theme_defaults": {"accent": "#a8cc66", "bg": "#101010"}},
    )
    assert r.status_code == 200
    stored = client.get("/settings").json()["guide_theme_defaults"]
    assert stored["accent"] == "#a8cc66"
    assert stored["bg"] == "#101010"
    assert stored["surface"] is None


def test_guide_theme_defaults_rejects_unknown_field(client):
    # GuideTheme forbids extras, so a typo'd colour key is a 422, not silent loss.
    r = client.patch("/settings", json={"guide_theme_defaults": {"accentt": "#fff"}})
    assert r.status_code == 422


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


# --- Log level (runtime toggle, no restart) ---

def test_log_level_round_trips_and_rejects_bad_value(client):
    assert client.patch("/settings", json={"log_level": "DEBUG"}).status_code == 200
    assert client.get("/settings").json()["log_level"] == "DEBUG"
    # Only the five standard levels are accepted.
    assert client.patch("/settings", json={"log_level": "VERBOSE"}).status_code == 422
    assert client.patch("/settings", json={"log_level": "debug"}).status_code == 422


def test_log_level_patch_applies_to_logger_live(client):
    """Updating the setting changes the `app` logger level immediately — the
    behaviour the UI relies on to toggle verbosity without a restart."""
    import logging

    client.patch("/settings", json={"log_level": "WARNING"})
    assert logging.getLogger("app").level == logging.WARNING

    client.patch("/settings", json={"log_level": "DEBUG"})
    assert logging.getLogger("app").level == logging.DEBUG


def test_apply_log_level_helper_validates():
    import logging
    from app.logging_config import apply_log_level

    assert apply_log_level("error") == "ERROR"          # normalizes case
    assert logging.getLogger("app").level == logging.ERROR
    try:
        apply_log_level("nonsense")
    except ValueError:
        pass
    else:  # pragma: no cover - fail explicitly if no error raised
        raise AssertionError("apply_log_level should reject unknown levels")


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


def test_recent_days_round_trips(client):
    r = client.patch("/settings", json={"recent_days": 14})
    assert r.status_code == 200
    assert client.get("/settings").json()["recent_days"] == 14


def test_recent_days_bounds_rejected(client):
    assert client.patch("/settings", json={"recent_days": 0}).status_code == 422
    assert client.patch("/settings", json={"recent_days": 91}).status_code == 422
    assert client.get("/settings").json()["recent_days"] == 7


def test_library_sort_round_trips(client):
    r = client.patch("/settings", json={"library_sort": "creator"})
    assert r.status_code == 200
    assert client.get("/settings").json()["library_sort"] == "creator"


def test_library_sort_invalid_value_rejected(client):
    # queue/queued_at exist on the API but aren't persistable Library defaults.
    assert client.patch("/settings", json={"library_sort": "queue"}).status_code == 422
    assert client.patch("/settings", json={"library_sort": "bogus"}).status_code == 422
    assert client.get("/settings").json()["library_sort"] == "name"


def test_gallery_preferences_round_trip(client):
    r = client.patch(
        "/settings",
        json={
            "gallery_enabled": False,
            "gallery_auto_rotate": False,
            "gallery_rotation_seconds": 20,
        },
    )
    assert r.status_code == 200
    settings = client.get("/settings").json()
    assert settings["gallery_enabled"] is False
    assert settings["gallery_auto_rotate"] is False
    assert settings["gallery_rotation_seconds"] == 20


def test_gallery_rotation_seconds_bounds_rejected(client):
    assert client.patch("/settings", json={"gallery_rotation_seconds": 2}).status_code == 422
    assert client.patch("/settings", json={"gallery_rotation_seconds": 61}).status_code == 422
    assert client.get("/settings").json()["gallery_rotation_seconds"] == 10


# --- Atomic single-preset endpoints (#287) ---
# A whole-list PATCH could drop entries when a stale client snapshot was sent;
# these endpoints mutate the stored list server-side so unrelated presets survive.


def test_upsert_preset_adds_to_empty(client):
    r = client.put("/settings/filter-presets", json={"name": "Favorites", "qs": "is_favorite=1"})
    assert r.status_code == 200
    assert r.json()["filter_presets"] == [{"name": "Favorites", "qs": "is_favorite=1"}]
    assert client.get("/settings").json()["filter_presets"] == [
        {"name": "Favorites", "qs": "is_favorite=1"}
    ]


def test_upsert_preset_preserves_existing(client):
    # The #287 regression: saving one preset must not drop the others.
    client.put("/settings/filter-presets", json={"name": "A", "qs": "q=a"})
    client.put("/settings/filter-presets", json={"name": "B", "qs": "q=b"})
    names = [p["name"] for p in client.get("/settings").json()["filter_presets"]]
    assert names == ["A", "B"]


def test_upsert_preset_replaces_same_name(client):
    client.put("/settings/filter-presets", json={"name": "A", "qs": "q=a"})
    r = client.put("/settings/filter-presets", json={"name": "A", "qs": "q=updated"})
    assert r.status_code == 200
    presets = client.get("/settings").json()["filter_presets"]
    assert presets == [{"name": "A", "qs": "q=updated"}]


def test_delete_preset_leaves_others(client):
    client.put("/settings/filter-presets", json={"name": "A", "qs": "q=a"})
    client.put("/settings/filter-presets", json={"name": "B", "qs": "q=b"})
    r = client.delete("/settings/filter-presets", params={"name": "A"})
    assert r.status_code == 200
    assert r.json()["filter_presets"] == [{"name": "B", "qs": "q=b"}]


def test_delete_missing_preset_is_noop(client):
    client.put("/settings/filter-presets", json={"name": "A", "qs": "q=a"})
    r = client.delete("/settings/filter-presets", params={"name": "does-not-exist"})
    assert r.status_code == 200
    assert client.get("/settings").json()["filter_presets"] == [{"name": "A", "qs": "q=a"}]


def test_upsert_preset_shape_enforced(client):
    assert client.put("/settings/filter-presets", json={"name": "X"}).status_code == 422
    bad = {"name": "X", "qs": "q=x", "color": "red"}
    assert client.put("/settings/filter-presets", json=bad).status_code == 422


def test_upsert_preset_coexists_with_patch_list(client):
    # A preset seeded via the legacy whole-list PATCH is visible to, and
    # preserved by, the atomic upsert path.
    client.patch("/settings", json={"filter_presets": [{"name": "Seed", "qs": "q=seed"}]})
    client.put("/settings/filter-presets", json={"name": "New", "qs": "q=new"})
    names = [p["name"] for p in client.get("/settings").json()["filter_presets"]]
    assert names == ["Seed", "New"]


# --- .env reload (#140) ---

import pytest
from app.config import settings as live_settings


@pytest.fixture
def restore_settings():
    """Reloading mutates the shared settings singleton; snapshot/restore it so a
    reload test can't leak env-config state into later tests."""
    snapshot = {n: getattr(live_settings, n) for n in type(live_settings).model_fields}
    yield
    for name, value in snapshot.items():
        setattr(live_settings, name, value)


def test_reload_reports_restart_keys(client, restore_settings):
    r = client.post("/settings/reload")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # database_url is bound once at startup — flagged as needing a restart.
    assert "database_url" in body["restart_required"]
    assert set(body.keys()) == {"ok", "drive_mappings", "restart_required"}


def test_reload_never_exposes_secrets(client, monkeypatch, restore_settings):
    monkeypatch.setenv("MMF_API_KEY", "super-secret-token")
    r = client.post("/settings/reload")
    assert "super-secret-token" not in r.text
    assert "mmf_api_key" not in r.json()


def test_reload_failure_does_not_leak_exception_details(client, monkeypatch, restore_settings):
    """STUDIO-30: a malformed .env raises a pydantic ValidationError whose str()
    can include internal field names/values — the client must get a generic
    message, not the raw exception."""
    def _boom(self):
        raise ValueError("stl_drive_1: field required (type=value_error.missing)")

    monkeypatch.setattr(type(live_settings), "reload", _boom)
    r = client.post("/settings/reload")
    assert r.status_code == 400
    assert "stl_drive_1" not in r.text
    assert "value_error.missing" not in r.text
    assert r.json()["detail"] == "Could not reload settings: invalid configuration"

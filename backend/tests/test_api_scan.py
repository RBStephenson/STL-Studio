"""
Tests for the /scan/browse folder-picker endpoint.
"""

import pytest


@pytest.fixture
def bootstrap_under_tmp(tmp_path, monkeypatch):
    """Treat tmp_path as a bootstrap browse root so the no-roots picker tests
    exercise listing behaviour rather than the allowlist rejection."""
    from app.routers import scan
    monkeypatch.setattr(scan, "_bootstrap_roots", lambda: [tmp_path])


class TestBrowse:
    pytestmark = pytest.mark.usefixtures("bootstrap_under_tmp")

    def test_lists_subdirectories(self, client, tmp_path):
        (tmp_path / "Alpha").mkdir()
        (tmp_path / "Beta").mkdir()
        (tmp_path / "a_file.txt").write_text("x")  # files must be excluded

        resp = client.get("/scan/browse", params={"path": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()

        names = [e["name"] for e in data["entries"]]
        assert names == ["Alpha", "Beta"]          # dirs only, sorted
        assert data["path"] == str(tmp_path)
        assert data["parent"] == str(tmp_path.parent)
        assert data["is_drive_list"] is False

    def test_excludes_hidden_directories(self, client, tmp_path):
        (tmp_path / "Visible").mkdir()
        (tmp_path / ".hidden").mkdir()

        resp = client.get("/scan/browse", params={"path": str(tmp_path)})
        names = [e["name"] for e in resp.json()["entries"]]
        assert names == ["Visible"]

    def test_missing_path_returns_404(self, client, tmp_path):
        resp = client.get("/scan/browse", params={"path": str(tmp_path / "does-not-exist")})
        assert resp.status_code == 404

    def test_entry_paths_are_absolute_and_navigable(self, client, tmp_path):
        child = tmp_path / "Creator"
        child.mkdir()
        (child / "Model").mkdir()

        top = client.get("/scan/browse", params={"path": str(tmp_path)}).json()
        entry_path = top["entries"][0]["path"]
        assert entry_path == str(child)

        # The returned path can be browsed directly.
        nested = client.get("/scan/browse", params={"path": entry_path}).json()
        assert [e["name"] for e in nested["entries"]] == ["Model"]


class TestBrowseBootstrapRestriction:
    """With no scan roots configured, browsing is still limited to the
    bootstrap allowlist — it must not expose the whole filesystem (#41)."""

    def test_arbitrary_path_rejected_when_no_roots(self, client, tmp_path, monkeypatch):
        from app.config import settings
        from app.routers import scan
        monkeypatch.setattr(settings, "stl_roots", "")

        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        monkeypatch.setattr(scan, "_bootstrap_roots", lambda: [allowed])

        assert client.get("/scan/browse", params={"path": str(allowed)}).status_code == 200
        assert client.get("/scan/browse", params={"path": str(outside)}).status_code == 403


class TestBrowseRootRestriction:
    """Once scan roots are configured, /scan/browse is limited to paths under them."""

    def test_browse_allowed_under_every_configured_root(self, client, tmp_path, monkeypatch):
        # Only DB-configured roots — clear the STL_ROOTS env fallback so the
        # allowlist is exactly the two roots added below.
        from app.config import settings
        monkeypatch.setattr(settings, "stl_roots", "")

        root_a = tmp_path / "RootA"
        root_b = tmp_path / "RootB"
        (root_a / "CreatorA").mkdir(parents=True)
        (root_b / "CreatorB").mkdir(parents=True)
        assert client.post("/scan/roots", json={"path": str(root_a)}).status_code == 200
        assert client.post("/scan/roots", json={"path": str(root_b)}).status_code == 200

        # Regression (#211): only the first configured root was checked, so any
        # path under the second root was rejected with 403.
        for root, child in ((root_a, "CreatorA"), (root_b, "CreatorB")):
            resp = client.get("/scan/browse", params={"path": str(root)})
            assert resp.status_code == 200, f"{root} should be browsable"
            assert [e["name"] for e in resp.json()["entries"]] == [child]

    def test_browse_outside_configured_roots_rejected(self, client, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "stl_roots", "")

        root = tmp_path / "Root"
        outside = tmp_path / "Outside"
        root.mkdir()
        outside.mkdir()
        assert client.post("/scan/roots", json={"path": str(root)}).status_code == 200

        resp = client.get("/scan/browse", params={"path": str(outside)})
        assert resp.status_code == 403


class TestScanRoots:
    def test_add_root_defaults_to_creator_layout(self, client, tmp_path):
        resp = client.post("/scan/roots", json={"path": str(tmp_path)})
        assert resp.status_code == 200
        assert resp.json()["layout"] == "{creator}"

    def test_add_root_with_custom_layout(self, client, tmp_path):
        resp = client.post("/scan/roots", json={"path": str(tmp_path), "layout": "{tag}/{creator}"})
        assert resp.status_code == 200
        assert resp.json()["layout"] == "{tag}/{creator}"

    def test_add_root_rejects_invalid_layout(self, client, tmp_path):
        resp = client.post("/scan/roots", json={"path": str(tmp_path), "layout": "{creator}/{tag}"})
        assert resp.status_code == 400

    def test_patch_root_updates_layout(self, client, tmp_path):
        root_id = client.post("/scan/roots", json={"path": str(tmp_path)}).json()["id"]

        resp = client.patch(f"/scan/roots/{root_id}", json={"layout": "{ignore}/{creator}"})
        assert resp.status_code == 200
        assert resp.json()["layout"] == "{ignore}/{creator}"

        listed = client.get("/scan/roots").json()
        assert listed[0]["layout"] == "{ignore}/{creator}"

    def test_patch_root_rejects_invalid_layout(self, client, tmp_path):
        root_id = client.post("/scan/roots", json={"path": str(tmp_path)}).json()["id"]
        resp = client.patch(f"/scan/roots/{root_id}", json={"layout": "no-creator-here"})
        assert resp.status_code == 400

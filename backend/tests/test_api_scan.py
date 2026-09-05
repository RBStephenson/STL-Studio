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

    def test_every_entry_carries_is_dir(self, client, tmp_path):
        (tmp_path / "Alpha").mkdir()

        resp = client.get("/scan/browse", params={"path": str(tmp_path)})
        assert all(e["is_dir"] is True for e in resp.json()["entries"])


class TestBrowseFileExtensions:
    """STUDIO-389: the STL Installer's zip-or-folder source picker needs
    specific files (not just directories) selectable through this same
    allowlist-guarded browser, rather than a platform-specific native file
    dialog (Electron-only, wouldn't work in the Docker/web deployment)."""
    pytestmark = pytest.mark.usefixtures("bootstrap_under_tmp")

    def test_default_omits_files_entirely(self, client, tmp_path):
        (tmp_path / "Alpha").mkdir()
        (tmp_path / "zarana.zip").write_bytes(b"PK")

        resp = client.get("/scan/browse", params={"path": str(tmp_path)})
        names = [e["name"] for e in resp.json()["entries"]]
        assert names == ["Alpha"]

    def test_matching_extension_included_alongside_folders(self, client, tmp_path):
        (tmp_path / "Alpha").mkdir()
        (tmp_path / "zarana.zip").write_bytes(b"PK")
        (tmp_path / "readme.txt").write_text("x")

        resp = client.get(
            "/scan/browse", params={"path": str(tmp_path), "file_extensions": "zip"}
        )
        entries = resp.json()["entries"]
        assert [(e["name"], e["is_dir"]) for e in entries] == [
            ("Alpha", True), ("zarana.zip", False),
        ]

    def test_extension_match_is_case_insensitive(self, client, tmp_path):
        (tmp_path / "ZARANA.ZIP").write_bytes(b"PK")

        resp = client.get(
            "/scan/browse", params={"path": str(tmp_path), "file_extensions": "zip"}
        )
        names = [e["name"] for e in resp.json()["entries"]]
        assert names == ["ZARANA.ZIP"]

    def test_leading_dot_in_filter_is_tolerated(self, client, tmp_path):
        (tmp_path / "zarana.zip").write_bytes(b"PK")

        resp = client.get(
            "/scan/browse", params={"path": str(tmp_path), "file_extensions": ".zip"}
        )
        names = [e["name"] for e in resp.json()["entries"]]
        assert names == ["zarana.zip"]

    def test_hidden_files_still_excluded(self, client, tmp_path):
        (tmp_path / ".hidden.zip").write_bytes(b"PK")

        resp = client.get(
            "/scan/browse", params={"path": str(tmp_path), "file_extensions": "zip"}
        )
        assert resp.json()["entries"] == []

    def test_drive_list_entries_are_dirs(self, client, monkeypatch):
        """Windows top-level drive-list response also carries is_dir so the
        frontend picker's click handler doesn't need a special case for it."""
        from app.routers import scan
        monkeypatch.setattr(scan.platform, "system", lambda: "Windows")
        monkeypatch.setattr(scan.os.path, "exists", lambda p: p == "C:\\")

        resp = client.get("/scan/browse", params={"file_extensions": "zip"})
        data = resp.json()
        assert data["is_drive_list"] is True
        assert all(e["is_dir"] is True for e in data["entries"])


class TestBrowseBootstrapRestriction:
    """With no scan roots configured, browsing is still limited to the
    bootstrap allowlist — it must not expose the whole filesystem (#41)."""

    def test_arbitrary_path_rejected_when_no_roots(self, client, tmp_path, monkeypatch):
        from app.routers import scan

        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        monkeypatch.setattr(scan, "_bootstrap_roots", lambda: [allowed])

        assert client.get("/scan/browse", params={"path": str(allowed)}).status_code == 200
        assert client.get("/scan/browse", params={"path": str(outside)}).status_code == 403


class TestBrowseRootRestriction:
    """With scan roots configured, /scan/browse allows paths under them AND under
    the bootstrap set (so the Add-Folder picker can still reach other drives to
    add a new root); anything outside both stays rejected."""

    def test_browse_bootstrap_path_allowed_with_roots_configured(self, client, tmp_path, monkeypatch):
        # Regression: once any root existed the allowlist narrowed to just the
        # roots, so the Settings "Add Folder" picker could not open any other
        # drive/folder to add. Bootstrap locations must stay browsable.
        from app.routers import scan
        root = tmp_path / "Root"
        root.mkdir()
        elsewhere = tmp_path / "Elsewhere"
        (elsewhere / "Sub").mkdir(parents=True)
        monkeypatch.setattr(scan, "_bootstrap_roots", lambda: [elsewhere])
        assert client.post("/scan/roots", json={"path": str(root)}).status_code == 200

        # Outside the configured root but inside bootstrap -> now allowed.
        resp = client.get("/scan/browse", params={"path": str(elsewhere)})
        assert resp.status_code == 200, resp.text
        assert [e["name"] for e in resp.json()["entries"]] == ["Sub"]

        # Outside BOTH the roots and bootstrap -> still rejected (#41 boundary holds).
        outside = tmp_path / "Outside"
        outside.mkdir()
        assert client.get("/scan/browse", params={"path": str(outside)}).status_code == 403

    def test_browse_allowed_under_every_configured_root(self, client, tmp_path, monkeypatch):

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

        root = tmp_path / "Root"
        outside = tmp_path / "Outside"
        root.mkdir()
        outside.mkdir()
        assert client.post("/scan/roots", json={"path": str(root)}).status_code == 200

        resp = client.get("/scan/browse", params={"path": str(outside)})
        assert resp.status_code == 403


class TestIsUnderConfiguredRoot:
    """Unit tests for the allowlist containment helper."""

    def test_child_of_filesystem_root_is_allowed(self):
        """Regression: a drive/filesystem root normpaths to a value that already
        ends in a separator (e.g. 'F:\\' on Windows, '/' on Unix). Appending
        os.sep doubled it, so every child of a drive root was wrongly rejected
        and the folder picker couldn't descend past the drive."""
        import os
        from pathlib import Path
        from app.routers.scan import _is_under_configured_root

        root = Path(os.path.normpath(os.sep))  # filesystem root for this OS
        child = root / "some_subfolder"

        assert _is_under_configured_root(child, [root]) is True
        assert _is_under_configured_root(root, [root]) is True

    def test_sibling_prefix_is_not_matched(self):
        """The fix must not over-match: 'C:/foobar' is not under 'C:/foo'."""
        from pathlib import Path
        from app.routers.scan import _is_under_configured_root

        root = Path("/tmp/foo")
        assert _is_under_configured_root(Path("/tmp/foobar"), [root]) is False
        assert _is_under_configured_root(Path("/tmp/foo/bar"), [root]) is True


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


class TestScanLaunchBusy:
    """Scan-launch endpoints must report 409 when the library is busy rather than
    a misleading 200 (STUDIO-83). The write lock — not just scanner status — is
    the gate, so a reorganize apply/undo in progress also blocks a new scan."""

    def _patch_idle(self, monkeypatch):
        # Force the fast-path status check to "not running" so the test exercises
        # the write-lock mapping, not the pre-check.
        from app.routers import scan
        monkeypatch.setattr(scan.scanner, "get_status", lambda: {"running": False})

    def test_full_scan_busy_returns_409(self, client, monkeypatch):
        from app.routers import scan
        self._patch_idle(monkeypatch)
        monkeypatch.setattr(scan.scanner, "start_full_scan", lambda: False)
        r = client.post("/scan/start")
        assert r.status_code == 409

    def test_full_scan_launch_returns_200(self, client, monkeypatch):
        from app.routers import scan
        self._patch_idle(monkeypatch)
        monkeypatch.setattr(scan.scanner, "start_full_scan", lambda: True)
        r = client.post("/scan/start")
        assert r.status_code == 200
        assert r.json()["running"] is True

    def test_creator_scan_busy_returns_409(self, client, db, monkeypatch):
        from app.models import Creator
        from app.routers import scan
        self._patch_idle(monkeypatch)
        creator = Creator(name="Busy Creator")
        db.add(creator)
        db.flush()
        monkeypatch.setattr(scan.scanner, "start_creator_scan", lambda cid: False)
        r = client.post(f"/scan/creator/{creator.id}")
        assert r.status_code == 409

    def test_creator_scan_launch_returns_200(self, client, db, monkeypatch):
        from app.models import Creator
        from app.routers import scan
        self._patch_idle(monkeypatch)
        creator = Creator(name="Ready Creator")
        db.add(creator)
        db.flush()
        monkeypatch.setattr(scan.scanner, "start_creator_scan", lambda cid: True)
        r = client.post(f"/scan/creator/{creator.id}")
        assert r.status_code == 200
        assert r.json()["running"] is True


class TestScanRootDestinationTemplate:
    """Per-root destination template on the scan-root API (STUDIO-403).

    Note the deliberate asymmetry with `layout`, which is NOT NULL and coerces
    blank to "{creator}": this column is nullable and coerces blank to NULL,
    because blank here means *inherit* rather than *use the default shape*.
    """

    def test_absent_on_create_means_inherit(self, client, tmp_path):
        resp = client.post("/scan/roots", json={"path": str(tmp_path)})
        assert resp.status_code == 200
        assert resp.json()["reorganize_template"] is None

    def test_add_root_with_a_destination_template(self, client, tmp_path):
        resp = client.post(
            "/scan/roots",
            json={"path": str(tmp_path), "reorganize_template": "{creator}/{title}"},
        )
        assert resp.status_code == 200
        assert resp.json()["reorganize_template"] == "{creator}/{title}"

    def test_add_root_rejects_an_invalid_destination_template(self, client, tmp_path):
        resp = client.post(
            "/scan/roots",
            json={"path": str(tmp_path), "reorganize_template": "{creater}"},
        )
        assert resp.status_code == 400

    def test_patch_sets_a_destination_template(self, client, tmp_path):
        root_id = client.post("/scan/roots", json={"path": str(tmp_path)}).json()["id"]

        resp = client.patch(
            f"/scan/roots/{root_id}", json={"reorganize_template": "{creator}/{title}"}
        )

        assert resp.status_code == 200
        assert resp.json()["reorganize_template"] == "{creator}/{title}"
        assert client.get("/scan/roots").json()[0]["reorganize_template"] == "{creator}/{title}"

    def test_patch_with_a_blank_string_clears_it_back_to_inheriting(self, client, tmp_path):
        """An empty string is the UI's way to say 'go back to inheriting'. It
        must store NULL, not a blank template — a blank template is not
        parseable and would 400 every preview that touched this root."""
        root_id = client.post(
            "/scan/roots",
            json={"path": str(tmp_path), "reorganize_template": "{creator}/{title}"},
        ).json()["id"]

        resp = client.patch(f"/scan/roots/{root_id}", json={"reorganize_template": ""})

        assert resp.status_code == 200
        assert resp.json()["reorganize_template"] is None

    def test_patch_rejects_an_invalid_destination_template(self, client, tmp_path):
        root_id = client.post("/scan/roots", json={"path": str(tmp_path)}).json()["id"]

        resp = client.patch(f"/scan/roots/{root_id}", json={"reorganize_template": "{creater}"})

        assert resp.status_code == 400

    def test_patching_another_field_leaves_the_template_alone(self, client, tmp_path):
        """Omitting the field is not the same as sending "" — renaming a library
        must not silently drop its destination template."""
        root_id = client.post(
            "/scan/roots",
            json={"path": str(tmp_path), "reorganize_template": "{creator}/{title}"},
        ).json()["id"]

        resp = client.patch(f"/scan/roots/{root_id}", json={"name": "minis"})

        assert resp.status_code == 200
        assert resp.json()["reorganize_template"] == "{creator}/{title}"

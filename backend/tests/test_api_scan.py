"""
Tests for the /scan/browse folder-picker endpoint.
"""


class TestBrowse:
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

"""Tests for named libraries + source→library mapping (Child A, #450)."""
from app.models import ImportSourceMapping, ScanRoot


def _make_root(db, path, name=None, is_writable=False):
    root = ScanRoot(path=path, enabled=True, layout="{creator}", name=name, is_writable=is_writable)
    db.add(root)
    db.commit()
    db.refresh(root)
    return root


class TestScanRootLibraryFields:
    def test_create_root_with_name_and_writable(self, client, db, tmp_path):
        r = client.post("/scan/roots", json={
            "path": str(tmp_path), "name": "minis", "is_writable": True,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "minis"
        assert body["is_writable"] is True

    def test_create_root_backfills_name_from_basename(self, client, db, tmp_path):
        r = client.post("/scan/roots", json={"path": str(tmp_path)})
        assert r.status_code == 200
        assert r.json()["name"] == tmp_path.name

    def test_update_root_sets_writable_and_name(self, client, db, tmp_path):
        root = _make_root(db, str(tmp_path))
        r = client.patch(f"/scan/roots/{root.id}", json={"name": "minis", "is_writable": True})
        assert r.status_code == 200
        assert r.json()["name"] == "minis"
        assert r.json()["is_writable"] is True


class TestListLibraries:
    def test_lists_only_writable_roots(self, db, client, tmp_path):
        _make_root(db, str(tmp_path / "a"), name="src", is_writable=False)
        _make_root(db, str(tmp_path / "b"), name="minis", is_writable=True)
        r = client.get("/scan/libraries")
        assert r.status_code == 200
        names = [lib["name"] for lib in r.json()]
        assert names == ["minis"]

    def test_library_exposes_write_enabled_flag(self, db, client, tmp_path):
        _make_root(db, str(tmp_path / "b"), name="minis", is_writable=True)
        r = client.get("/scan/libraries")
        # Default deployment is read-only (reorganize_write_enabled defaults False).
        assert r.json()[0]["write_enabled"] is False

    def test_backfills_name_for_legacy_writable_root(self, db, client, tmp_path):
        p = tmp_path / "legacy"
        _make_root(db, str(p), name=None, is_writable=True)
        r = client.get("/scan/libraries")
        assert r.json()[0]["name"] == "legacy"


class TestSourceMapping:
    def test_set_and_get_mapping(self, db, client, tmp_path):
        lib = _make_root(db, str(tmp_path / "lib"), name="minis", is_writable=True)
        src = str(tmp_path / "inbox")
        r = client.put("/import/source-mapping", json={"source_path": src, "library_id": lib.id})
        assert r.status_code == 200
        assert r.json() == {"source_path": src, "library_id": lib.id}
        g = client.get("/import/source-mapping", params={"path": src})
        assert g.status_code == 200
        assert g.json()["library_id"] == lib.id

    def test_get_unmapped_returns_null(self, db, client, tmp_path):
        r = client.get("/import/source-mapping", params={"path": str(tmp_path / "nope")})
        assert r.status_code == 200
        assert r.json() is None

    def test_upsert_overwrites_existing_mapping(self, db, client, tmp_path):
        lib1 = _make_root(db, str(tmp_path / "l1"), name="one", is_writable=True)
        lib2 = _make_root(db, str(tmp_path / "l2"), name="two", is_writable=True)
        src = str(tmp_path / "inbox")
        client.put("/import/source-mapping", json={"source_path": src, "library_id": lib1.id})
        client.put("/import/source-mapping", json={"source_path": src, "library_id": lib2.id})
        rows = db.query(ImportSourceMapping).filter(ImportSourceMapping.source_path == src).all()
        assert len(rows) == 1
        assert rows[0].library_id == lib2.id

    def test_rejects_non_writable_destination(self, db, client, tmp_path):
        lib = _make_root(db, str(tmp_path / "ro"), name="readonly", is_writable=False)
        r = client.put("/import/source-mapping", json={
            "source_path": str(tmp_path / "inbox"), "library_id": lib.id,
        })
        assert r.status_code == 400

    def test_rejects_unknown_library(self, db, client, tmp_path):
        r = client.put("/import/source-mapping", json={
            "source_path": str(tmp_path / "inbox"), "library_id": 99999,
        })
        assert r.status_code == 404

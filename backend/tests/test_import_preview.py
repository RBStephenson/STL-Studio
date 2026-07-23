"""Tests for GET /import/preview — pack-grouped inbox projection (Child B, #451)."""
import os

import pytest

from app.models import Creator, ImportSourceMapping, Model, ScanRoot, STLFile
from app.utils import utcnow

# Case-insensitive path matching (STUDIO-315/316) is a Windows-filesystem
# concern — os.path.normcase is a no-op on POSIX, so "Inbox" vs "INBOX" are
# genuinely different paths there and these scenarios don't apply.
windows_only = pytest.mark.skipif(os.name != "nt", reason="path-casing behavior is Windows-only")


def _creator(db, name):
    c = Creator(name=name)
    db.add(c)
    db.flush()
    return c


def _inbox_model(db, folder_path, *, creator=None, name="m", title=None,
                 character=None, notes=None, source_url=None, tags=None, n_files=1):
    m = Model(
        name=name,
        folder_path=folder_path,
        creator_id=creator.id if creator else None,
        title=title,
        character=character,
        notes=notes,
        source_url=source_url,
        tags=tags or [],
        auto_tags=[],
        is_inbox=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(m)
    db.flush()
    for i in range(n_files):
        db.add(STLFile(model_id=m.id, path=f"{folder_path}/f{i}.stl",
                       filename=f"f{i}.stl", size_bytes=1024))
    db.flush()
    return m


class TestImportPreview:
    def test_groups_creator_structured_source_into_packs(self, db, client):
        src = os.path.normpath("/tmp/source")
        ca = _creator(db, "Hijos De Pulvo")
        cb = _creator(db, "Other Pack")
        _inbox_model(db, f"{src}/Hijos De Pulvo/sculpt", creator=ca, n_files=3)
        _inbox_model(db, f"{src}/Hijos De Pulvo/busts", creator=ca, n_files=2)
        _inbox_model(db, f"{src}/Other Pack/x", creator=cb, n_files=1)
        db.commit()

        r = client.get("/import/preview", params={"source": src})
        assert r.status_code == 200
        body = r.json()
        names = {p["name"]: p for p in body["packs"]}
        assert set(names) == {"Hijos De Pulvo", "Other Pack"}
        assert names["Hijos De Pulvo"]["file_count"] == 5
        assert names["Hijos De Pulvo"]["source_path"] == os.path.join(src, "Hijos De Pulvo")
        assert len(names["Hijos De Pulvo"]["model_ids"]) == 2
        assert names["Other Pack"]["file_count"] == 1

    def test_flat_layout_source_is_single_pack(self, db, client):
        src = os.path.normpath("/tmp/flat")
        _inbox_model(db, src, name="loose", n_files=4)
        db.commit()
        r = client.get("/import/preview", params={"source": src})
        packs = r.json()["packs"]
        assert len(packs) == 1
        assert packs[0]["name"] == os.path.basename(src)
        assert packs[0]["source_path"] == src
        assert packs[0]["file_count"] == 4

    def test_representative_metadata_collapses_when_uniform(self, db, client):
        src = os.path.normpath("/tmp/src2")
        c = _creator(db, "Cr")
        _inbox_model(db, f"{src}/Pack/a", creator=c, title="Set", character="Knight")
        _inbox_model(db, f"{src}/Pack/b", creator=c, title="Set", character="Knight")
        db.commit()
        pack = client.get("/import/preview", params={"source": src}).json()["packs"][0]
        assert pack["title"] == "Set"
        assert pack["character"] == "Knight"
        assert pack["creator_name"] == "Cr"

    def test_representative_metadata_blank_when_mixed(self, db, client):
        src = os.path.normpath("/tmp/src3")
        c = _creator(db, "Cr")
        _inbox_model(db, f"{src}/Pack/a", creator=c, title="One")
        _inbox_model(db, f"{src}/Pack/b", creator=c, title="Two")
        db.commit()
        pack = client.get("/import/preview", params={"source": src}).json()["packs"][0]
        assert pack["title"] is None

    def test_inherited_library_id_from_mapping(self, db, client):
        src = os.path.normpath("/tmp/src4")
        lib = ScanRoot(path="/tmp/lib", enabled=True, layout="{creator}",
                       name="minis", is_writable=True)
        db.add(lib)
        db.flush()
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        _inbox_model(db, f"{src}/Pack/a", n_files=1)
        db.commit()
        body = client.get("/import/preview", params={"source": src}).json()
        assert body["library_id"] == lib.id

    def test_unmapped_source_has_null_library(self, db, client):
        src = os.path.normpath("/tmp/src5")
        _inbox_model(db, f"{src}/Pack/a", n_files=1)
        db.commit()
        body = client.get("/import/preview", params={"source": src}).json()
        assert body["library_id"] is None

    def test_excludes_non_inbox_models(self, db, client):
        src = os.path.normpath("/tmp/src6")
        c = _creator(db, "Cr")
        m = Model(name="reg", folder_path=f"{src}/Reg/a", creator_id=c.id,
                  tags=[], auto_tags=[], is_inbox=False,
                  created_at=utcnow(), updated_at=utcnow())
        db.add(m)
        _inbox_model(db, f"{src}/Inbox/a", creator=c, n_files=1)
        db.commit()
        packs = client.get("/import/preview", params={"source": src}).json()["packs"]
        assert {p["name"] for p in packs} == {"Inbox"}

    def test_excludes_models_outside_source(self, db, client):
        src = os.path.normpath("/tmp/src7")
        _inbox_model(db, f"{src}/In/a", n_files=1)
        _inbox_model(db, os.path.normpath("/tmp/other/Out/a"), n_files=1)
        db.commit()
        packs = client.get("/import/preview", params={"source": src}).json()["packs"]
        assert {p["name"] for p in packs} == {"In"}

    def test_empty_source_returns_no_packs(self, db, client):
        body = client.get("/import/preview", params={"source": "/tmp/nothing"}).json()
        assert body["packs"] == []

    def test_missing_source_param_is_400(self, db, client):
        r = client.get("/import/preview", params={"source": ""})
        assert r.status_code == 400


@windows_only
class TestImportPreviewCaseInsensitiveBucketing:
    """STUDIO-316: folder_path is stored with whatever case the scanner found on
    disk, but Windows paths are case-insensitive — a source queried with
    different casing than a model's stored folder_path must still bucket that
    model into its pack instead of silently dropping it."""

    def test_model_included_when_source_case_differs_from_folder_path(self, db, client, tmp_path):
        src = str(tmp_path / "Inbox")
        _inbox_model(db, os.path.join(src, "Pack", "a"), n_files=2)
        db.commit()

        queried = str(tmp_path / "INBOX")  # same folder, different case
        packs = client.get("/import/preview", params={"source": queried}).json()["packs"]
        assert {p["name"] for p in packs} == {"Pack"}
        assert packs[0]["file_count"] == 2

    def test_flat_layout_model_included_when_source_case_differs(self, db, client, tmp_path):
        src = str(tmp_path / "Flat")
        _inbox_model(db, src, name="loose", n_files=3)
        db.commit()

        queried = str(tmp_path / "FLAT")
        packs = client.get("/import/preview", params={"source": queried}).json()["packs"]
        assert len(packs) == 1
        assert packs[0]["file_count"] == 3


@windows_only
class TestImportPreviewMappingResolution:
    """STUDIO-315: preview/get-mapping must resolve a stored mapping the same
    way apply does (_mapped_source_for: normcase + longest-prefix), not a raw
    exact-string match — otherwise a case or trailing-separator difference
    between the stored and queried source hides a library mapping that apply
    itself would have found."""

    def test_preview_library_id_resolves_despite_case_difference(self, db, client, tmp_path):
        src = str(tmp_path / "Inbox")
        lib = ScanRoot(path=str(tmp_path / "lib"), enabled=True, layout="{creator}",
                       name="minis", is_writable=True)
        db.add(lib)
        db.flush()
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        _inbox_model(db, os.path.join(src, "Pack", "a"), n_files=1)
        db.commit()

        queried = str(tmp_path / "INBOX")
        body = client.get("/import/preview", params={"source": queried}).json()
        assert body["library_id"] == lib.id

    def test_source_mapping_endpoint_resolves_despite_case_difference(self, db, client, tmp_path):
        src = str(tmp_path / "Inbox")
        lib = ScanRoot(path=str(tmp_path / "lib"), enabled=True, layout="{creator}",
                       name="minis", is_writable=True)
        db.add(lib)
        db.flush()
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        db.commit()

        queried = str(tmp_path / "INBOX")
        body = client.get("/import/source-mapping", params={"path": queried}).json()
        assert body is not None
        assert body["library_id"] == lib.id

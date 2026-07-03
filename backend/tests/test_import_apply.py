"""Tests for POST /import/apply — batch-move imported packs into the mapped
library, reusing the reorganize engine (Child D, #453)."""
import os

import pytest

from app.config import settings
from app.models import Creator, ImportSourceMapping, Model, ScanRoot, STLFile
from app.services import reorganize
from app.utils import utcnow


@pytest.fixture()
def write_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "reorganize_write_enabled", True)


def _library(db, path, name="lib", primary=False):
    lib = ScanRoot(path=str(path).replace("\\", "/"), enabled=True, layout="{creator}/{character}/{title}",
                   name=name, is_writable=True)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


def _inbox_model(db, folder, *, creator=None, character=None, title=None, with_file=None):
    m = Model(name=title or "m", folder_path=str(folder).replace("\\", "/"),
              creator_id=creator.id if creator else None, character=character, title=title,
              tags=[], auto_tags=[], is_inbox=True, created_at=utcnow(), updated_at=utcnow())
    db.add(m)
    db.flush()
    if with_file:
        db.add(STLFile(model_id=m.id, path=str(with_file).replace("\\", "/"),
                       filename=os.path.basename(str(with_file)), size_bytes=1024))
    db.commit()
    return m


class TestImportApplyValidation:
    def test_requires_mapping(self, client, db, tmp_path):
        src = os.path.realpath(str(tmp_path / "inbox"))
        r = client.post("/import/apply", json={"source": src})
        assert r.status_code == 400


class TestMappedDestination:
    def test_inbox_model_anchors_to_mapped_library_not_primary(self, db, tmp_path):
        # Primary root (lowest id) is A; the source is mapped to B.
        a = _library(db, tmp_path / "A", name="A")  # primary
        b = _library(db, tmp_path / "B", name="B")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=b.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        m = _inbox_model(db, os.path.join(src, "Bust"), creator=creator, character="Joker", title="Bust")

        manifest = reorganize.build_manifest(db, None, inbox_source=src)
        entry = next(e for e in manifest.entries if e.model_id == m.id)
        assert entry.proposed_dir.startswith(str(b.path).replace("\\", "/"))
        assert not entry.proposed_dir.startswith(str(a.path).replace("\\", "/"))


class TestImportApplyReporting:
    def test_reports_ineligible_without_moving(self, client, db, tmp_path):
        lib = _library(db, tmp_path / "lib")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        db.commit()
        # No creator/character/title → unclassifiable → ineligible.
        _inbox_model(db, os.path.join(src, "loose"))

        r = client.post("/import/apply", json={"source": src})
        assert r.status_code == 200
        body = r.json()
        assert body["moved_models"] == 0
        assert body["skipped"] == 1
        assert body["ineligible"][0]["reasons"]

    def test_blocked_when_write_disabled(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "reorganize_write_enabled", False)
        lib = _library(db, tmp_path / "lib")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        r = client.post("/import/apply", json={"source": src})
        assert r.status_code == 403


class TestImportApplyMove:
    def test_moves_pack_into_mapped_library_and_clears_inbox(self, client, db, tmp_path, write_mode):
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        r = client.post("/import/apply", json={"source": src})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["moved_models"] == 1
        db.refresh(m)
        assert m.is_inbox is False
        assert m.folder_path.startswith(str(lib.path).replace("\\", "/"))
        assert not os.path.exists(str(f))

    def test_stale_source_dirs_cleaned_when_source_under_scan_root(self, client, db, tmp_path, write_mode):
        """Source inside a configured scan root: the post-apply stale-dir cleanup
        walk runs and removes the emptied pack folder. Regression guard for the
        cleanup block whose broad ``except Exception: pass`` (which also swallowed
        the internal HTTPExceptions) was replaced with typed guards + logging
        (STUDIO-60) — a successful apply must still return 200 and prune the dir."""
        root = _library(db, tmp_path / "root")
        src = os.path.realpath(str(tmp_path / "root" / "incoming"))
        db.add(ImportSourceMapping(source_path=src, library_id=root.id)); db.commit()
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "root" / "incoming" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        r = client.post("/import/apply", json={"source": src})
        assert r.status_code == 200, r.text
        assert r.json()["moved_models"] == 1
        # The emptied source pack dir is removed by the stale-dir cleanup walk.
        assert not os.path.exists(str(pack))

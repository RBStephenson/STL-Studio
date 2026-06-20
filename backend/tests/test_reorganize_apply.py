"""
Tests for library reorganize Phase 2a apply (#324).

Covers the safety contract: write-mode guard, drift abort, ineligible rejection,
cross-device (EXDEV) move, mid-batch crash leaving a replayable log with the DB
untouched, case-only rename, concurrent-scan rejection, and override repath.
The move/stat primitives are injected so we exercise EXDEV and crash paths
without a second real filesystem.
"""
import errno
import json
import os

import pytest

from app.config import settings
from app.models import GroupOverride, Model, PackOverride, STLFile
from app.services import reorganize_apply, write_lock
from app.services.reorganize_apply import ApplyError, _safe_move, apply_manifest
from tests.conftest import make_creator, make_model, make_stl_file


@pytest.fixture
def write_mode(tmp_path, monkeypatch):
    """Enable apply + point the data dir (undo log / probe) at a writable temp."""
    monkeypatch.setattr(settings, "reorganize_write_enabled", True)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/stl.db")
    return tmp_path


def _seed(db, tmp_path, **kw):
    """One creator/character/title model with a real file, deliberately placed in
    a messy `_inbox` location so the template destination differs and apply makes
    a real move (not an in-place no-op). Returns the model."""
    from app.models import Creator
    folder = tmp_path / "_inbox" / kw.get("title", "Bust")
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / kw.get("filename", "head.stl")
    f.write_bytes(b"solid\nendsolid\n")
    creator = db.query(Creator).filter_by(name=kw.get("creator_name", "Abe3D")).first() \
        or make_creator(db, name=kw.get("creator_name", "Abe3D"))
    m = make_model(db, creator, name=kw.get("title", "Bust"), character=kw.get("character", "Joker"))
    m.folder_path = str(folder).replace("\\", "/")
    m.title = kw.get("title", "Bust")
    db.commit()
    make_stl_file(db, m, filename=kw.get("filename", "head.stl"), path=str(f).replace("\\", "/"))
    db.commit()
    return m


def _root(db, tmp_path):
    from app.models import ScanRoot
    db.add(ScanRoot(path=str(tmp_path).replace("\\", "/"), enabled=True))
    db.commit()


def _preview(client):
    return client.get("/reorganize/preview").json()


class TestWriteModeGuard:
    def test_apply_refused_when_disabled(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "reorganize_write_enabled", False)
        _root(db, tmp_path)
        _seed(db, tmp_path)
        mid = _preview(client)["manifest_id"]
        resp = client.post("/reorganize/apply", json={"manifest_id": mid, "entry_ids": []})
        assert resp.status_code == 403


class TestApplyHappyPath:
    def test_moves_files_and_repaths_db(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m = _seed(db, tmp_path, character="Joker", title="Bust")
        # Put it somewhere that needs to move: rename character on disk mismatch.
        # The model currently lives at .../Joker/Bust; template dest is the same,
        # so force a move by seeding a model whose folder differs from template.
        preview = _preview(client)
        entry = preview["entries"][0]
        mid = preview["manifest_id"]

        resp = client.post("/reorganize/apply",
                           json={"manifest_id": mid, "entry_ids": [m.id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["moved_models"] == 1
        assert data["moved_files"] == 1
        # File now lives at the proposed path.
        assert os.path.exists(entry["files"][0]["proposed_path"])
        db.refresh(m)
        assert m.folder_path == entry["proposed_dir"]
        # Undo log written beside the DB.
        assert os.path.exists(data["undo_log"])
        lines = [json.loads(l) for l in open(data["undo_log"]) if l.strip()]
        assert len(lines) == 1 and lines[0]["status"] == "done"


class TestDrift:
    def test_aborts_when_source_changed(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        preview = _preview(client)
        mid = preview["manifest_id"]
        src = preview["entries"][0]["files"][0]["current_path"]
        # Mutate the source after preview → fingerprint drift.
        with open(src, "ab") as fh:
            fh.write(b"MORE")
        resp = client.post("/reorganize/apply",
                           json={"manifest_id": mid, "entry_ids": [m.id]})
        assert resp.status_code == 409
        assert "drifted" in resp.json()["detail"]
        # File NOT moved (still at source).
        assert os.path.exists(src)


class TestIneligible:
    def test_ineligible_entry_rejected(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m = _seed(db, tmp_path, character=None)  # unclassifiable → ineligible
        # character=None means folder uses "Joker"? rebuild without character:
        preview = _preview(client)
        mid = preview["manifest_id"]
        resp = client.post("/reorganize/apply",
                           json={"manifest_id": mid, "entry_ids": [m.id]})
        assert resp.status_code == 409


class TestSafeMovePrimitive:
    def test_cross_device_exdev_copies(self, tmp_path, monkeypatch):
        src = tmp_path / "a" / "head.stl"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"payload")
        dst = tmp_path / "b" / "head.stl"

        real_rename = os.rename
        calls = {"n": 0}

        def fake_rename(a, b):
            # First call (the fast-path same-device rename) raises EXDEV; the
            # temp-name dance inside the copy branch must still use real rename.
            if calls["n"] == 0 and str(b) == str(dst):
                calls["n"] += 1
                raise OSError(errno.EXDEV, "cross-device")
            return real_rename(a, b)

        monkeypatch.setattr(os, "rename", fake_rename)
        _safe_move(str(src), str(dst))
        assert dst.read_bytes() == b"payload"
        assert not src.exists()

    def test_never_overwrites_existing_destination(self, tmp_path):
        src = tmp_path / "a" / "head.stl"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"src")
        dst = tmp_path / "b" / "head.stl"
        dst.parent.mkdir(parents=True)
        dst.write_bytes(b"existing")
        with pytest.raises(FileExistsError):
            _safe_move(str(src), str(dst))
        assert dst.read_bytes() == b"existing"  # untouched
        assert src.exists()

    def test_case_only_rename(self, tmp_path):
        src = tmp_path / "Foo.stl"
        src.write_bytes(b"x")
        dst = tmp_path / "foo.stl"
        _safe_move(str(src), str(dst))
        # New name exists; on a case-insensitive FS it's the same inode renamed.
        names = {p.name for p in tmp_path.iterdir()}
        assert "foo.stl" in names


class TestCrashMidBatch:
    def test_partial_log_written_db_untouched(self, db, tmp_path, write_mode, client):
        _root(db, tmp_path)
        m1 = _seed(db, tmp_path, title="Bust", filename="a.stl")
        m2 = _seed(db, tmp_path, title="Cape", filename="b.stl")
        preview = _preview(client)
        mid = preview["manifest_id"]
        orig_paths = {m1.id: m1.folder_path, m2.id: m2.folder_path}

        moved = {"n": 0}

        def crashing_move(src, dst):
            if moved["n"] >= 1:
                raise OSError("simulated kill")
            moved["n"] += 1
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)

        with pytest.raises(ApplyError) as ei:
            apply_manifest(db, mid, [m1.id, m2.id], move_fn=crashing_move)
        assert ei.value.status == 500
        log_path = ei.value.detail["undo_log"]
        # Exactly one completed move recorded — replayable partial, not truncated.
        lines = [l for l in open(log_path) if l.strip()]
        assert len(lines) == 1
        # DB NOT repathed (2a leaves recovery to the log / 2b undo).
        db.refresh(m1)
        db.refresh(m2)
        assert m1.folder_path == orig_paths[m1.id]
        assert m2.folder_path == orig_paths[m2.id]


class TestConcurrentScanRejected:
    def test_apply_refused_while_scan_holds_lock(self, db, tmp_path, write_mode, client):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        mid = _preview(client)["manifest_id"]
        assert write_lock.try_acquire_for_scan() is True
        try:
            resp = client.post("/reorganize/apply",
                               json={"manifest_id": mid, "entry_ids": [m.id]})
            assert resp.status_code == 409
        finally:
            write_lock.release_scan()


def _apply(client, mid, ids):
    return client.post("/reorganize/apply", json={"manifest_id": mid, "entry_ids": ids})


class TestUndo:
    def test_undo_restores_files_and_db(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        preview = _preview(client)
        mid = preview["manifest_id"]
        entry = preview["entries"][0]
        src = entry["files"][0]["current_path"]
        dst = entry["files"][0]["proposed_path"]
        assert _apply(client, mid, [m.id]).status_code == 200
        assert os.path.exists(dst) and not os.path.exists(src)

        resp = client.post("/reorganize/undo", json={"manifest_id": mid})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["reversed_files"] == 1
        assert data["skipped"] == []
        # File back at source, destination gone.
        assert os.path.exists(src) and not os.path.exists(dst)
        db.refresh(m)
        # folder_path restored to the original source dir.
        assert m.folder_path == src.rsplit("/", 1)[0]

    def test_undo_is_idempotent(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        mid = _preview(client)["manifest_id"]
        _apply(client, mid, [m.id])
        first = client.post("/reorganize/undo", json={"manifest_id": mid}).json()
        assert first["reversed_files"] == 1
        # Second run: nothing left to reverse, everything skipped (not an error).
        second = client.post("/reorganize/undo", json={"manifest_id": mid}).json()
        assert second["reversed_files"] == 0
        assert all(s["reason"] == "missing" for s in second["skipped"])

    def test_undo_skips_drifted_destination(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        preview = _preview(client)
        mid = preview["manifest_id"]
        dst = preview["entries"][0]["files"][0]["proposed_path"]
        _apply(client, mid, [m.id])
        # User edits the moved file after apply.
        with open(dst, "ab") as fh:
            fh.write(b"EDIT")
        resp = client.post("/reorganize/undo", json={"manifest_id": mid}).json()
        assert resp["reversed_files"] == 0
        assert resp["skipped"][0]["reason"] == "drift"
        assert os.path.exists(dst)  # left in place

    def test_undo_refuses_to_clobber_occupied_origin(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        preview = _preview(client)
        mid = preview["manifest_id"]
        src = preview["entries"][0]["files"][0]["current_path"]
        _apply(client, mid, [m.id])
        # Something new appears at the original location.
        os.makedirs(os.path.dirname(src), exist_ok=True)
        with open(src, "wb") as fh:
            fh.write(b"new occupant")
        resp = client.post("/reorganize/undo", json={"manifest_id": mid}).json()
        assert resp["reversed_files"] == 0
        assert resp["skipped"][0]["reason"] == "origin_occupied"
        assert open(src, "rb").read() == b"new occupant"

    def test_undo_no_log_is_404(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        _seed(db, tmp_path)
        mid = _preview(client)["manifest_id"]  # previewed but never applied
        resp = client.post("/reorganize/undo", json={"manifest_id": mid})
        assert resp.status_code == 404

    def test_undo_refused_when_disabled(self, client, db, tmp_path, write_mode, monkeypatch):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        mid = _preview(client)["manifest_id"]
        _apply(client, mid, [m.id])
        monkeypatch.setattr(settings, "reorganize_write_enabled", False)
        resp = client.post("/reorganize/undo", json={"manifest_id": mid})
        assert resp.status_code == 403


class TestManifestIdValidation:
    @pytest.mark.parametrize("bad_id", ["../../etc/passwd", "abc", "../" * 5, "g" * 32])
    def test_apply_rejects_non_token_manifest_id(self, client, db, tmp_path, write_mode, bad_id):
        _root(db, tmp_path)
        _seed(db, tmp_path)
        resp = client.post("/reorganize/apply", json={"manifest_id": bad_id, "entry_ids": []})
        assert resp.status_code == 400

    def test_undo_rejects_non_token_manifest_id(self, client, db, tmp_path, write_mode):
        resp = client.post("/reorganize/undo", json={"manifest_id": "../../evil"})
        assert resp.status_code == 400


class TestOverrideRepath:
    def test_pack_and_group_overrides_repathed(self, db, tmp_path, write_mode, client):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        old = m.folder_path
        db.add(PackOverride(path=old))
        db.add(GroupOverride(path=old, character="Joker"))
        db.commit()
        preview = _preview(client)
        entry = preview["entries"][0]
        mid = preview["manifest_id"]
        # Only meaningful if it actually moves; skip if in-place.
        if entry["kind"] == "in_place":
            pytest.skip("destination equals source — no repath to verify")
        resp = client.post("/reorganize/apply",
                           json={"manifest_id": mid, "entry_ids": [m.id]})
        assert resp.status_code == 200
        new_dir = entry["proposed_dir"]
        assert db.query(PackOverride).filter_by(path=new_dir).first() is not None
        assert db.query(GroupOverride).filter_by(path=new_dir).first() is not None

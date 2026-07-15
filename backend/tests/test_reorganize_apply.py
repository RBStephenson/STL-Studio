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
from app.models import PackOverride
from app.services import write_lock
from app.services.reorganize_apply import ApplyError, _safe_move, apply_manifest
from tests.conftest import make_creator, make_model, make_stl_file, set_reorganize_enabled


@pytest.fixture
def write_mode(tmp_path, monkeypatch, db):
    """Enable apply + point the data dir (undo log / probe) at a writable temp."""
    set_reorganize_enabled(db, True)
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
    def test_apply_refused_when_disabled(self, client, db, tmp_path):
        set_reorganize_enabled(db, False)
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


class TestPackageApply:
    def test_moves_package_tree_and_repaths_nested_models(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3d")
        package = tmp_path / "MessyCreatorFolder" / "2B" / "1_4 2B YoRHa - Abe3D"
        alternate = package / "Alternate"
        alternate.mkdir(parents=True)
        base_file = package / "Base.stl"
        alt_file = alternate / "Head.stl"
        notes = package / "README.txt"
        shared_image = package.parent / "img" / "preview.jpg"
        shared_image.parent.mkdir()
        base_file.write_bytes(b"base")
        alt_file.write_bytes(b"alt")
        notes.write_text("keep me", encoding="utf-8")
        shared_image.write_bytes(b"jpg")
        standard = make_model(db, creator, name="2B", character="2B")
        standard.folder_path = str(package).replace("\\", "/")
        standard.other_files = [str(notes).replace("\\", "/")]
        standard.thumbnail_path = str(shared_image).replace("\\", "/")
        alt_model = make_model(db, creator, name="Alternative", character="2B")
        alt_model.folder_path = str(alternate).replace("\\", "/")
        db.commit()
        make_stl_file(db, standard, filename="Base.stl", path=str(base_file).replace("\\", "/"))
        make_stl_file(db, alt_model, filename="Head.stl", path=str(alt_file).replace("\\", "/"))
        db.commit()
        client.patch("/settings", json={"reorganize_package_mode_enabled": True})

        preview = client.get("/reorganize/preview", params={"template": "{creator}/{character}"}).json()
        entry = preview["entries"][0]
        response = client.post("/reorganize/apply", json={
            "manifest_id": preview["manifest_id"], "entry_ids": [entry["model_id"]],
        })

        assert response.status_code == 200, response.text
        assert response.json()["moved_models"] == 2
        destination = entry["proposed_dir"]
        assert os.path.exists(destination + "/Base.stl")
        assert os.path.exists(destination + "/Alternate/Head.stl")
        assert os.path.exists(destination + "/README.txt")
        character_destination = destination.rsplit("/", 1)[0]
        assert os.path.exists(character_destination + "/img/preview.jpg")
        db.refresh(standard)
        db.refresh(alt_model)
        assert standard.folder_path == destination
        assert standard.other_files == [destination + "/README.txt"]
        assert standard.thumbnail_path == character_destination + "/img/preview.jpg"
        assert alt_model.folder_path == destination + "/Alternate"

        undo = client.post("/reorganize/undo", json={"manifest_id": preview["manifest_id"]})
        assert undo.status_code == 200, undo.text
        assert os.path.exists(str(base_file))
        assert os.path.exists(str(alt_file))
        assert os.path.exists(str(notes))
        assert os.path.exists(str(shared_image))
        db.refresh(standard)
        db.refresh(alt_model)
        assert standard.folder_path == str(package).replace("\\", "/")
        assert standard.other_files == [str(notes).replace("\\", "/")]
        assert standard.thumbnail_path == str(shared_image).replace("\\", "/")
        assert alt_model.folder_path == str(alternate).replace("\\", "/")

    def test_partial_character_selection_retains_shared_assets(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        creator = make_creator(db, name="Abe3d")
        character = tmp_path / "MessyCreator" / "Ada Wong"
        first_dir = character / "Release One"
        second_dir = character / "Release Two"
        image = character / "img" / "preview.jpg"
        first_dir.mkdir(parents=True)
        second_dir.mkdir()
        image.parent.mkdir()
        first_file = first_dir / "body.stl"
        second_file = second_dir / "alt.stl"
        first_file.write_bytes(b"one")
        second_file.write_bytes(b"two")
        image.write_bytes(b"jpg")
        first = make_model(db, creator, name="Release One", character="Ada Wong")
        second = make_model(db, creator, name="Release Two", character="Ada Wong")
        first.folder_path = str(first_dir).replace("\\", "/")
        second.folder_path = str(second_dir).replace("\\", "/")
        first.thumbnail_path = str(image).replace("\\", "/")
        db.commit()
        make_stl_file(db, first, filename="body.stl", path=str(first_file).replace("\\", "/"))
        make_stl_file(db, second, filename="alt.stl", path=str(second_file).replace("\\", "/"))
        db.commit()
        client.patch("/settings", json={"reorganize_package_mode_enabled": True})

        preview = client.get("/reorganize/preview", params={"template": "{creator}/{character}"}).json()
        owner = next(entry for entry in preview["entries"] if entry["shared_files"])
        response = client.post("/reorganize/apply", json={
            "manifest_id": preview["manifest_id"], "entry_ids": [owner["model_id"]],
        })

        assert response.status_code == 200, response.text
        assert image.exists()
        db.refresh(first)
        assert first.thumbnail_path == str(image).replace("\\", "/")

        undo = client.post("/reorganize/undo", json={"manifest_id": preview["manifest_id"]})
        assert undo.status_code == 200, undo.text
        complete = client.get("/reorganize/preview", params={"template": "{creator}/{character}"}).json()
        complete_owner = next(entry for entry in complete["entries"] if entry["shared_files"])
        complete_apply = client.post("/reorganize/apply", json={
            "manifest_id": complete["manifest_id"],
            "entry_ids": [entry["model_id"] for entry in complete["entries"]],
        })

        assert complete_apply.status_code == 200, complete_apply.text
        assert os.path.exists(complete_owner["character_proposed_dir"] + "/img/preview.jpg")
        assert not character.exists()
        db.refresh(first)
        assert first.thumbnail_path == complete_owner["character_proposed_dir"] + "/img/preview.jpg"


class TestOnProgress:
    """on_progress(moved, total) is purely additive — no callback means no
    behavior change (covered above); with one, it must fire once per moved
    file with an accurate running count (STUDIO-XX, import-apply progress bar)."""

    def test_on_progress_called_once_per_file_with_accurate_counts(self, db, tmp_path, write_mode, client):
        _root(db, tmp_path)
        m1 = _seed(db, tmp_path, character="Joker", title="Bust")
        m2 = _seed(db, tmp_path, character="Riddler", title="Cane")
        mid = _preview(client)["manifest_id"]

        calls: list[tuple[int, int]] = []
        result = apply_manifest(
            db, mid, [m1.id, m2.id], on_progress=lambda moved, total: calls.append((moved, total)),
        )
        assert result.moved_files == 2
        assert calls == [(1, 2), (2, 2)]


class TestInboxEndToEnd:
    """#428: an inbox model (outside every scan root) must be eligible in preview,
    move into the managed library on apply (clearing is_inbox), and return to its
    inbox source on undo (restoring is_inbox)."""

    def test_inbox_preview_apply_undo(self, client, db, tmp_path, write_mode):
        from app.models import ScanRoot

        # Managed library = the destination scan root.
        lib = tmp_path / "library"
        lib.mkdir()
        db.add(ScanRoot(path=str(lib).replace("\\", "/"), enabled=True))
        db.commit()

        # Inbox model lives OUTSIDE the scan root.
        inbox = tmp_path / "loose" / "Bust"
        inbox.mkdir(parents=True)
        src_file = inbox / "head.stl"
        src_file.write_bytes(b"solid\nendsolid\n")
        src_str = str(src_file).replace("\\", "/")
        inbox_str = str(inbox).replace("\\", "/")

        creator = make_creator(db, name="Abe3D")
        m = make_model(db, creator, name="Bust", character="Joker")
        m.folder_path = inbox_str
        m.title = "Bust"
        m.is_inbox = True
        db.commit()
        make_stl_file(db, m, filename="head.stl", path=src_str)
        db.commit()

        # Preview: inbox model is eligible and anchored under the library root.
        preview = _preview(client)
        entry = next(e for e in preview["entries"] if e["model_id"] == m.id)
        assert entry["eligible"] is True
        assert entry["escapes_scan_root"] is False
        assert entry["proposed_dir"].startswith(str(lib).replace("\\", "/"))
        mid = preview["manifest_id"]
        dest_file = entry["files"][0]["proposed_path"]

        # Apply: file moves into the library; is_inbox cleared.
        resp = client.post("/reorganize/apply",
                           json={"manifest_id": mid, "entry_ids": [m.id]})
        assert resp.status_code == 200, resp.text
        assert os.path.exists(dest_file)
        assert not os.path.exists(src_str)
        db.refresh(m)
        assert m.folder_path == entry["proposed_dir"]
        assert m.is_inbox is False

        # Undo: file returns to the inbox source; is_inbox restored.
        resp = client.post("/reorganize/undo", json={"manifest_id": mid})
        assert resp.status_code == 200, resp.text
        assert os.path.exists(src_str)
        assert not os.path.exists(dest_file)
        db.refresh(m)
        assert m.folder_path == inbox_str
        assert m.is_inbox is True


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

    def test_undo_refused_when_disabled(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        mid = _preview(client)["manifest_id"]
        _apply(client, mid, [m.id])
        set_reorganize_enabled(db, False)
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


class TestPathConfinement:
    def test_confine_rejects_outside_root(self, tmp_path):
        from app.services.reorganize_apply import _confine
        root = os.path.normpath(os.path.abspath(str(tmp_path)))
        # Inside → returned normalized.
        inside = str(tmp_path / "Abe3D" / "head.stl")
        assert _confine(inside, [root]).startswith(root)
        # Outside / traversal → rejected.
        with pytest.raises(ApplyError):
            _confine("/etc/passwd", [root])
        with pytest.raises(ApplyError):
            _confine(str(tmp_path / ".." / "evil.stl"), [root])

    def test_apply_aborts_when_paths_escape_roots(self, client, db, tmp_path, write_mode):
        from app.models import ScanRoot
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        mid = _preview(client)["manifest_id"]
        # Drop the scan root → nothing is confined anymore → apply must refuse,
        # not move files to paths it can no longer vouch for (tampered-manifest
        # defense-in-depth).
        db.query(ScanRoot).delete()
        db.commit()
        resp = client.post("/reorganize/apply", json={"manifest_id": mid, "entry_ids": [m.id]})
        assert resp.status_code == 400


class TestOverrideRepath:
    def test_pack_override_repathed(self, db, tmp_path, write_mode, client):
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        old = m.folder_path
        db.add(PackOverride(path=old))
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

    def test_no_group_pin_survives_a_move_with_no_repathing(self, db, tmp_path, write_mode, client):
        """Model.no_group (#678 Phase 5) lives on the Model row, not a path-keyed
        override table — it should just travel with the model, no repath logic
        needed (unlike the retired GroupOverride mechanism this replaces)."""
        _root(db, tmp_path)
        m = _seed(db, tmp_path)
        m.no_group = True
        db.commit()
        preview = _preview(client)
        entry = preview["entries"][0]
        mid = preview["manifest_id"]
        if entry["kind"] == "in_place":
            pytest.skip("destination equals source — no move to verify")
        resp = client.post("/reorganize/apply",
                           json={"manifest_id": mid, "entry_ids": [m.id]})
        assert resp.status_code == 200
        db.refresh(m)
        assert m.no_group is True


class TestImageMoves:
    """A model's own gallery images move alongside its STL files (previously
    only STLs moved, leaving images — and therefore the source folder —
    behind)."""

    def _seed_with_image(self, db, tmp_path, set_primary=False):
        from app.models import Creator
        folder = tmp_path / "_inbox" / "Bust"
        folder.mkdir(parents=True, exist_ok=True)
        stl = folder / "head.stl"
        stl.write_bytes(b"solid\nendsolid\n")
        img = folder / "cover.jpg"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        creator = db.query(Creator).filter_by(name="Abe3D").first() or make_creator(db, name="Abe3D")
        m = make_model(db, creator, name="Bust", character="Joker")
        m.folder_path = str(folder).replace("\\", "/")
        m.title = "Bust"
        img_path = str(img).replace("\\", "/")
        m.image_paths = [img_path]
        m.thumbnail_path = img_path
        if set_primary:
            m.primary_image_path = img_path
        db.commit()
        make_stl_file(db, m, filename="head.stl", path=str(stl).replace("\\", "/"))
        db.commit()
        return m, img_path

    def test_image_moves_with_stl_and_repaths_model_fields(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m, img_path = self._seed_with_image(db, tmp_path, set_primary=True)
        mid = _preview(client)["manifest_id"]

        resp = _apply(client, mid, [m.id])
        assert resp.status_code == 200, resp.text
        assert resp.json()["moved_files"] == 2  # stl + image

        db.refresh(m)
        assert not os.path.exists(img_path)
        assert os.path.exists(m.thumbnail_path)
        assert m.thumbnail_path in m.image_paths
        assert m.primary_image_path == m.thumbnail_path
        # The old import folder is now genuinely empty and gets pruned.
        assert not os.path.isdir(os.path.dirname(img_path))

    def test_stale_missing_image_does_not_block_eligibility(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m, img_path = self._seed_with_image(db, tmp_path)
        os.remove(img_path)  # gone before preview, e.g. a stale gallery entry
        preview = _preview(client)
        entry = preview["entries"][0]

        assert entry["eligible"] is True
        assert entry["missing_files_on_disk"] is False
        assert len(entry["files"]) == 1  # only the STL — the missing image is skipped

    def test_shared_image_outside_model_folder_is_left_alone(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m, _ = self._seed_with_image(db, tmp_path)
        # A "character"-level image the model's gallery inherited from a
        # shared parent folder — not owned by this model, must not be moved
        # (another sibling variant could still be pointing at it).
        shared_img = tmp_path / "_inbox" / "shared.jpg"
        shared_img.write_bytes(b"\x89PNG\r\n\x1a\n")
        shared_path = str(shared_img).replace("\\", "/")
        m.image_paths = [*m.image_paths, shared_path]
        db.commit()

        mid = _preview(client)["manifest_id"]
        resp = _apply(client, mid, [m.id])
        assert resp.status_code == 200, resp.text

        assert shared_img.exists()
        db.refresh(m)
        assert shared_path in m.image_paths

    def test_undo_restores_image_file_and_model_fields(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m, img_path = self._seed_with_image(db, tmp_path)
        mid = _preview(client)["manifest_id"]
        _apply(client, mid, [m.id])
        db.refresh(m)
        moved_thumb = m.thumbnail_path
        assert os.path.exists(moved_thumb)

        resp = client.post("/reorganize/undo", json={"manifest_id": mid})
        assert resp.status_code == 200, resp.text
        assert resp.json()["reversed_files"] == 2  # stl + image
        assert not os.path.exists(moved_thumb)
        assert os.path.exists(img_path)

        db.refresh(m)
        assert m.thumbnail_path == img_path
        assert img_path in m.image_paths


class TestImageCollisionSkip:
    """A collision on a model's own tracked image (not one of its STL files)
    is skipped rather than failing the whole batch — the file might be
    incidental marketing art bundled with a download, or debris from an
    earlier interrupted apply; unlike an STL collision, it isn't worth
    aborting an otherwise-successful move over (#884)."""

    def _seed_with_image(self, db, tmp_path):
        from app.models import Creator
        folder = tmp_path / "_inbox" / "Bust"
        folder.mkdir(parents=True, exist_ok=True)
        stl = folder / "head.stl"
        stl.write_bytes(b"solid\nendsolid\n")
        img = folder / "carousel.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        creator = db.query(Creator).filter_by(name="Abe3D").first() or make_creator(db, name="Abe3D")
        m = make_model(db, creator, name="Bust", character="Joker")
        m.folder_path = str(folder).replace("\\", "/")
        m.title = "Bust"
        img_path = str(img).replace("\\", "/")
        m.image_paths = [img_path]
        db.commit()
        make_stl_file(db, m, filename="head.stl", path=str(stl).replace("\\", "/"))
        db.commit()
        return m, img_path

    def test_colliding_image_is_skipped_stl_still_moves(self, client, db, tmp_path, write_mode):
        _root(db, tmp_path)
        m, img_path = self._seed_with_image(db, tmp_path)
        preview = _preview(client)
        entry = preview["entries"][0]
        mid = preview["manifest_id"]
        image_file = next(f for f in entry["files"] if f["kind"] == "image")
        stray_dest = image_file["proposed_path"]
        os.makedirs(os.path.dirname(stray_dest), exist_ok=True)
        with open(stray_dest, "wb") as fh:
            fh.write(b"unrelated stray file")

        resp = _apply(client, mid, [m.id])
        assert resp.status_code == 200, resp.text
        assert resp.json()["moved_files"] == 1  # only the STL — the image was skipped

        db.refresh(m)
        assert os.path.exists(img_path)  # left in place, unmoved
        assert img_path in m.image_paths  # DB unchanged for the skipped image
        with open(stray_dest, "rb") as fh:
            assert fh.read() == b"unrelated stray file"  # stray file untouched

    def test_stl_collision_still_hard_fails_the_batch(self, client, db, tmp_path, write_mode):
        """The leniency above is image-only — an STL file colliding with an
        existing destination still aborts the whole batch, exactly as before."""
        _root(db, tmp_path)
        m, img_path = self._seed_with_image(db, tmp_path)
        preview = _preview(client)
        entry = preview["entries"][0]
        mid = preview["manifest_id"]
        stl_file = next(f for f in entry["files"] if f["kind"] == "stl")
        stray_dest = stl_file["proposed_path"]
        os.makedirs(os.path.dirname(stray_dest), exist_ok=True)
        with open(stray_dest, "wb") as fh:
            fh.write(b"unrelated stray file")

        resp = _apply(client, mid, [m.id])
        assert resp.status_code == 500
        assert "already exists" in resp.json()["detail"]["message"]
        db.refresh(m)
        assert os.path.exists(img_path)  # nothing moved — image untouched too
        assert m.folder_path == str(tmp_path / "_inbox" / "Bust").replace("\\", "/")

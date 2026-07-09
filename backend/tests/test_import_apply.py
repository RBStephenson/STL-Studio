"""Tests for POST /import/apply — batch-move imported packs into the mapped
library, reusing the reorganize engine (Child D, #453).

Apply now runs as a background job (STUDIO-XX): POST returns immediately with
``{started, result}`` and, when started, the caller polls GET
/import/apply/status. ``_apply_and_wait`` below posts and blocks on the shared
job runner so tests stay deterministic instead of polling on a wall clock."""
import os

import pytest

from app.models import Creator, ImportSourceMapping, Model, ScanRoot, STLFile
from app.routers.imports import _IMPORT_APPLY_KEY
from app.services import reorganize
from app.services.job_runner import runner
from app.utils import utcnow
from tests.conftest import set_reorganize_enabled


@pytest.fixture()
def write_mode(db):
    set_reorganize_enabled(db, True)


def _apply_and_wait(client, source, expected_status=200):
    """POST /import/apply and, if a background job started, block until it
    finishes, returning (http_status, result_dict) with the same shape the
    old synchronous endpoint returned directly."""
    r = client.post("/import/apply", json={"source": source})
    if r.status_code != expected_status:
        return r.status_code, r.json()
    body = r.json()
    if not body["started"]:
        return r.status_code, body["result"]
    assert runner.wait(_IMPORT_APPLY_KEY, timeout=10), "import-apply job did not finish"
    status = client.get("/import/apply/status").json()
    assert not status["running"]
    return r.status_code, status["result"]


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

        status, body = _apply_and_wait(client, src)
        assert status == 200
        assert body["moved_models"] == 0
        assert body["skipped"] == 1
        assert body["ineligible"][0]["reasons"]

    def test_blocked_when_write_disabled(self, client, db, tmp_path):
        set_reorganize_enabled(db, False)
        lib = _library(db, tmp_path / "lib")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        # The reorganize_enabled gate lives inside apply_manifest, which now
        # runs on the background job thread — POST still starts a job (the
        # manifest built ahead of it doesn't check the flag), and the 403
        # surfaces via the job's error field instead of the HTTP response.
        r = client.post("/import/apply", json={"source": src})
        assert r.status_code == 200
        assert runner.wait(_IMPORT_APPLY_KEY, timeout=10)
        status = client.get("/import/apply/status").json()
        assert not status["running"]
        assert "disabled" in (status["error"] or "").lower()


class TestImportApplyMove:
    def test_moves_pack_into_mapped_library_and_clears_inbox(self, client, db, tmp_path, write_mode):
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
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

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 1
        # The emptied source pack dir is removed by the stale-dir cleanup walk.
        assert not os.path.exists(str(pack))


class TestImportApplyScoping:
    """Regression coverage for the source -> entry.path scoping bug: apply
    called with a specific pack subfolder must move only that pack, even
    though ImportSourceMapping is only ever stored for the top-level root."""

    def test_apply_scoped_to_one_pack_leaves_sibling_pack_untouched(
        self, client, db, tmp_path, write_mode,
    ):
        lib = _library(db, tmp_path / "library")
        root = os.path.realpath(str(tmp_path / "inbox"))
        # Mapping is stored on the top-level root, as the /import UI does —
        # never on an individual pack subfolder.
        db.add(ImportSourceMapping(source_path=root, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()

        pack_a = tmp_path / "inbox" / "PackA"; pack_a.mkdir(parents=True)
        fa = pack_a / "head.stl"; fa.write_bytes(b"solid\nendsolid\n")
        model_a = _inbox_model(db, pack_a, creator=creator, character="A", title="PackA", with_file=fa)

        pack_b = tmp_path / "inbox" / "PackB"; pack_b.mkdir(parents=True)
        fb = pack_b / "head.stl"; fb.write_bytes(b"solid\nendsolid\n")
        model_b = _inbox_model(db, pack_b, creator=creator, character="B", title="PackB", with_file=fb)

        status, body = _apply_and_wait(client, os.path.realpath(str(pack_a)))
        assert status == 200, body
        assert body["moved_models"] == 1

        db.refresh(model_a)
        db.refresh(model_b)
        assert model_a.is_inbox is False
        assert not os.path.exists(str(fa))
        # Pack B was never included in this apply's manifest — it's untouched.
        assert model_b.is_inbox is True
        assert os.path.exists(str(fb))

    def test_apply_resolves_mapping_by_longest_prefix_for_pack_subfolder(
        self, client, db, tmp_path, write_mode,
    ):
        lib = _library(db, tmp_path / "library")
        root = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=root, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Pack"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        _inbox_model(db, pack, creator=creator, character="C", title="Pack", with_file=f)

        # src is the pack subfolder, not the mapped root — must still resolve.
        status, body = _apply_and_wait(client, os.path.realpath(str(pack)))
        assert status == 200, body
        assert body["moved_models"] == 1


class TestImportApplySlugifyDecoupling:
    """import-apply must not follow the Reorganize page's reorganize_slugify
    setting — the '_Inbox' sentinel creator (flat-layout imports, #? ) must
    land on disk exactly as authored, regardless of that setting's value."""

    def test_inbox_sentinel_creator_name_not_slugified_on_import(
        self, client, db, tmp_path, write_mode,
    ):
        from app.models import AppSetting
        # Default is True; set explicitly so the intent is unambiguous.
        db.merge(AppSetting(key="reorganize_slugify", value=True))
        db.commit()

        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="_Inbox"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 1
        db.refresh(m)
        # "_Inbox", not slugified to "inbox".
        assert "/_Inbox/" in m.folder_path


class TestImportApplyCollisionRetry:
    """A stray file already sitting at the computed destination (e.g. left
    over from an earlier interrupted import) must not hard-fail the whole
    batch — apply retries once with an auto-generated suffix."""

    def test_destination_collision_retries_with_suffix_instead_of_failing(
        self, client, db, tmp_path, write_mode,
    ):
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        # Pre-create the exact destination file the manifest will compute,
        # simulating a stray leftover from a prior interrupted import.
        dest_dir = tmp_path / "library" / "Abe3D" / "bust"
        dest_dir.mkdir(parents=True)
        (dest_dir / "head.stl").write_bytes(b"stray\n")

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 1
        db.refresh(m)
        assert m.is_inbox is False
        # Landed at a disambiguated destination rather than failing outright.
        assert m.folder_path != str(dest_dir).replace("\\", "/")
        assert not os.path.exists(str(f))


class TestImportApplyCleansUpNonStlFiles:
    """User request: once a pack is imported, its inbox folder must be fully
    cleaned up — including images (e.g. downloaded gallery images or ones
    added via the Upload Images feature), not just the STL files themselves."""

    def test_gallery_image_moves_with_pack_and_inbox_folder_is_pruned(
        self, client, db, tmp_path, write_mode,
    ):
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        # Simulates an image dropped into the pack folder (downloaded gallery
        # art, or an Upload Images addition) before apply — not tracked as an
        # STLFile, so it only ever moves via the non-STL cleanup pass.
        img = pack / "cover.jpg"; img.write_bytes(b"\x89PNG\r\n\x1a\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 1

        db.refresh(m)
        assert not os.path.exists(str(f))
        assert not os.path.exists(str(img))
        assert len(m.image_paths) == 1
        moved_img = m.image_paths[0]
        assert os.path.exists(moved_img)
        assert moved_img.startswith(m.folder_path)
        # The whole inbox pack folder — STL, image, and the folder itself — is gone.
        assert not os.path.isdir(str(pack))

    def test_gallery_image_lands_at_suffixed_destination_after_collision_retry(
        self, client, db, tmp_path, write_mode,
    ):
        """Regression: after the collision auto-suffix retry picks a new
        (suffixed) destination, the non-STL cleanup pass must move the pack's
        image there too — not into the stale/colliding pre-retry folder."""
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        img = pack / "cover.jpg"; img.write_bytes(b"\x89PNG\r\n\x1a\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        # Pre-create the un-suffixed destination as a stray collision, same as
        # TestImportApplyCollisionRetry above.
        dest_dir = tmp_path / "library" / "Abe3D" / "bust"
        dest_dir.mkdir(parents=True)
        (dest_dir / "head.stl").write_bytes(b"stray\n")

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 1

        db.refresh(m)
        assert m.folder_path != str(dest_dir).replace("\\", "/")
        assert len(m.image_paths) == 1
        moved_img = m.image_paths[0]
        # The image must be at the model's REAL (suffixed) folder, not the
        # stray collision folder it would have gone to pre-fix.
        assert moved_img.startswith(m.folder_path)
        assert os.path.exists(moved_img)
        # The stray collision folder is untouched — cleanup must not have
        # dumped the image there instead.
        assert not (dest_dir / "cover.jpg").exists()

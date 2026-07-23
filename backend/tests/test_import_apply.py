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

    def test_single_pack_apply_removes_untracked_leftovers_from_pack_root(
        self, client, db, tmp_path, write_mode,
    ):
        """A single-pack apply (src = one specific pack subfolder under the
        mapped root, the Import Preview per-pack button's call shape) that
        moves everything successfully should remove the WHOLE pack folder —
        including untracked scaffolding no model ever referenced (a stray
        slicer project file, a config file) — not just the STL/image content
        the reorganize engine and _move_non_stl_files know about (#1087)."""
        lib = _library(db, tmp_path / "library")
        mapped_root = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=mapped_root, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        # Untracked leftovers no Model/STLFile/image_paths ever references.
        (pack / "profile.chitubox").write_bytes(b"junk")
        (pack / "config.orynt3d").write_bytes(b"junk")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        status, body = _apply_and_wait(client, str(pack))
        assert status == 200, body
        assert body["moved_models"] == 1
        db.refresh(m)
        assert m.is_inbox is False
        assert not os.path.exists(str(pack))

    def test_import_all_apply_does_not_sweep_the_whole_mapped_root(
        self, client, db, tmp_path, write_mode,
    ):
        """The "Import All" flow applies the whole mapped source root, not one
        pack — even when nothing comes back ineligible, an unrelated/not-yet-
        scanned file sitting directly in that root must survive (#1087
        follow-up safety gate: force-removal only applies to a single-pack
        apply, never the mapped root itself)."""
        lib = _library(db, tmp_path / "library")
        mapped_root = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=mapped_root, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)
        # Sitting directly in the mapped root, unrelated to the "Bust" pack —
        # e.g. a file just dropped in and not yet scanned into any model.
        stray = tmp_path / "inbox" / "not_yet_scanned.txt"
        stray.write_bytes(b"do not delete me")

        status, body = _apply_and_wait(client, mapped_root)
        assert status == 200, body
        assert body["moved_models"] == 1
        assert os.path.exists(str(stray))

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


class TestImportApplyPreservesUnmovedFiles:
    """Regression for a real data-loss incident (#1087): the old cleanup pass
    rmtree'd a model's whole old_folder whenever its *proposed* destination
    directory already existed on disk — which just meant SOME prior run
    (interrupted mid-move, or otherwise) had already created it, not that
    THIS model's own files had actually landed there. An ineligible model
    with some files still genuinely sitting in its old_folder had them
    deleted outright, with no way to recover them."""

    def test_ineligible_models_stl_survives_when_destination_dir_preexists(
        self, client, db, tmp_path, write_mode,
    ):
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        present = pack / "still_here.stl"; present.write_bytes(b"solid\nendsolid\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=present)
        # A second STLFile row whose source is already gone — this is what
        # actually makes the model ineligible (missing_files_on_disk).
        db.add(STLFile(model_id=m.id, path=str(pack / "already_gone.stl").replace("\\", "/"),
                       filename="already_gone.stl", size_bytes=1024))
        db.commit()

        # Simulate a prior interrupted run: the proposed destination dir
        # already exists (slugify is on by default: abe3d/bust).
        dest_dir = tmp_path / "library" / "abe3d" / "bust"
        dest_dir.mkdir(parents=True)

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 0
        assert body["skipped"] == 1

        db.refresh(m)
        assert m.is_inbox is True
        # The file that was still genuinely present must NOT be deleted —
        # it stays available for a future retry once the real problem
        # (the missing sibling file) is resolved.
        assert present.exists()

    def test_ineligible_model_image_paths_remapped_when_files_moved(
        self, client, db, tmp_path, write_mode,
    ):
        """STUDIO-317: in a mixed-eligibility batch (so _run_import_apply_job's
        background path runs, not the synchronous all-ineligible shortcut), an
        ineligible model whose destination dir already exists still gets its
        non-STL files physically moved by _move_non_stl_files — image_paths /
        thumbnail_path must be remapped to the new location too, not left
        pointing at the now-emptied source folder."""
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()

        # Ineligible model: destination pre-exists (simulated interrupted prior
        # run) and it has a missing sibling STL file -> missing_files_on_disk.
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        image = pack / "preview.jpg"; image.write_bytes(b"\xff\xd8\xff")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust")
        m.image_paths = [str(image).replace("\\", "/")]
        m.thumbnail_path = str(image).replace("\\", "/")
        db.add(STLFile(model_id=m.id, path=str(pack / "gone.stl").replace("\\", "/"),
                       filename="gone.stl", size_bytes=1024))
        dest_dir = tmp_path / "library" / "abe3d" / "bust"
        dest_dir.mkdir(parents=True)

        # A second, eligible model in the same source so eligible_ids isn't
        # empty and the batch goes through the background job path.
        pack2 = tmp_path / "inbox" / "Knight"; pack2.mkdir(parents=True)
        f2 = pack2 / "head.stl"; f2.write_bytes(b"solid\nendsolid\n")
        _inbox_model(db, pack2, creator=creator, character="Knight", title="Knight", with_file=f2)
        db.commit()

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 1
        assert body["skipped"] == 1

        db.refresh(m)
        assert not image.exists()  # moved out of the source folder
        moved_image = dest_dir / "preview.jpg"
        assert moved_image.exists()
        assert [p.replace("\\", "/") for p in m.image_paths] == [str(moved_image).replace("\\", "/")]
        assert m.thumbnail_path.replace("\\", "/") == str(moved_image).replace("\\", "/")


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


class TestImportApplySlugify:
    """import-apply follows the Reorganize page's reorganize_slugify setting
    (so imports land already-organized without a separate manual Reorganize
    pass), but resolves it ONCE per apply and threads that single value through
    the whole request — including a collision retry — rather than re-reading
    the setting at each step. Re-reading it was the actual bug (#874): a
    pack's STL destination and its later non-STL/image cleanup could resolve
    two different casings if the setting changed between calls, producing a
    live DMGMinis (mixed-case) / dmgminis (lowercase) split for one pack."""

    def _set_slugify(self, db, value: bool) -> None:
        from app.models import AppSetting
        db.merge(AppSetting(key="reorganize_slugify", value=value))
        db.commit()

    def test_inbox_sentinel_creator_name_slugified_when_setting_on(
        self, client, db, tmp_path, write_mode,
    ):
        self._set_slugify(db, True)
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
        assert "/inbox/" in m.folder_path
        assert "/_Inbox/" not in m.folder_path

    def test_inbox_sentinel_creator_name_kept_as_authored_when_setting_off(
        self, client, db, tmp_path, write_mode,
    ):
        self._set_slugify(db, False)
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
        assert "/_Inbox/" in m.folder_path

    def test_collision_retry_keeps_same_slugify_value_as_initial_build(
        self, client, db, tmp_path, write_mode,
    ):
        """Regression: the retry-with-suffix path must reuse the slugify_all
        value resolved at the start of this apply, not re-read the setting —
        otherwise a mid-request change would split this pack's STL and image
        destinations across two casings again, exactly like #874."""
        self._set_slugify(db, True)
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="AbeThreeD"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        img = pack / "cover.jpg"; img.write_bytes(b"\x89PNG\r\n\x1a\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        # Pre-create the collision at the SLUGIFIED destination (lowercase
        # creator), since slugify is on for this apply.
        dest_dir = tmp_path / "library" / "abethreed" / "bust"
        dest_dir.mkdir(parents=True)
        (dest_dir / "head.stl").write_bytes(b"stray\n")

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 1
        db.refresh(m)
        # Landed at a suffixed but still-slugified destination — the retry
        # didn't flip back to as-authored casing mid-request.
        assert m.folder_path != str(dest_dir).replace("\\", "/")
        assert "/abethreed/" in m.folder_path
        assert "/AbeThreeD/" not in m.folder_path
        # The image followed to the same (slugified, suffixed) folder.
        assert len(m.image_paths) == 1
        assert m.image_paths[0].startswith(m.folder_path)


class TestImportApplySlugifyFilenames:
    """reorganize_slugify_filenames (#946) is an independent opt-in setting
    from reorganize_slugify — the latter only ever touches directory
    segments, never the STL's own filename."""

    def _set(self, db, value: bool) -> None:
        from app.models import AppSetting
        db.merge(AppSetting(key="reorganize_slugify_filenames", value=value))
        db.commit()

    def test_filename_slugified_when_setting_on(self, db, client, tmp_path, write_mode):
        self._set(db, True)
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "Cold Giant last time hollowed.stl"
        f.write_bytes(b"solid\nendsolid\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 1
        db.refresh(m)
        stl = db.query(STLFile).filter(STLFile.model_id == m.id).first()
        assert stl.filename == "cold-giant-last-time-hollowed.stl"
        assert stl.path.endswith("/cold-giant-last-time-hollowed.stl")

    def test_filename_kept_as_authored_when_setting_off(self, db, client, tmp_path, write_mode):
        self._set(db, False)
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "Cold Giant last time hollowed.stl"
        f.write_bytes(b"solid\nendsolid\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 1
        db.refresh(m)
        stl = db.query(STLFile).filter(STLFile.model_id == m.id).first()
        assert stl.filename == "Cold Giant last time hollowed.stl"


class TestImportApplySupportStatusDisambiguation:
    """A single pack with format-variant subfolders (e.g. "... (supported)" /
    "... (unsupported)") produces two inbox models sharing the same creator
    and title, so they compute to the same {creator}/{title} destination.
    Import has no interactive collision-resolution UI (unlike Reorganize), so
    this must resolve automatically rather than skip both models (#1087)."""

    def test_supported_and_unsupported_variants_import_without_collision(
        self, client, db, tmp_path, write_mode,
    ):
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Ignisaurus Clan Ignitium"); db.add(creator); db.flush()

        models = {}
        for variant in ("supported", "unsupported"):
            pack = tmp_path / "inbox" / f"Ignisaurus Clan Team Ignitium (x10) ({variant})"
            pack.mkdir(parents=True)
            f = pack / "part1.stl"; f.write_bytes(b"solid\nendsolid\n")
            models[variant] = _inbox_model(
                db, pack, creator=creator, character=None,
                title="Ignisaurus Clan Team Ignitium (x10) Prime Armored Fire Squad",
                with_file=f,
            )

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 2
        assert body["skipped"] == 0

        for variant, m in models.items():
            db.refresh(m)
            assert m.is_inbox is False
            assert m.folder_path.endswith(variant)
        assert models["supported"].folder_path != models["unsupported"].folder_path

    def test_generic_same_title_collision_with_no_variant_signal_still_blocked(
        self, client, db, tmp_path, write_mode,
    ):
        """Sanity check the fix is scoped to real distinguishing signals —
        two models that collide for no discoverable reason still skip rather
        than silently merging."""
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()

        for sub in ("files", "stl"):
            pack = tmp_path / "inbox" / "Bust" / sub
            pack.mkdir(parents=True)
            f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
            m = Model(name="Bust", folder_path=str(pack).replace("\\", "/"),
                      creator_id=creator.id, character=None, title="Bust",
                      tags=[], auto_tags=[], is_inbox=True, created_at=utcnow(), updated_at=utcnow())
            db.add(m); db.flush()
            db.add(STLFile(model_id=m.id, path=str(f).replace("\\", "/"), filename="head.stl", size_bytes=1024))
        db.commit()

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 0
        assert body["skipped"] == 2
        assert all(r == "destination collision" for i in body["ineligible"] for r in i["reasons"])

    def test_pack_root_gallery_image_shared_by_both_variants_survives_apply(
        self, client, db, tmp_path, write_mode,
    ):
        """Gallery images downloaded to the pack ROOT (not either variant's own
        subfolder) get attached to both nested models at scan time
        (boundary=inbox). Apply must copy that shared image into each
        model's own new folder and remap image_paths there — otherwise the
        path still points at the old inbox location, which the file-serving
        allowlist stops trusting the moment the model leaves inbox, and the
        gallery goes blank despite import otherwise succeeding."""
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Ignisaurus"); db.add(creator); db.flush()

        pack_root = tmp_path / "inbox"
        pack_root.mkdir(parents=True, exist_ok=True)
        shared_img = pack_root / "gallery_00.jpg"
        shared_img.write_bytes(b"\x89PNG\r\n\x1a\n")

        models = {}
        for variant in ("supported", "unsupported"):
            sub = pack_root / f"Ignisaurus (x10) ({variant})"
            sub.mkdir(parents=True)
            f = sub / "part1.stl"; f.write_bytes(b"solid\nendsolid\n")
            m = _inbox_model(db, sub, creator=creator, character=None,
                              title="Ignisaurus (x10)", with_file=f)
            # Scan-time behavior being simulated: both variants' image_paths
            # AND thumbnail_path already point at the one shared pack-root
            # image (thumbnail_path drives the Library grid card).
            m.image_paths = [str(shared_img).replace("\\", "/")]
            m.thumbnail_path = str(shared_img).replace("\\", "/")
            db.commit()
            models[variant] = m

        status, body = _apply_and_wait(client, src)
        assert status == 200, body
        assert body["moved_models"] == 2

        seen_paths = set()
        for variant, m in models.items():
            db.refresh(m)
            assert len(m.image_paths) == 1
            img_path = m.image_paths[0]
            assert img_path.startswith(m.folder_path)
            assert os.path.exists(img_path)
            seen_paths.add(img_path)
            # thumbnail_path must be relocated too, not just image_paths.
            assert m.thumbnail_path.startswith(m.folder_path)
            assert os.path.exists(m.thumbnail_path)
        # Each variant got its own copy, not a shared/aliased path.
        assert len(seen_paths) == 2
        # The original shared source file is untouched (copy, not move).
        assert shared_img.exists()


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

        # Pre-create the exact destination file the manifest will compute
        # (slugify is on by default, so the creator segment is lowercased),
        # simulating a stray leftover from a prior interrupted import.
        dest_dir = tmp_path / "library" / "abe3d" / "bust"
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
        # TestImportApplyCollisionRetry above (slugify is on by default).
        dest_dir = tmp_path / "library" / "abe3d" / "bust"
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

    def test_stale_hidden_dir_reference_dropped_even_with_no_new_images(
        self, client, db, tmp_path, write_mode,
    ):
        """A model whose image_paths already references a file inside a
        hidden directory (e.g. a leftover .manyfold derivative cache from
        before the scanner started skipping them, #903-follow-up) must lose
        that reference on apply — even when there's no real image to
        replace it with. The move loop's walk already skips hidden
        directories, so new_images ends up empty; the old `if new_images:`
        guard meant image_paths was never touched at all in that case,
        letting the stale reference survive indefinitely."""
        lib = _library(db, tmp_path / "library")
        src = os.path.realpath(str(tmp_path / "inbox"))
        db.add(ImportSourceMapping(source_path=src, library_id=lib.id))
        creator = Creator(name="Abe3D"); db.add(creator); db.flush()
        pack = tmp_path / "inbox" / "Bust"; pack.mkdir(parents=True)
        f = pack / "head.stl"; f.write_bytes(b"solid\nendsolid\n")
        hidden = pack / ".manyfold" / "derivatives"
        hidden.mkdir(parents=True)
        (hidden / "carousel.jpg").write_bytes(b"\x89PNG\r\n\x1a\n")
        m = _inbox_model(db, pack, creator=creator, character="Joker", title="Bust", with_file=f)
        # Simulate the stale pre-fix state: an earlier scan picked up the
        # hidden-dir file before the scanner started skipping them.
        m.image_paths = [str(hidden / "carousel.jpg")]
        db.commit()

        status, body = _apply_and_wait(client, src)
        assert status == 200, body

        db.refresh(m)
        assert m.image_paths == []

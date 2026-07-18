"""Tests for POST /scan/inbox and the is_inbox model flag (#428)."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.conftest import make_creator, make_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stl_tree(base: Path, structure: dict):
    """Recursively create files/directories from a dict.
    str values are file content; dict values are subdirectories."""
    for name, content in structure.items():
        if isinstance(content, dict):
            child = base / name
            child.mkdir(parents=True, exist_ok=True)
            _make_stl_tree(child, content)
        else:
            (base / name).write_text(content)


# ---------------------------------------------------------------------------
# POST /scan/inbox — validation
# ---------------------------------------------------------------------------

class TestInboxScanValidation:
    def test_missing_path_returns_400(self, client, db):
        r = client.post("/scan/inbox", json={"path": ""})
        assert r.status_code == 400
        assert "required" in r.json()["detail"].lower()

    def test_nonexistent_path_returns_400(self, client, db):
        r = client.post("/scan/inbox", json={"path": "/nonexistent/path/xyz"})
        assert r.status_code == 400
        assert "not exist" in r.json()["detail"].lower()

    def test_file_path_returns_400(self, client, db):
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            f.write(b"solid test\nendsolid")
            fpath = f.name
        try:
            r = client.post("/scan/inbox", json={"path": fpath})
            assert r.status_code == 400
            assert "not a directory" in r.json()["detail"].lower()
        finally:
            os.unlink(fpath)

    def test_configured_scan_root_returns_400(self, client, db):
        with tempfile.TemporaryDirectory() as tmpdir:
            client.post("/scan/roots", json={"path": tmpdir, "layout": "{creator}"})
            r = client.post("/scan/inbox", json={"path": tmpdir})
            assert r.status_code == 400
            assert "scan root" in r.json()["detail"].lower()

    def test_child_of_scan_root_returns_400(self, client, db):
        """Inbox path is a subdirectory of a scan root — overlap rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            child = os.path.join(tmpdir, "sub")
            os.makedirs(child)
            client.post("/scan/roots", json={"path": tmpdir, "layout": "{creator}"})
            r = client.post("/scan/inbox", json={"path": child})
            assert r.status_code == 400

    def test_parent_of_scan_root_returns_400(self, client, db):
        """Inbox path is an ancestor of a scan root — overlap rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            child = os.path.join(tmpdir, "lib")
            os.makedirs(child)
            client.post("/scan/roots", json={"path": child, "layout": "{creator}"})
            r = client.post("/scan/inbox", json={"path": tmpdir})
            assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /scan/inbox — scan already running
# ---------------------------------------------------------------------------

class TestInboxScanConflict:
    def test_409_when_scan_running(self, client, db):
        with patch("app.services.scanner.get_status", return_value={"running": True}):
            with tempfile.TemporaryDirectory() as tmpdir:
                r = client.post("/scan/inbox", json={"path": tmpdir})
        assert r.status_code == 409

    def test_409_when_write_lock_held(self, client, db):
        """Lock acquired synchronously in endpoint — 409 before thread starts."""
        from unittest.mock import MagicMock
        mock_settings = MagicMock()
        with patch("app.services.scanner.prepare_inbox_scan", return_value=False), \
             patch("app.routers.scan._configured_roots", return_value=[]), \
             patch("app.routers.scan.settings", mock_settings):
            with tempfile.TemporaryDirectory() as tmpdir:
                r = client.post("/scan/inbox", json={"path": tmpdir})
        assert r.status_code == 409
        assert "busy" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /models?is_inbox filter
# ---------------------------------------------------------------------------

class TestIsInboxFilter:
    def test_filter_returns_only_inbox_models(self, client, db):
        creator = make_creator(db)
        inbox_m = make_model(db, creator, name="Inbox Model")
        inbox_m.is_inbox = True
        make_model(db, creator, name="Normal Model")
        db.commit()

        r = client.get("/models?is_inbox=true")
        assert r.status_code == 200
        names = {m["name"] for m in r.json()["items"]}
        assert "Inbox Model" in names
        assert "Normal Model" not in names

    def test_filter_false_excludes_inbox(self, client, db):
        creator = make_creator(db)
        inbox_m = make_model(db, creator, name="Inbox Model")
        inbox_m.is_inbox = True
        make_model(db, creator, name="Normal Model")
        db.commit()

        r = client.get("/models?is_inbox=false")
        assert r.status_code == 200
        names = {m["name"] for m in r.json()["items"]}
        assert "Normal Model" in names
        assert "Inbox Model" not in names

    def test_no_filter_excludes_inbox(self, client, db):
        creator = make_creator(db)
        inbox_m = make_model(db, creator, name="Inbox Model")
        inbox_m.is_inbox = True
        make_model(db, creator, name="Normal Model")
        db.commit()

        r = client.get("/models")
        assert r.status_code == 200
        names = {m["name"] for m in r.json()["items"]}
        # Default view hides inbox models; they require ?is_inbox=true.
        assert "Inbox Model" not in names
        assert "Normal Model" in names

    def test_is_inbox_field_in_model_response(self, client, db):
        creator = make_creator(db)
        m = make_model(db, creator, name="Test")
        m.is_inbox = True
        db.commit()

        r = client.get("/models?is_inbox=true")
        assert r.status_code == 200
        item = next(i for i in r.json()["items"] if i["name"] == "Test")
        assert item["is_inbox"] is True


# ---------------------------------------------------------------------------
# scan_inbox_folder — unit tests (synchronous, no thread)
# ---------------------------------------------------------------------------

class TestScanInboxFolder:
    def test_creator_structure_indexes_subdirs_as_creators(self, client, db):
        """Approach B: each immediate subdir becomes a creator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            _make_stl_tree(inbox, {
                "Artist One": {
                    "Dragon Pack": {"dragon.stl": "solid d\nendsolid"},
                },
                "Artist Two": {
                    "Knight": {"knight.stl": "solid k\nendsolid"},
                },
                "EmptyFolder": {},
            })

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db)

        r = client.get("/models?is_inbox=true")
        assert r.json()["total"] >= 1

    def test_pseudo_creator_subdirs_with_no_further_nesting_are_indexed(self, client, db):
        """Regression: a pack folder whose immediate subdirs hold STLs
        directly (no further character/product level below them) previously
        indexed 0 models. Each subdir becomes its own pseudo-creator
        (Approach B) with creator_boundary == folder; since it has no child
        directories to recurse into, the old "creator boundary is never a
        model" rule silently dropped every file. Mirrors the real reported
        case: a pack with sibling sub-collection folders, each holding STLs
        directly and nothing more (#1048)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            _make_stl_tree(inbox, {
                "E Stairs": {
                    "a.stl": "solid a\nendsolid",
                    "b.stl": "solid b\nendsolid",
                },
                "Platforms": {
                    "c.stl": "solid c\nendsolid",
                },
            })

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db)

        r = client.get("/models?is_inbox=true")
        names = {item["name"] for item in r.json()["items"]}
        assert "E Stairs" in names
        assert "Platforms" in names

        for item in r.json()["items"]:
            if item["name"] in ("E Stairs", "Platforms"):
                detail = client.get(f"/models/{item['id']}").json()
                assert len(detail["stl_files"]) > 0

    def test_flat_structure_uses_inbox_creator(self, client, db):
        """Flat: STLs directly in inbox root → _Inbox creator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            (inbox / "thing.stl").write_text("solid t\nendsolid")

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db)

        r = client.get("/models?is_inbox=true")
        assert r.json()["total"] >= 1

    def test_inbox_flag_not_cleared_by_index_model(self, client, db):
        """_index_model called without is_inbox=True must not clear an existing True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            (inbox / "thing.stl").write_text("solid t\nendsolid")

            from app.services.scanner import scan_inbox_folder, _index_model
            from app.models import Creator as CreatorModel
            scan_inbox_folder(tmpdir, db=db)

        r = client.get("/models?is_inbox=true")
        assert r.json()["total"] >= 1
        item = r.json()["items"][0]
        assert item["is_inbox"] is True

        # Call _index_model again on the same folder WITHOUT is_inbox=True.
        # is_inbox should remain True — the function only ever sets it, never clears.
        with tempfile.TemporaryDirectory() as tmpdir2:
            inbox2 = Path(tmpdir2)
            (inbox2 / "other.stl").write_text("solid o\nendsolid")
            creator = db.query(CreatorModel).first()
            _index_model(
                folder=inbox2,
                creator=creator,
                db=db,
                creator_boundary=inbox2,
                character=None,
                stl_cache={},
                is_inbox=False,
            )
            db.commit()

        # Pre-existing inbox model unchanged
        r2 = client.get(f"/models/{item['id']}")
        assert r2.json()["is_inbox"] is True


# ---------------------------------------------------------------------------
# scan_inbox_folder(single_pack=True) — #1087
# ---------------------------------------------------------------------------

class TestSinglePackImport:
    """Import Preview's per-pack Import button (POST /import/scan-folder)
    always scopes to exactly one pack — by construction, a pack is one
    product's content, never several creators' worth. single_pack=True skips
    Approach B (every immediate subfolder -> its own creator) and instead
    treats the whole pack as one creator, delegating to _walk_for_models —
    the same product/variant detection a real scan root's creator folder
    already gets."""

    def test_format_variant_subfolders_become_one_creator_with_grouped_models(self, client, db):
        """Regression for the reported case: a pack shaped like
        "Product (supported)" / "Product (unsupported)" / "Product (chitubox)"
        — previously split into bogus per-subfolder creators (#1048-style),
        orphaning any pack-level metadata. Now: one creator (the shared
        '_Inbox' placeholder, since no creator_name is given here — #1110),
        both STL-bearing variants indexed and auto-grouped into a single
        "2 variants" card, the STL-less chitubox folder produces no model
        at all."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            _make_stl_tree(inbox, {
                "Widget Team (supported)": {
                    "a_sup.stl": "solid a\nendsolid",
                    "b_sup.stl": "solid b\nendsolid",
                },
                "Widget Team (unsupported)": {
                    "a.stl": "solid a\nendsolid",
                    "b.stl": "solid b\nendsolid",
                },
                "Widget Team (chitubox)": {
                    "a.chitubox": "not an stl",
                },
            })

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db, single_pack=True)

        from app.models import Model
        models = db.query(Model).filter(Model.is_inbox == True).all()  # noqa: E712
        assert len(models) == 2
        assert {m.creator.name for m in models} == {"_Inbox"}
        # Auto-grouped into one variant group, not left as two loose models.
        group_ids = {m.variant_group_id for m in models}
        assert len(group_ids) == 1
        assert None not in group_ids

        # The Library listing collapses the group to one representative row.
        # ModelRead (the list-item schema) only carries creator_id — creator
        # identity was already asserted above via the DB query.
        r = client.get("/models?is_inbox=true")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["variant_count"] == 2

    def test_router_scan_folder_uses_single_pack_mode(self, client, db):
        """POST /import/scan-folder (the real endpoint Import Preview calls)
        must pass single_pack=True through to the scanner — the actual scan
        run (threaded, its own DB session) is covered by the unit-level
        tests above; this just pins the router's wiring."""
        from app.models import ScanRoot
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmpdir:
            db.add(ScanRoot(path=tmpdir, enabled=True, layout="{creator}"))
            db.commit()

            with patch("app.services.scanner.start_inbox_scan", return_value=True) as mock_start:
                r = client.post("/import/scan-folder", json={"path": tmpdir})
            assert r.status_code == 200
            mock_start.assert_called_once()
            args, kwargs = mock_start.call_args
            assert kwargs.get("single_pack") is True

    def test_single_pack_with_no_subfolders_still_indexes_the_pack(self, client, db):
        """A pack with STLs directly in its own root (no variant subfolders
        at all) — the plain, common case — must still work under
        single_pack=True. No creator_name given, so it lands in the shared
        '_Inbox' placeholder (#1110)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            (inbox / "part.stl").write_text("solid p\nendsolid")

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db, single_pack=True)

            from app.models import Model
            models = db.query(Model).filter(Model.is_inbox == True).all()  # noqa: E712
            assert len(models) == 1
            assert models[0].creator.name == "_Inbox"

        r = client.get("/models?is_inbox=true")
        assert len(r.json()["items"]) == 1

    def test_known_creator_name_resolves_directly_no_placeholder(self, client, db):
        """When the caller already knows the real creator (Import Preview's
        Creator field, typed or Fetch-populated before the user clicks
        Import), the scan attaches models to it directly — no folder-named
        placeholder is ever created, so there's nothing left to prune (#1110,
        the root-cause fix for #1108's cleanup-after-the-fact)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            (inbox / "part.stl").write_text("solid p\nendsolid")

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db, single_pack=True, creator_name="dakkadakka.store")

        from app.models import Creator, Model
        models = db.query(Model).filter(Model.is_inbox == True).all()  # noqa: E712
        assert len(models) == 1
        assert models[0].creator.name == "dakkadakka.store"
        # No placeholder named after the folder was ever created.
        assert db.query(Creator).filter(Creator.name == Path(tmpdir).name).first() is None
        assert db.query(Creator).count() == 1

    def test_two_packs_with_the_same_known_creator_share_one_row(self, client, db):
        """Multiple packs from the same creator, each imported independently
        via its own Import click, must resolve to the SAME creator row —
        not one placeholder-turned-real row per pack (#1110)."""
        with tempfile.TemporaryDirectory() as base:
            pack_a = Path(base) / "Ignisaurus Clan Ignitium"
            pack_b = Path(base) / "Ignisaurus Destroyers"
            for pack in (pack_a, pack_b):
                pack.mkdir()
                (pack / "part.stl").write_text("solid p\nendsolid")

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(str(pack_a), db=db, single_pack=True, creator_name="dakkadakka.store")
            scan_inbox_folder(str(pack_b), db=db, single_pack=True, creator_name="DakkaDakka.Store")

        from app.models import Creator, Model
        assert db.query(Creator).count() == 1
        creator = db.query(Creator).first()
        assert creator.name == "dakkadakka.store"  # first casing wins, matches resolve_creator
        models = db.query(Model).filter(Model.is_inbox == True).all()  # noqa: E712
        assert len(models) == 2
        assert {m.creator_id for m in models} == {creator.id}

    def test_blank_creator_name_falls_back_to_shared_inbox_placeholder(self, client, db):
        """An empty/whitespace-only creator_name (Creator field not filled in
        yet) lands in the shared '_Inbox' placeholder (#1110) — not a fresh
        one-off creator named after this pack's own folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            (inbox / "part.stl").write_text("solid p\nendsolid")

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db, single_pack=True, creator_name="   ")

            from app.models import Model
            models = db.query(Model).filter(Model.is_inbox == True).all()  # noqa: E712
            assert len(models) == 1
            assert models[0].creator.name == "_Inbox"

    def test_two_unenriched_packs_share_the_inbox_placeholder(self, client, db):
        """Two different, not-yet-enriched packs both land under the SAME
        '_Inbox' creator — not two separate folder-named placeholders."""
        with tempfile.TemporaryDirectory() as base:
            pack_a = Path(base) / "Pack A"
            pack_b = Path(base) / "Pack B"
            for pack in (pack_a, pack_b):
                pack.mkdir()
                (pack / "part.stl").write_text("solid p\nendsolid")

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(str(pack_a), db=db, single_pack=True)
            scan_inbox_folder(str(pack_b), db=db, single_pack=True)

        from app.models import Creator, Model
        assert db.query(Creator).filter(Creator.name == "_Inbox").count() == 1
        models = db.query(Model).filter(Model.is_inbox == True).all()  # noqa: E712
        assert len(models) == 2
        assert {m.creator.name for m in models} == {"_Inbox"}

    def test_router_scan_folder_passes_creator_name_through(self, client, db):
        from app.models import ScanRoot
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmpdir:
            db.add(ScanRoot(path=tmpdir, enabled=True, layout="{creator}"))
            db.commit()

            with patch("app.services.scanner.start_inbox_scan", return_value=True) as mock_start:
                r = client.post(
                    "/import/scan-folder",
                    json={"path": tmpdir, "creator_name": "dakkadakka.store"},
                )
            assert r.status_code == 200
            args, kwargs = mock_start.call_args
            assert kwargs.get("creator_name") == "dakkadakka.store"

    def test_flat_layout_auto_links_sup_files_by_filename_instead_of_splitting(self, client, db):
        """A pack with NO variant subfolders, distinguishing supported vs
        unsupported purely by a "-sup" filename suffix, has no folder signal
        for _walk_for_models to split on — everything lands on one model.
        Rather than leaving the -sup files as unrelated duplicate entries,
        auto-link each to its base part by name (#1087 follow-up), the same
        pairing "AI Organize > Link sups" already offers manually — the
        user's explicit choice over splitting into two models."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            _make_stl_tree(inbox, {
                "warrior-1.stl": "solid a\nendsolid",
                "warrior-1-sup.stl": "solid a\nendsolid",
                "warrior-2.stl": "solid b\nendsolid",
                "warrior-2-sup.stl": "solid b\nendsolid",
                "sergeant.stl": "solid c\nendsolid",  # no sup counterpart
            })

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db, single_pack=True)

        from app.models import Model, STLFile
        models = db.query(Model).filter(Model.is_inbox == True).all()  # noqa: E712
        assert len(models) == 1
        files = {f.filename: f for f in db.query(STLFile).filter_by(model_id=models[0].id).all()}
        assert len(files) == 5
        assert files["warrior-1-sup.stl"].sup_of_id == files["warrior-1.stl"].id
        assert files["warrior-2-sup.stl"].sup_of_id == files["warrior-2.stl"].id
        assert files["warrior-1.stl"].sup_of_id is None
        assert files["sergeant.stl"].sup_of_id is None

    def test_gallery_images_skip_chitubox_siblings_own_bundled_copies(self, client, db):
        """Regression (#1114): a no-STL sibling folder that's itself a
        recognized format-variant (a "(chitubox)" project-file folder next
        to "(supported)"/"(unsupported)") often bundles its own redundant
        copy of the same numbered marketing images. Sweeping those in
        padded every variant's gallery with duplicates and made the two
        variants' image counts diverge instead of matching."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox = Path(tmpdir)
            _make_stl_tree(inbox, {
                # Pack-root-shared images — legitimately swept into every variant.
                "1.jpg": "root1", "2.jpg": "root2",
                "Widget Team (supported)": {
                    "a_sup.stl": "solid a\nendsolid",
                },
                "Widget Team (unsupported)": {
                    "a.stl": "solid a\nendsolid",
                    # This variant's OWN bundled images — legitimately its own.
                    "1.jpg": "unsup1", "2.jpg": "unsup2",
                },
                "Widget Team (chitubox)": {
                    "a.chitubox": "not an stl",
                    # Redundant copies bundled alongside the project files —
                    # must NOT get swept into either variant's gallery.
                    "1.jpg": "chitubox1", "2.jpg": "chitubox2",
                },
            })

            from app.services.scanner import scan_inbox_folder
            scan_inbox_folder(tmpdir, db=db, single_pack=True)

        from app.models import Model
        models = {m.folder_path.rsplit("/", 1)[-1]: m
                  for m in db.query(Model).filter(Model.is_inbox == True).all()}  # noqa: E712
        supported = models["Widget Team (supported)"]
        unsupported = models["Widget Team (unsupported)"]

        # Neither variant's gallery includes anything from the chitubox folder.
        assert not any("chitubox" in p for p in (supported.image_paths or []))
        assert not any("chitubox" in p for p in (unsupported.image_paths or []))
        # supported: only the 2 pack-root-shared images (no own subfolder images).
        assert len(supported.image_paths or []) == 2
        # unsupported: the 2 shared + its own 2 — 4, not 4 + chitubox's 2 = 6.
        assert len(unsupported.image_paths or []) == 4

"""Tests for POST /import/install (STUDIO-101/387).

Wraps installer.install() (STUDIO-386, its own dedicated test file covers the
extraction logic itself) with flag gating, source-path allowlisting, the
writable-library check, the default-layout-only restriction, and the write
lock. These tests exercise the endpoint's own logic, not extraction.

A source built as a real folder on disk routes through copy_verified; zip
sources don't. Most of this file uses zip fixtures for the happy-path and
error-mapping coverage, with folder-source coverage kept to one dedicated test.

That split used to carry a warning that the folder-source test was "expected to
fail locally on Windows, pass in CI". It was fixed in STUDIO-408, and the
warning was wrong in a way worth remembering: copy_verified fsynced a read-only
descriptor, which POSIX allows and Windows rejects, so the folder path was
broken *for users on the platform it ships to* — not merely on a developer's
machine. A test that fails only on the deployment platform is reporting a
product bug, not a local quirk. (The warning also cited test_safe_copy.py and
test_installer.py as documenting the issue; neither ever did.)
"""
import zipfile

import pytest

from app.models import Creator, ScanRoot
from app.services import installer, write_lock
from tests.conftest import set_installer_enabled


def _make_zip(path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def _allow_source(db, path):
    """Make `path` an allowed install source (same path-injection guard
    barrier /import/source-contents' own tests use)."""
    db.add(ScanRoot(path=str(path), enabled=True, layout="{creator}"))
    db.commit()


def _library(db, path, *, writable=True, layout="{creator}"):
    lib = ScanRoot(path=str(path), enabled=True, layout=layout, is_writable=writable, name="lib")
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


@pytest.fixture()
def enabled(db):
    set_installer_enabled(db, True)


class TestFlagGating:
    def test_disabled_by_default_returns_403(self, client, db, tmp_path):
        library = _library(db, tmp_path / "library")
        r = client.post("/import/install", json={
            "source": str(tmp_path), "library_id": library.id,
            "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 403


class TestHappyPath:
    def test_zip_source_creates_creator_and_installs(self, client, db, tmp_path, enabled):
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        zip_path = source / "pack.zip"
        _make_zip(zip_path, {"Zarana/Head.stl": b"head"})
        library = _library(db, tmp_path / "library")

        r = client.post("/import/install", json={
            "source": str(zip_path), "library_id": library.id,
            "creator": "Abe3D", "character": "Zarana",
        })

        assert r.status_code == 200
        body = r.json()
        assert body["creator"] == "Abe3D"
        assert body["file_count"] == 1
        assert body["total_bytes"] == 4
        dest = tmp_path / "library" / "Abe3D" / "Zarana"
        assert body["dest"] == str(dest)
        assert (dest / "Head.stl").read_bytes() == b"head"

        creator = db.query(Creator).filter(Creator.name == "Abe3D").one()
        assert body["creator_id"] == creator.id

    def test_existing_creator_matched_case_insensitively_reuses_row(self, client, db, tmp_path, enabled):
        existing = Creator(name="Abe3D")
        db.add(existing)
        db.commit()
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        zip_path = source / "pack.zip"
        _make_zip(zip_path, {"Zarana/Head.stl": b"head"})
        library = _library(db, tmp_path / "library")

        r = client.post("/import/install", json={
            "source": str(zip_path), "library_id": library.id,
            "creator": "abe3d", "character": "Zarana",  # different casing
        })

        assert r.status_code == 200
        body = r.json()
        assert body["creator"] == "Abe3D"  # existing row's casing, not the input's
        assert body["creator_id"] == existing.id
        assert db.query(Creator).count() == 1  # no duplicate row created
        dest = tmp_path / "library" / "Abe3D" / "Zarana"  # folder uses existing casing too
        assert (dest / "Head.stl").exists()

    def test_folder_source_happy_path(self, client, db, tmp_path, enabled):
        """The one folder-source test — everything else here uses zip fixtures.
        This is the path that was broken on Windows until STUDIO-408; see the
        module docstring."""
        source = tmp_path / "downloads" / "ZaranaFolder"
        source.mkdir(parents=True)
        (source / "Head.stl").write_bytes(b"head")
        _allow_source(db, tmp_path / "downloads")
        library = _library(db, tmp_path / "library")

        r = client.post("/import/install", json={
            "source": str(source), "library_id": library.id,
            "creator": "Abe3D", "character": "Zarana",
        })

        assert r.status_code == 200
        dest = tmp_path / "library" / "Abe3D" / "Zarana"
        assert (dest / "Head.stl").read_bytes() == b"head"


class TestValidation:
    def test_blank_source_400(self, client, db, tmp_path, enabled):
        library = _library(db, tmp_path / "library")
        r = client.post("/import/install", json={
            "source": "  ", "library_id": library.id, "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 400

    def test_blank_creator_400(self, client, db, tmp_path, enabled):
        library = _library(db, tmp_path / "library")
        r = client.post("/import/install", json={
            "source": str(tmp_path), "library_id": library.id, "creator": " ", "character": "Zarana",
        })
        assert r.status_code == 400

    def test_blank_character_400(self, client, db, tmp_path, enabled):
        library = _library(db, tmp_path / "library")
        r = client.post("/import/install", json={
            "source": str(tmp_path), "library_id": library.id, "creator": "Abe3D", "character": " ",
        })
        assert r.status_code == 400

    def test_source_outside_allowed_bases_403(self, client, db, tmp_path, enabled, monkeypatch):
        # On Windows, _bootstrap_roots() returns every present drive letter
        # (matching /scan/browse's own real behavior), which makes any real
        # local path "allowed" regardless of _configured_roots -- so this
        # boundary can only be tested by removing the bootstrap set itself,
        # not by simply not calling _allow_source.
        import app.routers.imports as imports_module
        monkeypatch.setattr(imports_module, "_bootstrap_roots", lambda: [])

        library = _library(db, tmp_path / "library")
        unallowed = tmp_path / "not_allowed" / "pack.zip"
        unallowed.parent.mkdir(parents=True)
        _make_zip(unallowed, {"Zarana/Head.stl": b"head"})

        r = client.post("/import/install", json={
            "source": str(unallowed), "library_id": library.id,
            "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 403

    def test_library_not_found_404(self, client, db, tmp_path, enabled):
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        r = client.post("/import/install", json={
            "source": str(source), "library_id": 999999, "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 404

    def test_library_not_writable_400(self, client, db, tmp_path, enabled):
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        library = _library(db, tmp_path / "library", writable=False)
        r = client.post("/import/install", json={
            "source": str(source), "library_id": library.id, "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 400

    def test_non_default_layout_library_400(self, client, db, tmp_path, enabled):
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        library = _library(db, tmp_path / "library", layout="{tag}/{creator}")
        r = client.post("/import/install", json={
            "source": str(source), "library_id": library.id, "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 400


class TestInstallerErrorMapping:
    def test_collision_returns_409(self, client, db, tmp_path, enabled):
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        zip_path = source / "pack.zip"
        _make_zip(zip_path, {"Zarana/Head.stl": b"head"})
        library = _library(db, tmp_path / "library")
        (tmp_path / "library" / "Abe3D" / "Zarana").mkdir(parents=True)

        r = client.post("/import/install", json={
            "source": str(zip_path), "library_id": library.id,
            "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 409

    def test_size_cap_exceeded_returns_413(self, client, db, tmp_path, enabled, monkeypatch):
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        zip_path = source / "pack.zip"
        _make_zip(zip_path, {"Zarana/Head.stl": b"x" * 100})
        library = _library(db, tmp_path / "library")
        monkeypatch.setattr(installer, "MAX_INSTALL_SIZE_BYTES", 10)

        r = client.post("/import/install", json={
            "source": str(zip_path), "library_id": library.id,
            "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 413

    def test_unsupported_source_extension_returns_400(self, client, db, tmp_path, enabled):
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        rar_path = source / "pack.rar"
        rar_path.write_bytes(b"not a zip")
        library = _library(db, tmp_path / "library")

        r = client.post("/import/install", json={
            "source": str(rar_path), "library_id": library.id,
            "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 400

    def test_write_lock_busy_returns_409(self, client, db, tmp_path, enabled, monkeypatch):
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        zip_path = source / "pack.zip"
        _make_zip(zip_path, {"Zarana/Head.stl": b"head"})
        library = _library(db, tmp_path / "library")

        def busy(*args, **kwargs):
            raise write_lock.LibraryBusy("Another scan, apply, or undo is in progress")
            yield  # pragma: no cover -- unreachable, keeps this a generator/contextmanager shape

        import contextlib
        monkeypatch.setattr(write_lock, "library_write", contextlib.contextmanager(busy))

        r = client.post("/import/install", json={
            "source": str(zip_path), "library_id": library.id,
            "creator": "Abe3D", "character": "Zarana",
        })
        assert r.status_code == 409

    def test_creator_character_path_traversal_returns_403(self, client, db, tmp_path, enabled):
        source = tmp_path / "downloads"
        source.mkdir()
        _allow_source(db, source)
        zip_path = source / "pack.zip"
        _make_zip(zip_path, {"Zarana/Head.stl": b"head"})
        library = _library(db, tmp_path / "library")

        r = client.post("/import/install", json={
            "source": str(zip_path), "library_id": library.id,
            "creator": "../../etc", "character": "passwd",
        })
        assert r.status_code == 403

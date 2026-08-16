"""STL Installer + post-install scan integration (STUDIO-388).

STUDIO-388's ticket proposed reusing scanner.start_inbox_scan for the
post-install scan. Two problems ruled that out during planning:

1. Pointed at scan_root/creator with single_pack=False, _inbox_scan treats
   every immediate subdirectory as its own creator -- so each *character*
   folder under the real creator would become a bogus creator named after
   itself.
2. Even scoped correctly to just the new character folder (single_pack=True),
   _inbox_scan unconditionally sets is_inbox=True, and nothing ever clears
   it back to False. The main Library listing hides is_inbox=True models by
   default, so installed content would silently vanish from the Library
   until the user separately found and applied it via Import Preview --
   defeating the point of an installer that places content directly.

The existing scanner.start_creator_scan/scan_creator (already shipped,
already used by a real "rescan this creator" UI action) is the correct fit
instead: it indexes non-inbox, and _creator_dirs_for/_creator_dirs_by_name
already handle both an existing creator (via already-indexed models' folder
paths) and a brand-new creator with zero prior models (disk-based name
fallback) -- exactly the two shapes the installer produces. No new scanning
logic is needed; these tests confirm the composition works end-to-end.
"""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.models import Model, ScanRoot
from app.services import installer, scanner


def _install(tmp_path, creator_name: str, character: str, filename: str = "head.stl") -> None:
    source = tmp_path / "incoming"
    source.mkdir(exist_ok=True)
    (source / filename).write_bytes(b"stl-bytes")
    library = tmp_path / "library"
    library.mkdir(exist_ok=True)
    installer.install(source, library, creator_name, character)
    (source / filename).unlink()  # next _install call reuses the same incoming dir


def test_creator_scan_indexes_freshly_installed_content_as_non_inbox(db, tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "SessionLocal", sessionmaker(bind=db.get_bind()))
    library = tmp_path / "library"
    library.mkdir()
    db.add(ScanRoot(path=str(library), layout="{creator}", enabled=True))
    db.commit()

    _install(tmp_path, "Abe3D", "Zarana")

    creator = scanner.resolve_creator("Abe3D", db)
    db.commit()

    scanner.scan_creator(creator.id)

    model = db.query(Model).filter(Model.creator_id == creator.id).one()
    assert model.is_inbox is False
    assert model.character == "Zarana"


def test_creator_scan_bootstraps_a_creator_with_zero_prior_models(db, tmp_path, monkeypatch):
    """The installer can create a brand-new Creator row with no indexed models
    yet (STUDIO-387's inline add-new-creator path). _creator_dirs_for has
    nothing to key off in that case -- confirms the _creator_dirs_by_name
    disk-based fallback still finds and indexes the just-installed content."""
    monkeypatch.setattr(scanner, "SessionLocal", sessionmaker(bind=db.get_bind()))
    library = tmp_path / "library"
    library.mkdir()
    db.add(ScanRoot(path=str(library), layout="{creator}", enabled=True))
    db.commit()

    creator = scanner.resolve_creator("3DMOONN", db)
    db.commit()
    assert db.query(Model).filter(Model.creator_id == creator.id).count() == 0

    _install(tmp_path, "3DMOONN", "Percy")

    scanner.scan_creator(creator.id)

    model = db.query(Model).filter(Model.creator_id == creator.id).one()
    assert model.is_inbox is False
    assert model.character == "Percy"


def test_creator_scan_after_install_does_not_duplicate_existing_characters(db, tmp_path, monkeypatch):
    """A creator scan triggered by installing a second character doesn't
    touch or duplicate a character that was already indexed."""
    monkeypatch.setattr(scanner, "SessionLocal", sessionmaker(bind=db.get_bind()))
    library = tmp_path / "library"
    library.mkdir()
    db.add(ScanRoot(path=str(library), layout="{creator}", enabled=True))
    db.commit()

    _install(tmp_path, "Abe3D", "Zarana")
    creator = scanner.resolve_creator("Abe3D", db)
    db.commit()
    scanner.scan_creator(creator.id)
    assert db.query(Model).filter(Model.creator_id == creator.id).count() == 1

    _install(tmp_path, "Abe3D", "Cobra Commander")
    scanner.scan_creator(creator.id)

    models = db.query(Model).filter(Model.creator_id == creator.id).all()
    assert {m.character for m in models} == {"Zarana", "Cobra Commander"}
    assert all(m.is_inbox is False for m in models)

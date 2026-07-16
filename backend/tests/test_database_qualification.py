"""Production-like backup, restore, and reset qualification (STUDIO-203)."""

import io
import sqlite3

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.main import app
from app.models import (
    AppSetting,
    Collection,
    CollectionModel,
    Creator,
    Model,
    ReorganizeManifest,
    VariantGroup,
)
from app.painting.models import Guide, GuidePhase, GuideStep, GuideTab
from app.services import secrets


QUALIFIED_TABLES = (
    "app_settings",
    "collections",
    "collection_models",
    "variant_groups",
    "models",
    "guides",
    "guide_tabs",
    "guide_phases",
    "guide_steps",
    "reorganize_manifests",
)


def _counts(path) -> dict[str, int]:
    with sqlite3.connect(path) as conn:
        return {
            table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in QUALIFIED_TABLES
        }


def _relationships(path) -> tuple:
    with sqlite3.connect(path) as conn:
        return (
            conn.execute(
                "SELECT c.name, m.name FROM collections c "
                "JOIN collection_models cm ON cm.collection_id = c.id "
                "JOIN models m ON m.id = cm.model_id"
            ).fetchall(),
            conn.execute(
                "SELECT vg.label, m.name, rep.name FROM variant_groups vg "
                "JOIN models m ON m.variant_group_id = vg.id "
                "JOIN models rep ON rep.id = vg.rep_model_id ORDER BY m.name"
            ).fetchall(),
            conn.execute(
                "SELECT g.slug, m.name, gt.name, gp.label, gs.title FROM guides g "
                "JOIN models m ON m.id = g.model_id "
                "JOIN guide_tabs gt ON gt.guide_id = g.id "
                "JOIN guide_phases gp ON gp.tab_id = gt.id "
                "JOIN guide_steps gs ON gs.phase_id = gp.id"
            ).fetchall(),
        )


@pytest.fixture()
def qualified_database(tmp_path, monkeypatch):
    db_path = tmp_path / "stl_studio.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setenv("STL_SECRET_KEY", Fernet.generate_key().decode())

    import app.database as db_module
    import app.main as main_module
    import app.routers.database as database_router

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(database_router, "engine", engine)
    secrets.reset_cache()

    with Session() as db:
        creator = Creator(name="Qualification Creator")
        db.add(creator)
        db.flush()
        representative = Model(
            name="Knight Supported",
            folder_path="/library/Qualification Creator/Knight Supported",
            creator_id=creator.id,
        )
        alternate = Model(
            name="Knight Unsupported",
            folder_path="/library/Qualification Creator/Knight Unsupported",
            creator_id=creator.id,
        )
        db.add_all((representative, alternate))
        db.flush()
        group = VariantGroup(
            creator_id=creator.id, label="Knight", rep_model_id=representative.id, source="manual"
        )
        db.add(group)
        db.flush()
        representative.variant_group_id = group.id
        alternate.variant_group_id = group.id

        collection = Collection(name="Release Qualification")
        db.add(collection)
        db.flush()
        db.add(CollectionModel(collection_id=collection.id, model_id=representative.id))
        db.add(AppSetting(key="models_per_page", value=48))
        db.add(
            ReorganizeManifest(
                id="qualification-manifest",
                template="{creator}/{model}",
                payload={"entries": [{"model_id": representative.id}]},
            )
        )

        guide = Guide(
            slug="qualification-knight",
            title="Qualification Knight",
            model_id=representative.id,
            status="published",
        )
        db.add(guide)
        db.flush()
        tab = GuideTab(guide_id=guide.id, name="Armor")
        db.add(tab)
        db.flush()
        phase = GuidePhase(tab_id=tab.id, label="Basecoat")
        db.add(phase)
        db.flush()
        db.add(GuideStep(phase_id=phase.id, title="Establish midtone"))
        db.commit()
        secrets.set_ai_api_key(db, "qualification-secret-not-for-production")

    expected = (_counts(db_path), _relationships(db_path))
    with TestClient(app, base_url="http://localhost") as client:
        yield client, db_path, Session, expected

    secrets.reset_cache()
    engine.dispose()


def test_production_like_backup_restore_preserves_counts_relationships_and_secret(
    qualified_database, tmp_path
):
    client, db_path, Session, expected = qualified_database
    response = client.get("/database/backup")
    assert response.status_code == 200
    backup = tmp_path / "qualification-backup.db"
    backup.write_bytes(response.content)

    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM collection_models")
        conn.execute("DELETE FROM guide_steps")
        conn.execute("DELETE FROM app_settings")
        conn.commit()

    response = client.post(
        "/database/restore",
        files={"file": (backup.name, io.BytesIO(backup.read_bytes()), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    assert (_counts(db_path), _relationships(db_path)) == expected

    secrets.reset_cache()
    with Session() as db:
        assert secrets.get_ai_api_key(db) == "qualification-secret-not-for-production"


def test_production_like_reset_recreates_schema_and_keeps_recovery_snapshot(qualified_database):
    client, db_path, _, expected = qualified_database
    response = client.post("/database/reset")
    assert response.status_code == 200, response.text

    snapshot = response.json()["snapshot"]
    assert snapshot
    assert _counts(db_path) == {table: 0 for table in QUALIFIED_TABLES}
    assert (_counts(snapshot), _relationships(snapshot)) == expected

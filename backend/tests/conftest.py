"""
Shared fixtures for all tests.

Sets DATABASE_URL *before* any app module is imported so Settings() and
create_engine() both pick up the test value.
"""
import os

# Must happen before any app import
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from app.utils import utcnow
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.models import Creator, Model, STLFile, VariantGroup


# ---------------------------------------------------------------------------
# DB + client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db(test_engine, monkeypatch):
    Session = sessionmaker(bind=test_engine)

    # Patch every module that holds a direct reference to engine / SessionLocal,
    # so startup events (_migrate_schema, _seed_tag_index) use the test DB.
    import app.database as db_module
    import app.main as main_module

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session)
    monkeypatch.setattr(main_module, "engine", test_engine)

    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    # base_url must look local: the CSRF middleware (#213) rejects writes
    # whose Host header isn't localhost (TestClient defaults to "testserver").
    with TestClient(app, base_url="http://localhost") as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def make_creator(db, name="Test Creator") -> Creator:
    c = Creator(name=name)
    db.add(c)
    db.flush()
    return c


def make_model(
    db,
    creator: Creator,
    name: str = "Test Model",
    character: str | None = None,
    thumbnail_path: str | None = None,
    needs_review: bool = False,
    tags: list | None = None,
) -> Model:
    m = Model(
        name=name,
        folder_path=f"/tmp/models/{creator.name}/{name}",
        creator_id=creator.id,
        character=character,
        thumbnail_path=thumbnail_path,
        needs_review=needs_review,
        tags=tags or [],
        auto_tags=[],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(m)
    db.flush()
    return m


def make_variant_group(
    db,
    creator: Creator,
    members: list[Model],
    label: str = "Group",
    source: str = "auto",
    rep: Model | None = None,
    heuristic_rep: bool = False,
) -> VariantGroup:
    """Durably group `members` (#678 Phase 3+: variant_group_id is the sole
    grouping key — a plain `character` value never collapses at the read path
    on its own). Mirrors what a scan's `grouping.regroup_creator` pass, or a
    manual merge, leaves behind.

    Defaults to `members[0]` as the designated rep; pass `heuristic_rep=True`
    to leave `rep_model_id` unset so `_rep_order`'s thumbnail/favorite/queued
    heuristic decides instead (for tests of that heuristic itself)."""
    g = VariantGroup(creator_id=creator.id, label=label, source=source)
    db.add(g)
    db.flush()
    for m in members:
        m.variant_group_id = g.id
    if not heuristic_rep:
        g.rep_model_id = (rep or members[0]).id
    db.flush()
    return g


def make_stl_file(
    db,
    model: Model,
    filename: str = "test.stl",
    part_type: str | None = None,
    path: str | None = None,
) -> STLFile:
    f = STLFile(
        model_id=model.id,
        path=path or f"/tmp/{filename}",
        filename=filename,
        size_bytes=1024,
        part_type=part_type,
    )
    db.add(f)
    db.flush()
    return f

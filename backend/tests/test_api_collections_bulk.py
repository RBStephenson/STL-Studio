"""Bulk collection-add endpoint (STUDIO-373): adding a variant group's models
to a collection in one request, expanding any grouped id to its full
non-excluded sibling set."""
from app.models import Collection, CollectionModel, VariantGroup

from .conftest import make_creator, make_model


def _make_group(db, creator, count=3, excluded_at=None):
    """Create `count` models sharing one variant group. `excluded_at` (a set of
    0-based indices) marks those models excluded."""
    grp = VariantGroup(creator_id=creator.id, label="Group")
    db.add(grp)
    db.flush()
    models = []
    for i in range(count):
        m = make_model(db, creator, name=f"variant-{i}")
        m.variant_group_id = grp.id
        if excluded_at and i in excluded_at:
            m.excluded = True
        models.append(m)
    db.flush()
    return grp, models


def test_bulk_add_expands_selected_group_member_to_whole_group(client, db):
    creator = make_creator(db)
    _, members = _make_group(db, creator, count=3)
    col = Collection(name="Painted")
    db.add(col)
    db.flush()

    # Only the rep's id is submitted, matching a Library group-card selection.
    r = client.post(f"/collections/{col.id}/models/bulk", json={"model_ids": [members[0].id]})

    assert r.status_code == 200
    assert r.json() == {"added": 3, "total": 3}
    linked = {row.model_id for row in db.query(CollectionModel).filter(CollectionModel.collection_id == col.id)}
    assert linked == {m.id for m in members}


def test_bulk_add_excludes_hidden_siblings(client, db):
    creator = make_creator(db)
    _, members = _make_group(db, creator, count=3, excluded_at={2})
    col = Collection(name="Painted")
    db.add(col)
    db.flush()

    r = client.post(f"/collections/{col.id}/models/bulk", json={"model_ids": [members[0].id]})

    assert r.status_code == 200
    assert r.json() == {"added": 2, "total": 2}
    linked = {row.model_id for row in db.query(CollectionModel).filter(CollectionModel.collection_id == col.id)}
    assert linked == {members[0].id, members[1].id}
    assert members[2].id not in linked


def test_bulk_add_skips_already_linked_models(client, db):
    creator = make_creator(db)
    _, members = _make_group(db, creator, count=2)
    col = Collection(name="Painted")
    db.add(col)
    db.flush()
    db.add(CollectionModel(collection_id=col.id, model_id=members[0].id))
    db.flush()

    r = client.post(f"/collections/{col.id}/models/bulk", json={"model_ids": [members[0].id]})

    assert r.status_code == 200
    # Total counts the whole expanded group; added excludes the pre-existing link.
    assert r.json() == {"added": 1, "total": 2}
    linked = {row.model_id for row in db.query(CollectionModel).filter(CollectionModel.collection_id == col.id)}
    assert linked == {m.id for m in members}


def test_bulk_add_ungrouped_models_adds_only_those_ids(client, db):
    creator = make_creator(db)
    m1 = make_model(db, creator, name="solo-1")
    m2 = make_model(db, creator, name="solo-2")
    col = Collection(name="Painted")
    db.add(col)
    db.flush()

    r = client.post(f"/collections/{col.id}/models/bulk", json={"model_ids": [m1.id, m2.id]})

    assert r.status_code == 200
    assert r.json() == {"added": 2, "total": 2}


def test_bulk_add_empty_ids_returns_400(client, db):
    col = Collection(name="Painted")
    db.add(col)
    db.flush()

    r = client.post(f"/collections/{col.id}/models/bulk", json={"model_ids": []})

    assert r.status_code == 400


def test_bulk_add_unknown_collection_returns_404(client, db):
    creator = make_creator(db)
    m1 = make_model(db, creator)
    db.flush()

    r = client.post("/collections/999999/models/bulk", json={"model_ids": [m1.id]})

    assert r.status_code == 404


def test_bulk_add_unknown_model_ids_returns_404(client, db):
    col = Collection(name="Painted")
    db.add(col)
    db.flush()

    r = client.post(f"/collections/{col.id}/models/bulk", json={"model_ids": [999999]})

    assert r.status_code == 404

"""
Collection API tests — focused on the delete cascade (issue #214).

PRAGMA foreign_keys is off, so deleting a Collection must manually delete
its CollectionModel link rows; otherwise SQLite rowid reuse hands the dead
membership to the next collection created.
"""
from app.models import Collection, CollectionModel

from .conftest import make_creator, make_model


def _make_collection_with_member(db, client, name="Painted"):
    creator = make_creator(db, name=f"creator for {name}")
    model = make_model(db, creator, name=f"model for {name}")
    col = Collection(name=name)
    db.add(col)
    db.flush()
    db.add(CollectionModel(collection_id=col.id, model_id=model.id))
    db.flush()
    return col, model


def test_delete_collection_removes_link_rows(client, db):
    col, _ = _make_collection_with_member(db, client)
    col_id = col.id

    assert client.delete(f"/collections/{col_id}").status_code == 204

    remaining = db.query(CollectionModel).filter(
        CollectionModel.collection_id == col_id
    ).count()
    assert remaining == 0


def test_new_collection_does_not_inherit_deleted_members(client, db):
    """The rowid-reuse case: recreate after delete, must start empty."""
    col, _ = _make_collection_with_member(db, client)
    assert client.delete(f"/collections/{col.id}").status_code == 204

    r = client.post("/collections", json={"name": "Fresh"})
    assert r.status_code == 201
    new_id = r.json()["id"]
    # SQLite reuses the freed max rowid, which is what made #214 visible.
    assert new_id == col.id

    r = client.get(f"/collections/{new_id}/models")
    assert r.status_code == 200
    assert r.json() == []


def test_delete_collection_leaves_other_collections_alone(client, db):
    col_a, model_a = _make_collection_with_member(db, client, name="A")
    col_b, model_b = _make_collection_with_member(db, client, name="B")

    assert client.delete(f"/collections/{col_a.id}").status_code == 204

    r = client.get(f"/collections/{col_b.id}/models")
    assert [m["id"] for m in r.json()] == [model_b.id]

"""STUDIO-304: propagate_source_url must key on variant_group_id, not the
legacy character field — two distinct durable groups can share a character."""
from app.services.variant_sync import propagate_source_url
from tests.conftest import make_creator, make_model, make_variant_group


def test_propagates_to_grouped_sibling_missing_url(db):
    creator = make_creator(db)
    a = make_model(db, creator, name="a", character="Ada Wong")
    b = make_model(db, creator, name="b", character="Ada Wong")
    make_variant_group(db, creator, [a, b])
    db.commit()

    a.source_url = "https://cults3d.com/en/3d-model/game/ada"
    a.source_site = "cults3d"
    updated = propagate_source_url(db, a)
    db.commit()

    assert updated == 1
    db.refresh(b)
    assert b.source_url == a.source_url
    assert b.source_site == "cults3d"


def test_does_not_propagate_across_distinct_groups_sharing_character(db):
    """A bust split from a 75mm figure can share `character` while being
    deliberately separate durable groups — character alone must never be
    used to reach across that boundary."""
    creator = make_creator(db)
    a = make_model(db, creator, name="a", character="Ada Wong")
    b = make_model(db, creator, name="b", character="Ada Wong")
    make_variant_group(db, creator, [a])
    make_variant_group(db, creator, [b], label="Bust")
    db.commit()

    a.source_url = "https://cults3d.com/en/3d-model/game/ada"
    updated = propagate_source_url(db, a)
    db.commit()

    assert updated == 0
    db.refresh(b)
    assert b.source_url is None


def test_ungrouped_model_propagates_to_no_one(db):
    creator = make_creator(db)
    a = make_model(db, creator, name="a", character="Ada Wong")
    b = make_model(db, creator, name="b", character="Ada Wong")
    db.commit()

    a.source_url = "https://cults3d.com/en/3d-model/game/ada"
    updated = propagate_source_url(db, a)
    db.commit()

    assert updated == 0
    db.refresh(b)
    assert b.source_url is None


def test_does_not_overwrite_sibling_with_existing_url(db):
    creator = make_creator(db)
    a = make_model(db, creator, name="a")
    b = make_model(db, creator, name="b")
    make_variant_group(db, creator, [a, b])
    b.source_url = "https://gumroad.com/l/existing"
    db.commit()

    a.source_url = "https://cults3d.com/en/3d-model/game/ada"
    updated = propagate_source_url(db, a)
    db.commit()

    assert updated == 0
    db.refresh(b)
    assert b.source_url == "https://gumroad.com/l/existing"

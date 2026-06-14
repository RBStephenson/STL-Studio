"""Unit tests for the model_tags index rebuild (services/tag_sync).

Locks in rebuild_all_tags behaviour (previously only sync_model_tags was
exercised, via the tag-management API) after the #56 dedup that routes both
through the shared _write_model_tags helper.
"""
from tests.conftest import make_creator, make_model
from app.models import ModelTag
from app.services.tag_sync import rebuild_all_tags


def test_rebuild_all_tags_merges_user_and_auto_tags(db):
    creator = make_creator(db)
    m1 = make_model(db, creator, name="Alpha", tags=["bust"])
    m1.auto_tags = ["figure", "bust"]          # "bust" also a user tag → user wins (is_auto False)
    m2 = make_model(db, creator, name="Beta", tags=["statue"])
    m2.auto_tags = ["figure"]
    m2.removed_auto_tags = ["figure"]          # suppressed → dropped from the index
    db.commit()

    # A stale row that a full rebuild must clear.
    db.add(ModelTag(model_id=m1.id, tag="ghost", is_auto=True))
    db.commit()

    count = rebuild_all_tags(db)

    rows = {(r.model_id, r.tag): r.is_auto for r in db.query(ModelTag).all()}
    assert rows == {
        (m1.id, "bust"): False,    # user tag wins over the same-named auto tag
        (m1.id, "figure"): True,
        (m2.id, "statue"): False,  # m2's "figure" auto tag was suppressed
    }
    assert count == len(rows)

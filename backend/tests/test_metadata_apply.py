"""Unit tests for the shared metadata writer (apply_scraped_to_model).

Focuses on the two policy flags that differ between the single-model
(Find-on-Web) and bulk (creator-enrich) call sites.
"""
import asyncio

from app.services.metadata_apply import apply_scraped_to_model
from app.services.scrapers.base import ScrapedModel
from tests.conftest import make_creator, make_model


def _run(coro):
    return asyncio.run(coro)


def _scraped(**overrides) -> ScrapedModel:
    fields = dict(
        title="Fetched Title",
        description="desc",
        source_url="https://example.com/object/1",
        source_site="myminifactory",
        tags=["b", "c"],
        category="Cat",
        license="CC",
        thumbnail_url=None,
    )
    fields.update(overrides)
    return ScrapedModel(**fields)


def test_writes_core_fields_and_merges_tags(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="m")
    model.tags = ["a", "b"]
    db.commit()

    _run(apply_scraped_to_model(db, model, _scraped()))
    db.commit()
    db.refresh(model)

    assert model.description == "desc"
    assert model.category == "Cat"
    assert model.license == "CC"
    # Tags merged + deduped (existing "a","b" ∪ fetched "b","c").
    assert set(model.tags) == {"a", "b", "c"}
    assert model.needs_review is False


def test_overwrite_title_true_replaces(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="m")
    model.title = "Old Title"
    db.commit()

    _run(apply_scraped_to_model(db, model, _scraped(), overwrite_title=True))
    db.commit(); db.refresh(model)
    assert model.title == "Fetched Title"


def test_overwrite_title_false_keeps_existing(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="m")
    model.title = "Old Title"
    db.commit()

    _run(apply_scraped_to_model(db, model, _scraped(), overwrite_title=False))
    db.commit(); db.refresh(model)
    assert model.title == "Old Title"  # filled only when empty


def test_overwrite_title_false_fills_empty(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="m")
    model.title = None
    db.commit()

    _run(apply_scraped_to_model(db, model, _scraped(), overwrite_title=False))
    db.commit(); db.refresh(model)
    assert model.title == "Fetched Title"


def test_thumbnail_fill_only_skips_when_present(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="m", thumbnail_path="/local/x.png")
    db.commit()

    # thumbnail_url set, but fill-only + existing path => left untouched, no download.
    _run(apply_scraped_to_model(
        db, model, _scraped(thumbnail_url="https://cdn/x.png"), thumbnail_fill_only=True
    ))
    db.commit(); db.refresh(model)
    assert model.thumbnail_path == "/local/x.png"
    assert model.thumbnail_url is None


def test_reassign_creator_false_keeps_existing_creator(db):
    creator = make_creator(db, name="abe3d")
    other = make_creator(db, name="Abe 3D Prints")
    model = make_model(db, creator, name="m")
    db.commit()

    _run(apply_scraped_to_model(
        db, model, _scraped(creator_name="Abe 3D Prints"), reassign_creator=False
    ))
    db.commit(); db.refresh(model)
    assert model.creator_id == creator.id
    assert model.creator_id != other.id


def test_reassign_creator_true_moves_creator(db):
    creator = make_creator(db, name="abe3d")
    model = make_model(db, creator, name="m")
    db.commit()

    _run(apply_scraped_to_model(
        db, model, _scraped(creator_name="Abe 3D Prints"), reassign_creator=True
    ))
    db.commit(); db.refresh(model)
    assert model.creator_id != creator.id


def test_reassign_creator_false_still_fills_null_creator(db):
    creator = make_creator(db, name="abe3d")
    model = make_model(db, creator, name="m")
    model.creator_id = None
    db.commit()

    _run(apply_scraped_to_model(
        db, model, _scraped(creator_name="Abe 3D Prints"), reassign_creator=False
    ))
    db.commit(); db.refresh(model)
    assert model.creator_id is not None


def test_clear_needs_review_false_leaves_flag_set(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="m", needs_review=True)
    db.commit()

    _run(apply_scraped_to_model(db, model, _scraped(), clear_needs_review=False))
    db.commit(); db.refresh(model)
    assert model.needs_review is True


def test_clear_needs_review_true_clears_flag(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="m", needs_review=True)
    db.commit()

    _run(apply_scraped_to_model(db, model, _scraped(), clear_needs_review=True))
    db.commit(); db.refresh(model)
    assert model.needs_review is False


def test_like_count_written_rating_untouched(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="m")
    model.rating = 4.2
    db.commit()

    _run(apply_scraped_to_model(db, model, _scraped(like_count=123)))
    db.commit(); db.refresh(model)
    assert model.like_count == 123
    assert model.rating == 4.2

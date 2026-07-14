"""Unit tests for the shared metadata writer (apply_scraped_to_model).

Focuses on the two policy flags that differ between the single-model
(Find-on-Web) and bulk (creator-enrich) call sites.
"""
import asyncio

from app.services import metadata_apply
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


class TestGalleryImages:
    """#1028: apply_scraped_to_model downloads scraped.image_urls into
    model.image_paths — but only when the model has no images yet, for both
    the single-model and bulk call sites alike (no thumbnail_fill_only-style
    per-caller flag, since a gallery has no single "current" slot to compare
    against)."""

    def test_fills_gallery_when_empty(self, db, monkeypatch):
        calls = []

        async def fake_download(model_id, urls, **kwargs):
            calls.append((model_id, urls))
            return [f"/data/gallery_images/{model_id}_{i}.jpg" for i in range(len(urls))]

        monkeypatch.setattr(metadata_apply, "download_gallery_images", fake_download)

        creator = make_creator(db)
        model = make_model(db, creator, name="m")
        model.image_paths = []
        db.commit()

        urls = ["https://cdn/a.jpg", "https://cdn/b.jpg"]
        _run(apply_scraped_to_model(db, model, _scraped(image_urls=urls)))
        db.commit(); db.refresh(model)

        assert calls == [(model.id, urls)]
        assert model.image_paths == [
            f"/data/gallery_images/{model.id}_0.jpg",
            f"/data/gallery_images/{model.id}_1.jpg",
        ]

    def test_skips_download_when_gallery_already_has_images(self, db, monkeypatch):
        calls = []

        async def fake_download(model_id, urls, **kwargs):
            calls.append((model_id, urls))
            return ["/data/gallery_images/1_0.jpg"]

        monkeypatch.setattr(metadata_apply, "download_gallery_images", fake_download)

        creator = make_creator(db)
        model = make_model(db, creator, name="m")
        model.image_paths = ["/library/existing.jpg"]
        db.commit()

        _run(apply_scraped_to_model(db, model, _scraped(image_urls=["https://cdn/a.jpg"])))
        db.commit(); db.refresh(model)

        assert calls == []
        assert model.image_paths == ["/library/existing.jpg"]

    def test_no_image_urls_leaves_gallery_untouched(self, db, monkeypatch):
        calls = []

        async def fake_download(model_id, urls, **kwargs):
            calls.append((model_id, urls))
            return []

        monkeypatch.setattr(metadata_apply, "download_gallery_images", fake_download)

        creator = make_creator(db)
        model = make_model(db, creator, name="m")
        model.image_paths = []
        db.commit()

        _run(apply_scraped_to_model(db, model, _scraped(image_urls=[])))
        db.commit(); db.refresh(model)

        assert calls == []
        assert model.image_paths == []

    def test_all_downloads_failing_leaves_gallery_untouched(self, db, monkeypatch):
        async def fake_download(model_id, urls, **kwargs):
            return []  # every URL failed to download

        monkeypatch.setattr(metadata_apply, "download_gallery_images", fake_download)

        creator = make_creator(db)
        model = make_model(db, creator, name="m")
        model.image_paths = []
        db.commit()

        _run(apply_scraped_to_model(db, model, _scraped(image_urls=["https://cdn/dead.jpg"])))
        db.commit(); db.refresh(model)

        assert model.image_paths == []


def test_like_count_written_rating_untouched(db):
    creator = make_creator(db)
    model = make_model(db, creator, name="m")
    model.rating = 4.2
    db.commit()

    _run(apply_scraped_to_model(db, model, _scraped(like_count=123)))
    db.commit(); db.refresh(model)
    assert model.like_count == 123
    assert model.rating == 4.2

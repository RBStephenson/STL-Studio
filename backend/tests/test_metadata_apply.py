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
    model.image_paths unconditionally, every run, capped at 30 — matching
    Import's own gallery cap, no fill-only-when-empty gate. Only the subset
    of image_paths previously written by a fetch (paths under
    gallery_images_dir()) is replaced; anything else already in the gallery
    (e.g. scan-discovered images) is left alone."""

    @staticmethod
    def _mock_gallery_dir(monkeypatch, tmp_path):
        d = tmp_path / "gallery_images"
        d.mkdir()
        monkeypatch.setattr(metadata_apply.thumbnails, "gallery_images_dir", lambda: d)
        return d

    def test_downloads_and_sets_gallery_when_empty(self, db, monkeypatch, tmp_path):
        gallery_dir = self._mock_gallery_dir(monkeypatch, tmp_path)
        calls = []

        async def fake_download(model_id, urls, **kwargs):
            calls.append((model_id, urls))
            return [str(gallery_dir / f"{model_id}_{i}.jpg") for i in range(len(urls))]

        monkeypatch.setattr(metadata_apply.thumbnails, "download_gallery_images", fake_download)

        creator = make_creator(db)
        model = make_model(db, creator, name="m")
        model.image_paths = []
        db.commit()

        urls = ["https://cdn/a.jpg", "https://cdn/b.jpg"]
        _run(apply_scraped_to_model(db, model, _scraped(image_urls=urls)))
        db.commit(); db.refresh(model)

        assert calls == [(model.id, urls)]
        assert model.image_paths == [
            str(gallery_dir / f"{model.id}_0.jpg"),
            str(gallery_dir / f"{model.id}_1.jpg"),
        ]

    def test_downloads_even_when_gallery_already_has_non_fetched_images(self, db, monkeypatch, tmp_path):
        """A scan-discovered image already sitting in the gallery must not
        block a fetch from adding the scraped ones too (the exact bug
        reported: a model with one promo image bundled in its download
        never got the rest of the product page's gallery)."""
        gallery_dir = self._mock_gallery_dir(monkeypatch, tmp_path)
        calls = []

        async def fake_download(model_id, urls, **kwargs):
            calls.append((model_id, urls))
            return [str(gallery_dir / f"{model_id}_0.jpg")]

        monkeypatch.setattr(metadata_apply.thumbnails, "download_gallery_images", fake_download)

        creator = make_creator(db)
        model = make_model(db, creator, name="m")
        model.image_paths = ["/library/scanned-promo.jpg"]
        db.commit()

        _run(apply_scraped_to_model(db, model, _scraped(image_urls=["https://cdn/a.jpg"])))
        db.commit(); db.refresh(model)

        assert calls == [(model.id, ["https://cdn/a.jpg"])]
        assert model.image_paths == ["/library/scanned-promo.jpg", str(gallery_dir / f"{model.id}_0.jpg")]

    def test_refetch_replaces_previously_fetched_images_but_keeps_scanned_ones(self, db, monkeypatch, tmp_path):
        gallery_dir = self._mock_gallery_dir(monkeypatch, tmp_path)

        async def fake_download(model_id, urls, **kwargs):
            # Simulates a shrinking source gallery: only one image this time,
            # where a prior fetch had left two files behind.
            return [str(gallery_dir / f"{model_id}_0.jpg")]

        monkeypatch.setattr(metadata_apply.thumbnails, "download_gallery_images", fake_download)

        creator = make_creator(db)
        model = make_model(db, creator, name="m")
        db.commit()  # assigns model.id
        model.image_paths = [
            "/library/scanned.jpg",
            str(gallery_dir / f"{model.id}_0.jpg"),
            str(gallery_dir / f"{model.id}_1.jpg"),
        ]
        db.commit()

        _run(apply_scraped_to_model(db, model, _scraped(image_urls=["https://cdn/a.jpg"])))
        db.commit(); db.refresh(model)

        assert model.image_paths == ["/library/scanned.jpg", str(gallery_dir / f"{model.id}_0.jpg")]

    def test_no_image_urls_leaves_gallery_untouched(self, db, monkeypatch):
        calls = []

        async def fake_download(model_id, urls, **kwargs):
            calls.append((model_id, urls))
            return []

        monkeypatch.setattr(metadata_apply.thumbnails, "download_gallery_images", fake_download)

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

        monkeypatch.setattr(metadata_apply.thumbnails, "download_gallery_images", fake_download)

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

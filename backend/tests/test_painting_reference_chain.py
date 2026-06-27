"""Reference-image fallback chain — STL-folder rung 0 + provenance
(#494, spec §4.4 / §8.5).

Candidates are selected by index into a server-built, scan-root-validated list,
so no request value ever reaches the filesystem. The network rungs (URL / web
search / AI-gen) are deferred to #563.

The data dir is redirected to a tmp path so stored copies don't touch the real
volume; model folder images live under the test STL root (conftest sets
STL_ROOTS=/tmp) so the scan-root safety guard accepts them.
"""
import io

import pytest
from PIL import Image

from app.models import Model
from app.painting.models import Guide, GuideReferenceImage
from app.painting.services import images


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "data_dir", lambda: tmp_path)
    return tmp_path


def _png_bytes(size=(16, 16), color=(120, 80, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _write_image(path, size=(16, 16)):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes(size))
    return str(path)


def _model_with_images(db, tmp_path, *, thumb=True, extra=0):
    """Create a Model whose folder images live under the test STL root."""
    folder = tmp_path / "models" / "creator" / "fig"
    thumb_path = _write_image(folder / "thumb.png") if thumb else None
    extras = [_write_image(folder / f"img{i}.png") for i in range(extra)]
    model = Model(
        name="Fig",
        folder_path=str(folder),
        thumbnail_path=thumb_path,
        image_paths=extras,
    )
    db.add(model)
    db.commit()
    return model


def _guide(db, model=None, slug="presto") -> Guide:
    g = Guide(slug=slug, title="Presto", model_id=model.id if model else None)
    db.add(g)
    db.commit()
    return g


# ---------------------------------------------------------------------------
# Rung 0 — STL model folder candidates
# ---------------------------------------------------------------------------

class TestModelCandidates:
    def test_lists_thumbnail_first_then_image_paths(self, db, tmp_path):
        model = _model_with_images(db, tmp_path, thumb=True, extra=2)
        guide = _guide(db, model)

        candidates = images.list_model_candidates(db, guide)

        assert candidates[0] == model.thumbnail_path
        assert set(candidates) == {model.thumbnail_path, *model.image_paths}

    def test_empty_without_linked_model(self, db, tmp_path):
        guide = _guide(db, model=None)
        assert images.list_model_candidates(db, guide) == []

    def test_dedupes_and_drops_missing_files(self, db, tmp_path):
        model = _model_with_images(db, tmp_path, thumb=True, extra=1)
        # thumbnail repeated in image_paths + a path that doesn't exist on disk.
        model.image_paths = [model.thumbnail_path, str(tmp_path / "gone.png")]
        db.commit()
        guide = _guide(db, model)

        candidates = images.list_model_candidates(db, guide)
        assert candidates == [model.thumbnail_path]

    def test_drops_paths_outside_scan_root(self, db, tmp_path, monkeypatch):
        model = _model_with_images(db, tmp_path, thumb=True)
        # An absolute path outside STL_ROOTS must be refused even if it exists.
        outside = _write_image(tmp_path.parent / "outside.png")
        monkeypatch.setattr("app.routers.files._allowed_roots",
                            lambda: [tmp_path / "models"])
        model.thumbnail_path = outside
        model.image_paths = []
        db.commit()
        guide = _guide(db, model)

        assert images.list_model_candidates(db, guide) == []


class TestStoreFromModel:
    def test_copies_bytes_with_provenance(self, db, tmp_path):
        model = _model_with_images(db, tmp_path, thumb=True)
        guide = _guide(db, model)

        row = images.store_from_model(db, guide, 0, alt_text="box art")
        db.commit()

        assert row.provenance == "stl_model_folder"
        assert row.source_url is None
        assert row.alt_text == "box art"
        assert guide.reference_image_id == row.id
        assert (tmp_path / row.storage_key).exists()

    def test_rejects_out_of_range_index(self, db, tmp_path):
        model = _model_with_images(db, tmp_path, thumb=True)  # one candidate
        guide = _guide(db, model)

        with pytest.raises(images.ReferenceImageError):
            images.store_from_model(db, guide, 5)

    def test_rejects_when_no_candidates(self, db, tmp_path):
        guide = _guide(db, model=None)
        with pytest.raises(images.ReferenceImageError):
            images.store_from_model(db, guide, 0)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class TestEndpoints:
    def test_candidates_endpoint(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr(images, "data_dir", lambda: tmp_path)
        model = _model_with_images(db, tmp_path, thumb=True, extra=1)
        guide = _guide(db, model)

        resp = client.get(f"/painting/guides/{guide.id}/reference-image/candidates")
        assert resp.status_code == 200
        assert resp.json()["candidates"][0] == model.thumbnail_path

    def test_from_model_endpoint(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr(images, "data_dir", lambda: tmp_path)
        model = _model_with_images(db, tmp_path, thumb=True)
        guide = _guide(db, model)

        resp = client.post(
            f"/painting/guides/{guide.id}/reference-image/from-model",
            json={"index": 0},
        )
        assert resp.status_code == 201
        assert resp.json()["provenance"] == "stl_model_folder"

    def test_from_model_endpoint_rejects_bad_index(self, client, db, tmp_path, monkeypatch):
        monkeypatch.setattr(images, "data_dir", lambda: tmp_path)
        model = _model_with_images(db, tmp_path, thumb=True)
        guide = _guide(db, model)

        resp = client.post(
            f"/painting/guides/{guide.id}/reference-image/from-model",
            json={"index": 99},
        )
        assert resp.status_code == 422

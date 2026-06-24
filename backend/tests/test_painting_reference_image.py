"""Reference-image upload + storage + serving (#535, spec §8.5).

The data dir is redirected to a tmp path so uploads don't touch the real volume.
"""
import io

import pytest
from PIL import Image

from app.painting.models import Guide, GuideReferenceImage
from app.painting.services import images


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    """Point the image store at a throwaway dir (in-memory DB -> cwd otherwise)."""
    monkeypatch.setattr(images, "data_dir", lambda: tmp_path)
    return tmp_path


def _png_bytes(size=(16, 16), color=(120, 80, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _guide(db, slug="presto") -> Guide:
    g = Guide(slug=slug, title="Presto")
    db.add(g)
    db.commit()
    return g


# ---------------------------------------------------------------------------
# Service: store / clear / load
# ---------------------------------------------------------------------------

def test_store_upload_creates_row_file_and_fk(db, _tmp_data_dir):
    guide = _guide(db)
    row = images.store_upload(db, guide, _png_bytes((24, 18)), alt_text="hero shot")
    db.commit()

    assert row.provenance == "user_upload"
    assert (row.width, row.height) == (24, 18)
    assert row.alt_text == "hero shot"
    assert guide.reference_image_id == row.id
    assert (_tmp_data_dir / row.storage_key).exists()


def test_store_upload_replaces_prior(db, _tmp_data_dir):
    guide = _guide(db)
    first = images.store_upload(db, guide, _png_bytes())
    db.commit()
    first_path = _tmp_data_dir / first.storage_key

    second = images.store_upload(db, guide, _png_bytes((32, 32)))
    db.commit()

    assert guide.reference_image_id == second.id
    assert db.get(GuideReferenceImage, first.id) is None
    assert not first_path.exists()                       # old file removed
    assert db.query(GuideReferenceImage).count() == 1


def test_store_upload_rejects_oversize(db, monkeypatch):
    monkeypatch.setattr(images, "_MAX_BYTES", 100)
    guide = _guide(db)
    with pytest.raises(images.ReferenceImageError):
        images.store_upload(db, guide, _png_bytes((64, 64)))


def test_store_upload_rejects_non_image(db):
    guide = _guide(db)
    with pytest.raises(images.ReferenceImageError):
        images.store_upload(db, guide, b"not an image")


def test_clear_reference_removes_row_file_and_fk(db, _tmp_data_dir):
    guide = _guide(db)
    row = images.store_upload(db, guide, _png_bytes())
    db.commit()
    path = _tmp_data_dir / row.storage_key

    images.clear_reference(db, guide)
    db.commit()

    assert guide.reference_image_id is None
    assert db.get(GuideReferenceImage, row.id) is None
    assert not path.exists()


def test_clear_reference_noop_without_image(db):
    guide = _guide(db)
    images.clear_reference(db, guide)  # must not raise
    assert guide.reference_image_id is None


def test_load_reference_returns_bytes_and_type(db):
    guide = _guide(db)
    raw = _png_bytes()
    images.store_upload(db, guide, raw)
    db.commit()

    loaded = images.load_reference(db, guide)
    assert loaded is not None
    data, media_type = loaded
    assert data == raw
    assert media_type == "image/png"


def test_load_reference_none_when_unset(db):
    guide = _guide(db)
    assert images.load_reference(db, guide) is None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def test_upload_endpoint_round_trip(client, db, _tmp_data_dir):
    guide = _guide(db)
    resp = client.post(
        f"/painting/guides/{guide.id}/reference-image",
        files={"file": ("ref.png", _png_bytes((40, 30)), "image/png")},
        data={"alt_text": "front"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["provenance"] == "user_upload"
    assert (body["width"], body["height"]) == (40, 30)

    got = client.get(f"/painting/guides/{guide.id}/reference-image")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"


def test_upload_endpoint_rejects_bad_file(client, db):
    guide = _guide(db)
    resp = client.post(
        f"/painting/guides/{guide.id}/reference-image",
        files={"file": ("ref.txt", b"nope", "text/plain")},
    )
    assert resp.status_code == 422


def test_get_endpoint_404_without_image(client, db):
    guide = _guide(db)
    assert client.get(f"/painting/guides/{guide.id}/reference-image").status_code == 404


def test_delete_endpoint_clears(client, db, _tmp_data_dir):
    guide = _guide(db)
    client.post(
        f"/painting/guides/{guide.id}/reference-image",
        files={"file": ("ref.png", _png_bytes(), "image/png")},
    )
    assert client.delete(f"/painting/guides/{guide.id}/reference-image").status_code == 200
    db.expire_all()
    assert db.get(Guide, guide.id).reference_image_id is None

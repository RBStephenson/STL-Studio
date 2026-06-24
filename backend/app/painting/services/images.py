"""Reference-image acquisition: upload, AI generation, assisted web search,
and STL-model-folder sourcing, with provenance tracking (spec §8.5).

#535 implements the first rung: user upload — store the bytes on the local data
volume, record a GuideReferenceImage row, and wire the guide FK. The heavyweight
fallback chain (STL-folder / web search / AI-gen) stays stubbed for #494.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.painting.models import Guide, GuideReferenceImage
from app.services.write_lock import data_dir

# Subdirectory under the local data dir (next to the SQLite DB) where uploaded
# reference images live. Deliberately not under a scan root — see data_dir().
_STORAGE_SUBDIR = "guide_reference_images"

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB upload cap (also bounds vision token cost).

# Accepted upload content — Pillow format name -> (extension, Anthropic media type).
# These are the formats Claude vision accepts; we re-derive the type from the
# decoded image rather than trusting the client's Content-Type.
_FORMAT_MAP = {
    "PNG": (".png", "image/png"),
    "JPEG": (".jpg", "image/jpeg"),
    "WEBP": (".webp", "image/webp"),
    "GIF": (".gif", "image/gif"),
}


class ReferenceImageError(ValueError):
    """The supplied upload was missing, too large, or not a supported image."""


def _storage_root() -> Path:
    root = data_dir() / _STORAGE_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path_for(storage_key: str) -> Path:
    """Resolve a stored row's storage_key to an absolute path on disk."""
    return data_dir() / storage_key


def _decode(raw: bytes) -> tuple[Image.Image, str, str]:
    """Validate bytes as a supported image; return (image, extension, media_type)."""
    if not raw:
        raise ReferenceImageError("The uploaded file is empty.")
    if len(raw) > _MAX_BYTES:
        raise ReferenceImageError(
            f"Image is too large ({len(raw) // 1024} KB); the limit is "
            f"{_MAX_BYTES // (1024 * 1024)} MB."
        )
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ReferenceImageError("The uploaded file is not a readable image.") from exc

    mapping = _FORMAT_MAP.get(image.format or "")
    if mapping is None:
        raise ReferenceImageError(
            f"Unsupported image format '{image.format}'. Use PNG, JPEG, WebP, or GIF."
        )
    extension, media_type = mapping
    return image, extension, media_type


def clear_reference(db: Session, guide: Guide) -> None:
    """Drop the guide's current reference image (FK + row + file), if any.

    Nulls the guide FK before deleting the row so the FK constraint never trips.
    No-op when the guide has no reference image.
    """
    image_id = guide.reference_image_id
    if image_id is None:
        return
    guide.reference_image_id = None
    db.flush()  # clear the FK before the row goes away

    row = db.get(GuideReferenceImage, image_id)
    if row is not None:
        path = _path_for(row.storage_key)
        db.delete(row)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # row is the source of truth; an orphaned file is harmless


def store_upload(
    db: Session,
    guide: Guide,
    raw: bytes,
    *,
    alt_text: str | None = None,
) -> GuideReferenceImage:
    """Store an uploaded reference image for a guide and wire the guide FK.

    Replaces any existing reference image. Raises ReferenceImageError when the
    bytes are missing, oversize, or not a supported image. Caller commits.
    """
    image, extension, _ = _decode(raw)
    width, height = image.size

    clear_reference(db, guide)

    filename = f"{guide.id}_{uuid.uuid4().hex}{extension}"
    storage_key = f"{_STORAGE_SUBDIR}/{filename}"
    (_storage_root() / filename).write_bytes(raw)

    row = GuideReferenceImage(
        guide_id=guide.id,
        storage_key=storage_key,
        provenance="user_upload",
        alt_text=alt_text,
        width=width,
        height=height,
    )
    db.add(row)
    db.flush()  # assign row.id
    guide.reference_image_id = row.id
    return row


def load_reference(db: Session, guide: Guide) -> tuple[bytes, str] | None:
    """Return (bytes, media_type) for the guide's reference image, or None.

    Used by both the preview endpoint and the generation vision path. Returns
    None when no image is set or the stored file has gone missing.
    """
    image_id = guide.reference_image_id
    if image_id is None:
        return None
    row = db.get(GuideReferenceImage, image_id)
    if row is None:
        return None
    path = _path_for(row.storage_key)
    if not path.exists():
        return None
    raw = path.read_bytes()
    try:
        _, _, media_type = _decode(raw)
    except ReferenceImageError:
        return None
    return raw, media_type

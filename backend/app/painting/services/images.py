"""Reference-image acquisition: upload + STL-model-folder sourcing, with
provenance tracking (spec §4.4 / §8.5).

The dependable, fully-local spine of the spec's fallback chain (#535 + #494):

* **user_upload** — `store_upload` (the original #535 rung).
* **stl_model_folder** — `list_model_candidates` / `store_from_model`: the
  linked model's already-indexed folder images, zero-cost (rung 0). The caller
  picks a candidate by index, so no request value ever reaches the filesystem.

The rungs that fetch from the network — user-supplied URL (rung 4), assisted
web search (rung 2), AI generation (rung 3) — are deferred to #563, where the
SSRF surface gets a dedicated IP-pinned guard rather than riding the shared
thumbnail downloader.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.models import Model
from app.painting.models import Guide, GuideReferenceImage
from app.routers.files import _is_safe_path
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


def _persist(
    db: Session,
    guide: Guide,
    raw: bytes,
    *,
    provenance: str,
    source_url: str | None = None,
    alt_text: str | None = None,
) -> GuideReferenceImage:
    """Validate bytes, replace any existing reference, and store + wire the FK.

    Shared by every acquisition rung; only `provenance`/`source_url` differ.
    Raises ReferenceImageError on bad/oversize/unsupported bytes. Caller commits.
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
        provenance=provenance,
        source_url=source_url,
        alt_text=alt_text,
        width=width,
        height=height,
    )
    db.add(row)
    db.flush()  # assign row.id
    guide.reference_image_id = row.id
    return row


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
    return _persist(db, guide, raw, provenance="user_upload", alt_text=alt_text)


def list_model_candidates(db: Session, guide: Guide) -> list[str]:
    """Reference-image candidates from the guide's linked STL model (rung 0).

    Returns the linked model's indexed folder images (thumbnail first, then
    `image_paths`), deduped, restricted to existing files inside a scan root.
    Empty when the guide has no linked model or no indexed images.
    """
    if guide.model_id is None:
        return []
    model = db.get(Model, guide.model_id)
    if model is None:
        return []

    raw_paths: list[str] = []
    if model.thumbnail_path:
        raw_paths.append(model.thumbnail_path)
    raw_paths.extend(model.image_paths or [])

    candidates: list[str] = []
    seen: set[str] = set()
    for p in raw_paths:
        if p in seen:
            continue
        seen.add(p)
        path = Path(p)
        if _is_safe_path(path) and path.exists():
            candidates.append(p)
    return candidates


def store_from_model(
    db: Session,
    guide: Guide,
    index: int,
    *,
    alt_text: str | None = None,
) -> GuideReferenceImage:
    """Copy a linked-model folder image into the guide's reference store (rung 0).

    `index` selects from `list_model_candidates(db, guide)`. Because the read
    target is taken from that server-built, scan-root-validated list — never
    from a request-supplied path — there is no path-injection surface. Raises
    ReferenceImageError on an out-of-range index or unreadable bytes.
    """
    candidates = list_model_candidates(db, guide)
    if not 0 <= index < len(candidates):
        raise ReferenceImageError(
            "That isn't one of the linked model's folder images."
        )
    raw = Path(candidates[index]).read_bytes()
    return _persist(db, guide, raw, provenance="stl_model_folder", alt_text=alt_text)


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

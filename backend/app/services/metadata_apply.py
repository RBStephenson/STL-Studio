"""Apply scraped/fetched metadata onto a local model.

Single writer shared by the per-model Find-on-Web path (scrape router) and the
bulk creator-enrichment path (enrich router), so both apply the same field set
with the same semantics — no drift between "enrich one" and "enrich many".

The two call sites differ in policy, exposed as flags:
  * ``overwrite_title`` — the reviewed single-model path overwrites the title;
    the bulk path only fills an empty title (less human review per item).
  * ``thumbnail_fill_only`` — the bulk path never replaces an existing local
    thumbnail; the single-model path always refreshes it.
  * ``reassign_creator`` — the reviewed single-model path may re-point the
    model's creator; the bulk/refresh paths never do (the store's spelling of
    a creator name can differ from the local creator being enriched, and
    reassigning would silently split the library — #699 1.1). Fills
    ``creator_id`` when it is NULL regardless of the flag.
  * ``clear_needs_review`` — the reviewed single-model path clears the flag;
    bulk apply leaves it since no human looked at the deep data (#699 1.3).

Gallery images (``scraped.image_urls``, #1028) are downloaded the same way
for every call site, unlike the flags above: unconditionally, every time,
capped at 30 — matching Import's own gallery-image cap. Unlike the thumbnail
(single slot, ``thumbnail_fill_only`` decides whether to touch it), a
gallery download always runs; there's no per-caller flag to skip it. What's
preserved across repeated fetches is *which files*, not *whether* to fetch:
only the subset of ``image_paths`` previously written by a fetch (files
under ``gallery_images_dir()``) is replaced with the fresh set — anything
else already in the gallery (e.g. scan-discovered images sitting in the
model's own library folder) is left alone, so a rescan's images and a
fetch's images can coexist without either being able to stomp the other.
"""
import logging
import os

from sqlalchemy.orm import Session

from app.models import Model
from app.services import thumbnails
from app.services.scanner import resolve_creator
from app.services.scrapers.base import ScrapedModel
from app.services.thumbnails import ThumbnailDownloadError
from app.services.variant_sync import propagate_source_url
from app.utils import utcnow

logger = logging.getLogger(__name__)


async def fill_gallery_images(model: Model, image_urls: list[str]) -> None:
    """Download ``image_urls`` into ``model.image_paths`` (no commit),
    unconditionally — every Fetch/Enrich run replaces the previously-fetched
    subset of the gallery with a fresh one, capped at 30 (#1028). Standalone
    (not folded silently into apply_scraped_to_model's body) so the Edit
    Metadata panel's own inline Fetch/Apply flow — which merges scraped
    fields into its local form and saves via a plain PATCH /models/{id},
    never going through apply_scraped_to_model at all — can call it too."""
    if not image_urls:
        return
    saved = await thumbnails.download_gallery_images(model.id, image_urls)
    if not saved:
        return
    # Only replace files this mechanism itself previously wrote — anything
    # else in image_paths (scan-discovered images from the model's own
    # library folder) is untouched, not stomped by a fetch that happens to
    # return fewer/different images this time.
    fetched_prefix = os.path.realpath(str(thumbnails.gallery_images_dir())) + os.sep
    kept = [p for p in (model.image_paths or []) if not p.startswith(fetched_prefix)]
    model.image_paths = kept + saved


async def apply_scraped_to_model(
    db: Session,
    model: Model,
    scraped: ScrapedModel,
    *,
    overwrite_title: bool = True,
    thumbnail_fill_only: bool = False,
    reassign_creator: bool = True,
    clear_needs_review: bool = True,
) -> None:
    """Write the populated fields of ``scraped`` onto ``model`` (no commit)."""
    if scraped.title and (overwrite_title or not model.title):
        model.title = scraped.title
    if scraped.description:
        model.description = scraped.description
    if scraped.source_url:
        model.source_url = scraped.source_url
    if scraped.source_site:
        model.source_site = scraped.source_site
    if scraped.external_id:
        model.external_id = scraped.external_id

    if scraped.thumbnail_url and not (thumbnail_fill_only and model.thumbnail_path):
        # Download the remote image to a local file — CDNs block hot-linking, and
        # the UI gives thumbnail_path precedence over thumbnail_url.
        try:
            model.thumbnail_path = str(
                await thumbnails.download_thumbnail(model.id, scraped.thumbnail_url)
            )
            model.thumbnail_url = None
        except ThumbnailDownloadError as e:
            logger.warning(f"Thumbnail download failed for model {model.id}: {e}")
            # Fall back to the bare URL, clearing the local path so the new remote
            # image actually takes display precedence.
            model.thumbnail_url = scraped.thumbnail_url
            model.thumbnail_path = None

    await fill_gallery_images(model, scraped.image_urls)

    if scraped.tags:
        model.tags = list(set(model.tags or []) | set(scraped.tags))
    if scraped.category:
        model.category = scraped.category
    if scraped.license:
        model.license = scraped.license
    if scraped.like_count is not None:
        model.like_count = scraped.like_count
    if scraped.download_count is not None:
        model.download_count = scraped.download_count

    if scraped.creator_name and (reassign_creator or model.creator_id is None):
        model.creator_id = resolve_creator(scraped.creator_name, db).id

    if scraped.source_url:
        propagate_source_url(db, model)

    model.source_last_fetched = utcnow()
    if clear_needs_review:
        model.needs_review = False
    model.updated_at = utcnow()

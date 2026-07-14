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
for both call sites, unlike the flags above: only when the model's
``image_paths`` is currently empty, capped at 30. Unlike the thumbnail
(single slot, always refreshed by the single-model path), a gallery has no
single "current" image to compare against and no reliable way to tell which
already-downloaded files came from which source URL — so both paths use the
same conservative fill-only-when-empty policy to avoid ballooning a gallery
on repeated fetches.
"""
import logging

from sqlalchemy.orm import Session

from app.models import Model
from app.services.scanner import resolve_creator
from app.services.scrapers.base import ScrapedModel
from app.services.thumbnails import ThumbnailDownloadError, download_gallery_images, download_thumbnail
from app.services.variant_sync import propagate_source_url
from app.utils import utcnow

logger = logging.getLogger(__name__)


async def fill_gallery_images(model: Model, image_urls: list[str]) -> None:
    """Download ``image_urls`` into ``model.image_paths`` (no commit), but only
    when the model has no gallery images yet (#1028) — see the module
    docstring for why this has no per-caller policy flag. Standalone (not
    folded silently into apply_scraped_to_model's body) so the Edit Metadata
    panel's own inline Fetch/Apply flow — which merges scraped fields into
    its local form and saves via a plain PATCH /models/{id}, never going
    through apply_scraped_to_model at all — can call it too."""
    if not image_urls or model.image_paths:
        return
    saved = await download_gallery_images(model.id, image_urls)
    if saved:
        model.image_paths = saved


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
                await download_thumbnail(model.id, scraped.thumbnail_url)
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

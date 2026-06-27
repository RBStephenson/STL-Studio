"""Apply scraped/fetched metadata onto a local model.

Single writer shared by the per-model Find-on-Web path (scrape router) and the
bulk creator-enrichment path (enrich router), so both apply the same field set
with the same semantics — no drift between "enrich one" and "enrich many".

The two call sites differ only in two policies, exposed as flags:
  * ``overwrite_title`` — the reviewed single-model path overwrites the title;
    the bulk path only fills an empty title (less human review per item).
  * ``thumbnail_fill_only`` — the bulk path never replaces an existing local
    thumbnail; the single-model path always refreshes it.
"""
import logging

from sqlalchemy.orm import Session

from app.models import Model
from app.services.scanner import resolve_creator
from app.services.scrapers.base import ScrapedModel
from app.services.thumbnails import ThumbnailDownloadError, download_thumbnail
from app.services.variant_sync import propagate_source_url
from app.utils import utcnow

logger = logging.getLogger(__name__)


async def apply_scraped_to_model(
    db: Session,
    model: Model,
    scraped: ScrapedModel,
    *,
    overwrite_title: bool = True,
    thumbnail_fill_only: bool = False,
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

    if scraped.tags:
        model.tags = list(set(model.tags or []) | set(scraped.tags))
    if scraped.category:
        model.category = scraped.category
    if scraped.license:
        model.license = scraped.license
    if scraped.like_count is not None:
        model.rating = scraped.like_count  # store likes as proxy for rating
    if scraped.download_count is not None:
        model.download_count = scraped.download_count

    if scraped.creator_name:
        model.creator_id = resolve_creator(scraped.creator_name, db).id

    if scraped.source_url:
        propagate_source_url(db, model)

    model.source_last_fetched = utcnow()
    model.needs_review = False
    model.updated_at = utcnow()

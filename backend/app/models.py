from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, Boolean,
    ForeignKey, BigInteger, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils import utcnow


class ScanRoot(Base):
    __tablename__ = "scan_roots"

    id = Column(Integer, primary_key=True)
    path = Column(String, unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    # Human-readable label ("minis") shown as a Library in the import flow (#450).
    # Nullable; the API backfills a basename default for legacy rows.
    name = Column(String, nullable=True)
    # Marks this root as a managed import *destination* — a "library" files can be
    # moved into (#450). Default off: the actual disk-write probe + config flag are
    # still enforced at apply time (reorganize_apply._probe_writable, #324).
    is_writable = Column(Boolean, nullable=False, default=False, server_default="0")
    # Folder-layout template (see services/layout.py). Describes the path levels
    # down to the creator; the scanner detects models heuristically below it.
    layout = Column(String, nullable=False, default="{creator}", server_default="{creator}")
    last_scanned = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class ImportSourceMapping(Base):
    """Persisted mapping from an import source root folder to a destination
    library (#450). Set once per source root; pack cards under it inherit the
    destination, and the import dropdown pre-fills (but stays editable)."""
    __tablename__ = "import_source_mappings"

    id = Column(Integer, primary_key=True)
    source_path = Column(String, unique=True, nullable=False)
    library_id = Column(Integer, ForeignKey("scan_roots.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=utcnow)


class PackOverride(Base):
    """A folder the user has explicitly marked as a multi-product *pack*.

    The scanner treats it as a boundary — never a model itself — and indexes each
    child folder as its own model (grouped under the child's name). Persisted so an
    opt-in split survives future rescans. Used because pack-vs-variant can't be told
    apart reliably by folder name alone."""
    __tablename__ = "pack_overrides"

    id = Column(Integer, primary_key=True)
    path = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class GroupOverride(Base):
    """A model the user has manually assigned to a specific character group.

    Persisted so the assignment survives rescans. character=None means the model
    is explicitly ungrouped (removed from any character group). Mirrors PackOverride
    for the group dimension: the scanner applies this instead of the heuristic."""
    __tablename__ = "group_overrides"

    id = Column(Integer, primary_key=True)
    path = Column(String, unique=True, nullable=False)  # model folder_path
    character = Column(String, nullable=True)           # None = explicitly ungrouped
    created_at = Column(DateTime, default=utcnow)


class Creator(Base):
    __tablename__ = "creators"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    source_url = Column(String, nullable=True)
    models = relationship("Model", back_populates="creator")


class Model(Base):
    """One logical model (a folder under a creator). May contain many STL files."""
    __tablename__ = "models"
    __table_args__ = (
        # Variant-collapse window partitions by (creator_id, character); the
        # creator sort reuses the leading column.
        Index("ix_models_creator_character", "creator_id", "character"),
        # Default grid sort is ORDER BY character, name — needs an index led by
        # character (the creator_character one can't serve it).
        Index("ix_models_character_name", "character", "name"),
        # `sort=added` orders by created_at desc (#170).
        Index("ix_models_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    folder_path = Column(String, unique=True, nullable=False)
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=True)

    # Hierarchy
    character = Column(String, nullable=True)     # inferred grouping above model level

    # Metadata — user-edited or scraped
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    source_url = Column(String, nullable=True)
    source_site = Column(String, nullable=True)   # thingiverse|printables|gumroad|…
    license = Column(String, nullable=True)
    tags = Column(JSON, default=list)             # user-set tags
    auto_tags = Column(JSON, default=list)        # scanner-detected: scale, type, modifiers
    removed_auto_tags = Column(JSON, default=list)  # auto-tags the user suppressed; survives rescans
    category = Column(String, nullable=True)
    custom_attributes = Column(JSON, default=dict)  # arbitrary key/value attributes
    print_settings = Column(JSON, default=dict)
    external_id = Column(String, nullable=True)   # ID on the source site

    # Scraping
    source_last_fetched = Column(DateTime, nullable=True)

    # Content
    nsfw = Column(Boolean, default=False)

    # Review state
    needs_review = Column(Boolean, default=False)  # scanner flagged low-confidence detection
    # Inbox flag: set when the model was imported via the one-shot import-folder
    # flow (#428) rather than a permanent scan root. Cleared once the model is
    # moved into the managed library via reorganize apply (#324).
    is_inbox = Column(Boolean, default=False, server_default="0", nullable=False, index=True)

    # User-hidden from the viewer. Files on disk are left untouched; the scanner
    # preserves this flag and never resurrects an excluded model on rescan.
    excluded = Column(Boolean, default=False, index=True)

    # User curation — independent flags
    is_favorite = Column(Boolean, default=False, index=True)
    # User-designated display thumbnail for the model's variant group (#193).
    # When set on a member, that model becomes the group's representative card
    # (overriding the id/has-thumbnail heuristic). Survives rescans like other
    # user flags; harmless if the group later changes.
    is_group_rep = Column(Boolean, default=False, server_default="0", nullable=False)
    # Manual position within the model's variant group (#399). NULL = no manual
    # order (heuristic decides). When set across a group, the lowest value is the
    # group's representative card. Survives rescans like other user choices.
    variant_order = Column(Integer, nullable=True)
    user_rating = Column(Integer, nullable=True, index=True)  # 1–5 stars; NULL = unrated (#167)

    # Print-status lifecycle: none → queued → printing → printed. Single source of
    # truth for print tracking (#166); the legacy in_queue boolean was retired in
    # favor of this column. The timestamps below are supporting metadata the status
    # string can't carry on its own.
    print_status = Column(String, nullable=False, default="none", server_default="none", index=True)
    print_count = Column(Integer, nullable=False, default=0, server_default="0")
    queued_at = Column(DateTime, nullable=True)              # when queued (tiebreak ordering)
    queue_position = Column(Integer, nullable=True)          # manual drag-to-reorder order
    printed_at = Column(DateTime, nullable=True)             # last marked printed (History sort)

    # Images
    thumbnail_path = Column(String, nullable=True)   # local path
    thumbnail_url = Column(String, nullable=True)    # remote URL
    image_paths = Column(JSON, default=list)          # additional local images (gallery)
    other_files = Column(JSON, default=list)          # non-STL, non-image files (PDFs, TXTs, etc.)
    primary_image_path = Column(String, nullable=True)  # user-selected card image from image_paths

    # Persisted Set-Thumbnail picker manifest (#304). Caches the walk of the
    # character boundary so reopening the picker — even across restarts — needs
    # no directory enumeration when the folder signature is unchanged.
    image_manifest = Column(JSON, nullable=True)          # [{path, filename}] or None (never built)
    image_manifest_sig = Column(String, nullable=True)    # boundary signature the manifest was built from

    # Stats from source site
    rating = Column(Float, nullable=True)
    download_count = Column(Integer, nullable=True)

    # Housekeeping
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    creator = relationship("Creator", back_populates="models")
    stl_files = relationship("STLFile", back_populates="model")
    collection_links = relationship("CollectionModel", back_populates="model")


class STLFile(Base):
    __tablename__ = "stl_files"

    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    path = Column(String, unique=True, nullable=False)
    filename = Column(String, nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    file_hash = Column(String, nullable=True, index=True)
    part_type = Column(String, nullable=True)   # user-assigned part category
    part_name = Column(String, nullable=True)   # user-assigned display name (overrides auto-generated label)
    sup_of_id = Column(Integer, ForeignKey("stl_files.id"), nullable=True)  # explicit sup relationship
    created_at = Column(DateTime, default=utcnow)

    model = relationship("Model", back_populates="stl_files")


class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    cover_image_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    model_links = relationship("CollectionModel", back_populates="collection")


class CollectionModel(Base):
    __tablename__ = "collection_models"
    __table_args__ = (UniqueConstraint("collection_id", "model_id"),)

    id = Column(Integer, primary_key=True)
    collection_id = Column(Integer, ForeignKey("collections.id"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)

    collection = relationship("Collection", back_populates="model_links")
    model = relationship("Model", back_populates="collection_links")


class ModelTag(Base):
    """Denormalized tag index — one row per (model, tag) pair.

    Derived from models.tags (user-set) and models.auto_tags (scanner-detected).
    User tags take precedence: if a tag appears in both, is_auto=False.
    Rebuilt by tag_sync.sync_model_tags() whenever tags change.
    """
    __tablename__ = "model_tags"
    __table_args__ = (
        UniqueConstraint("model_id", "tag", name="uq_model_tag"),
        Index("ix_model_tags_tag", "tag"),
    )

    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True)
    tag = Column(String, nullable=False)
    is_auto = Column(Boolean, nullable=False, default=False)


class AppSetting(Base):
    """Server-persisted app-wide settings as key/value rows.

    Known keys and their defaults live in schemas.AppSettingsRead;
    rows exist only for values the user has explicitly set.
    """
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(JSON, nullable=False)


class ReorganizeManifest(Base):
    """A persisted library-reorganize preview manifest (#323, Phase 1).

    The preview is computed and stored as an immutable artifact (id + JSON
    payload of entries with per-file source paths and fingerprints) so Phase 2
    (#324) can execute the *approved* manifest and verify non-drift, rather than
    silently recomputing — see the issue's decision B. No files are moved here.
    """
    __tablename__ = "reorganize_manifests"

    id = Column(String, primary_key=True)          # uuid4 hex
    template = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)         # full ReorganizePreviewResponse
    created_at = Column(DateTime, default=utcnow)

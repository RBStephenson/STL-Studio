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
    # Opt-in folder-driven grouping: when on, the first folder below the creator is
    # the character, and every model anywhere beneath it is one variant group —
    # bypassing the name-based heuristic. Off by default. (User overrides still win.)
    group_by_character = Column(Boolean, nullable=False, default=False, server_default="0")
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


class GroupingStrategy(Base):
    """Per-subtree variant-grouping strategy (#618). Keyed by a folder path; the
    nearest ancestor of a model's folder wins, defaulting to "auto" when none
    applies. "off" tells the proposal engine to leave that subtree's models
    ungrouped (each standalone)."""
    __tablename__ = "grouping_strategies"

    id = Column(Integer, primary_key=True)
    path = Column(String, unique=True, nullable=False)   # folder path the strategy anchors
    strategy = Column(String, nullable=False, default="auto")  # "auto" | "off"
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
        # STUDIO-89: common Library filters that previously did a full scan —
        # source_site (source filter), needs_review (Triage), source_last_fetched
        # (enrich refresh's staleness filter).
        Index("ix_models_source_site", "source_site"),
        Index("ix_models_needs_review", "needs_review"),
        Index("ix_models_source_last_fetched", "source_last_fetched"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    folder_path = Column(String, unique=True, nullable=False)
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=True)

    # Hierarchy
    character = Column(String, nullable=True)     # inferred grouping above model level
    # First-class variant grouping (#613 P0). NULL = ungrouped. Membership is the
    # source of truth for grouping going forward; `character` stays as the display
    # label during the phased migration. Indexed for the variant-collapse window.
    variant_group_id = Column(
        Integer, ForeignKey("variant_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )

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
    custom_attributes = Column(JSON, default=dict)  # arbitrary key/value attributes (user-set)
    parsed_attributes = Column(JSON, default=dict)  # scanner-detected variant attrs: support_status, cut_status, slicer, version
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

    # Explicit "keep me out of any group" pin (#678 Phase 5), sticky across
    # rescans — replaces the retired GroupOverride(character=None) row. Set by
    # the durable-group split/remove path; cleared when the model is explicitly
    # merged into a group again.
    no_group = Column(Boolean, nullable=False, default=False, server_default="0")

    # User curation — independent flags
    is_favorite = Column(Boolean, default=False, index=True)
    # Lock (shown as "Organized" in the UI — don't confuse with the unrelated
    # ModelDetail.unorganized computed field in schemas.py, a folder-location
    # mismatch indicator with no relation to this one): not just a status
    # label — while set, no process may alter this model's STL files,
    # categories, or part names (manual edit, bulk recategorize, AI Organize
    # apply, drag-to-categorize) or move/rename them via Reorganize. Toggled
    # from the library card; enforced server-side at every write path that
    # touches those fields, not just hidden in the UI.
    locked = Column(Boolean, default=False, server_default="0", nullable=False, index=True)
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
    removed_image_paths = Column(JSON, default=list)  # gallery images the user suppressed; survives rescans
    other_files = Column(JSON, default=list)          # non-STL, non-image files (PDFs, TXTs, etc.)
    primary_image_path = Column(String, nullable=True)  # user-selected card image from image_paths

    # Persisted Set-Thumbnail picker manifest (#304). Caches the walk of the
    # character boundary so reopening the picker — even across restarts — needs
    # no directory enumeration when the folder signature is unchanged.
    image_manifest = Column(JSON, nullable=True)          # [{path, filename}] or None (never built)
    image_manifest_sig = Column(String, nullable=True)    # boundary signature the manifest was built from

    # Stats from source site
    rating = Column(Float, nullable=True)
    like_count = Column(Integer, nullable=True)  # store like/heart count (#699 1.2)
    download_count = Column(Integer, nullable=True)

    # Housekeeping
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    creator = relationship("Creator", back_populates="models")
    stl_files = relationship("STLFile", back_populates="model")
    collection_links = relationship("CollectionModel", back_populates="model")
    variant_group = relationship(
        "VariantGroup", back_populates="models", foreign_keys=[variant_group_id]
    )


class VariantGroup(Base):
    """A durable, first-class variant group (#613). Models point in via
    `variant_group_id`. `source` distinguishes scanner-proposed ("auto") groups,
    which a rescan may revise, from user-curated ("manual") groups, which it must
    never touch."""
    __tablename__ = "variant_groups"

    id = Column(Integer, primary_key=True)
    creator_id = Column(Integer, ForeignKey("creators.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String, nullable=True)             # display name for the group
    # use_alter breaks the models<->variant_groups FK cycle so create_all/drop_all
    # can order the tables (rep_model_id -> models, models.variant_group_id -> here).
    rep_model_id = Column(
        Integer,
        ForeignKey("models.id", ondelete="SET NULL", use_alter=True, name="fk_variant_groups_rep_model"),
        nullable=True,
    )
    source = Column(String, nullable=False, default="auto", server_default="auto")  # "auto" | "manual"
    reason = Column(String, nullable=True)            # why these grouped (proposal engine, P1)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    creator = relationship("Creator")
    models = relationship(
        "Model", back_populates="variant_group", foreign_keys="Model.variant_group_id"
    )
    rep_model = relationship("Model", foreign_keys=[rep_model_id])


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


class AiApiConfig(Base):
    """Named AI API endpoint configuration — one row per user-defined entry.

    Multiple configs of the same type are allowed (e.g. two Ollama instances).
    Encrypted API keys are stored separately in app_settings under the key
    `ai_api_key_<id>_enc` to keep them out of this table's plaintext rows.
    """
    __tablename__ = "ai_api_configs"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    api_type = Column(String, nullable=False)  # "anthropic" | "openai"
    url = Column(String, nullable=True)         # OpenAI-compatible base URL
    model = Column(String, nullable=False, default="")
    effort = Column(String, nullable=True)      # Anthropic only: "low"|"medium"|"high"
    # Per-connection request timeout in seconds. Remote endpoints (e.g. an
    # Ollama box loading a model cold) can take far longer than a local one, so
    # this is tunable per config rather than a single global. Default 10s.
    request_timeout = Column(Integer, nullable=False, default=10, server_default="10")
    # Max files sent to the LLM per AI Organize request/batch. None = use the
    # service's built-in defaults (ai_organize._LLM_FILE_CAP / _UNIT_LLM_FILE_CAP).
    # Tunable per connection since a fast/reliable endpoint can safely take
    # bigger batches than a slow local one prone to running out of max_tokens.
    batch_size = Column(Integer, nullable=True)
    # OpenAI-compatible connections only: let the model reason before
    # answering instead of actively suppressing it. Off by default — a
    # thinking phase adds latency and, worse, risks the model burning its
    # whole max_tokens budget on hidden reasoning and returning nothing (#903).
    reasoning_enabled = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime, default=utcnow)


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

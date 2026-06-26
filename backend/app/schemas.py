from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

# Reused as the shape of the app-level default guide theme (#514). The painting
# schemas don't import app.schemas, so this import is one-directional (no cycle).
from app.painting.schemas import GuideTheme


class CreatorBase(BaseModel):
    name: str
    source_url: Optional[str] = None


class CreatorRead(CreatorBase):
    id: int
    model_count: Optional[int] = 0

    class Config:
        from_attributes = True


class STLFileRead(BaseModel):
    id: int
    path: str
    filename: str
    size_bytes: Optional[int] = None
    part_type: Optional[str] = None

    class Config:
        from_attributes = True


class ModelBase(BaseModel):
    name: str
    folder_path: str


class ModelRead(ModelBase):
    id: int
    native_folder_path: Optional[str] = None
    title: Optional[str] = None
    character: Optional[str] = None
    variant_count: int = 1
    description: Optional[str] = None
    notes: Optional[str] = None
    source_url: Optional[str] = None
    source_site: Optional[str] = None
    license: Optional[str] = None
    tags: list = []
    auto_tags: list = []
    removed_auto_tags: list = []
    category: Optional[str] = None
    custom_attributes: dict = {}
    needs_review: bool = False
    is_inbox: bool = False
    nsfw: bool = False
    excluded: bool = False
    is_favorite: bool = False
    is_group_rep: bool = False
    variant_order: Optional[int] = None
    user_rating: Optional[int] = None
    queued_at: Optional[datetime] = None
    printed_at: Optional[datetime] = None
    print_status: str = "none"
    print_count: int = 0
    thumbnail_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    image_paths: list = Field(default_factory=list)
    other_files: list = Field(default_factory=list)
    primary_image_path: Optional[str] = None

    @field_validator("image_paths", "other_files", mode="before")
    @classmethod
    def _coerce_list(cls, v: object) -> list:
        return v if isinstance(v, list) else []
    rating: Optional[float] = None
    download_count: Optional[int] = None
    creator_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ModelDetail(ModelRead):
    stl_files: list[STLFileRead] = []
    creator: Optional[CreatorRead] = None
    collection_ids: list[int] = []
    has_group_override: bool = False
    group_override: Optional[str] = None  # the override value (None = explicitly ungrouped)


class ModelList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ModelRead]


class ScanStatus(BaseModel):
    running: bool
    message: str
    models_found: Optional[int] = None
    files_found: Optional[int] = None
    cancelled: bool = False


class CollectionBase(BaseModel):
    name: str
    description: Optional[str] = None


class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class CollectionRead(CollectionBase):
    id: int
    cover_image_path: Optional[str] = None
    model_count: Optional[int] = 0
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class ModelUpdate(BaseModel):
    """Partial update — only the fields actually sent are applied."""
    title: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    source_url: Optional[str] = None
    source_site: Optional[str] = None
    license: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    removed_auto_tags: Optional[list[str]] = None
    custom_attributes: Optional[dict] = None
    nsfw: Optional[bool] = None
    needs_review: Optional[bool] = None
    thumbnail_url: Optional[str] = None
    primary_image_path: Optional[str] = None
    image_paths: Optional[list] = None
    creator_name: Optional[str] = None


class ThumbnailUpdate(BaseModel):
    thumbnail_path: Optional[str] = None
    thumbnail_url: Optional[str] = None


class ThumbnailFromUrl(BaseModel):
    url: str


class BatchThumbnailFromUrl(BaseModel):
    """Download one image and store it as the thumbnail for many models (#184).
    Fetched once, fanned out to every member's per-model thumbnail file."""
    model_ids: list[int]
    url: str


class BatchSetSourceUrl(BaseModel):
    """Set one store-page URL on a selected set of variants (#500).

    Selection-scoped and overwriting: the URL is written to exactly the given
    ids (replacing any existing URL), with NO fill-empty propagation to
    unselected siblings — distinct from the passive single-model path (#202)."""
    model_ids: list[int]
    source_url: str


class GroupRepUpdate(BaseModel):
    """Designate (or clear) a model as its variant group's display rep (#193)."""
    is_group_rep: bool = True


class FavoriteUpdate(BaseModel):
    is_favorite: bool


class RatingUpdate(BaseModel):
    # 1–5 sets the star rating; None clears it back to unrated (#167).
    rating: Optional[int] = Field(None, ge=1, le=5)


class QueueReorder(BaseModel):
    ids: list[int]   # queued model ids in the desired manual order


class GroupReorder(BaseModel):
    creator_id: int
    character: str
    # Member ids in the desired display order. Empty = reset (clear the whole
    # group's manual order, falling back to the heuristic). Ids not in the group
    # are ignored.
    ids: list[int] = []


PRINT_STATUSES = {"none", "queued", "printing", "printed"}


class PrintStatusUpdate(BaseModel):
    status: str

    def validate_status(self):
        if self.status not in PRINT_STATUSES:
            raise ValueError(f"status must be one of {sorted(PRINT_STATUSES)}")


class ExcludeUpdate(BaseModel):
    excluded: bool


class STLFileUpdate(BaseModel):
    part_type: Optional[str] = None


class BulkTagUpdate(BaseModel):
    ids: list[int]
    add_tags: list[str] = []
    remove_tags: list[str] = []


class BulkExcludeUpdate(BaseModel):
    ids: list[int]
    excluded: bool


class BulkReviewUpdate(BaseModel):
    ids: list[int]
    needs_review: bool


class BulkEnrichUpdate(BaseModel):
    ids: list[int]
    creator_name: Optional[str] = None
    character: Optional[str] = None
    title: Optional[str] = None
    notes: Optional[str] = None
    source_url: Optional[str] = None
    gallery_images: Optional[list[str]] = None


class BulkDeleteRequest(BaseModel):
    ids: list[int]
    delete_files: bool = False


class BulkDeleteResponse(BaseModel):
    deleted: int
    folders_removed: int


class SetGroupBody(BaseModel):
    character: Optional[str] = None  # None = explicitly ungroup; string = target group name


class BatchSetGroupBody(BaseModel):
    """Assign many models to one group (or ungroup) in a single transaction.
    Powers group rename / merge / split / ungroup on the VariantGroup page."""
    model_ids: list[int]
    character: Optional[str] = None  # None = explicitly ungroup all; string = target group name


class InboxScanRequest(BaseModel):
    path: str


class ScanRootCreate(BaseModel):
    path: str
    layout: str = "{creator}"
    name: Optional[str] = None
    is_writable: bool = False


class ScanRootUpdate(BaseModel):
    layout: Optional[str] = None
    enabled: Optional[bool] = None
    name: Optional[str] = None
    is_writable: Optional[bool] = None


class LibraryRead(BaseModel):
    """A scan root usable as an import destination (#450)."""
    id: int
    path: str
    name: str
    is_writable: bool
    write_enabled: bool  # deployment-level reorganize_write_enabled flag

    class Config:
        from_attributes = True


class SourceMappingRead(BaseModel):
    source_path: str
    library_id: int

    class Config:
        from_attributes = True


class SourceMappingSet(BaseModel):
    source_path: str
    library_id: int


class ImportPreviewPack(BaseModel):
    """One pack card in the import preview — a top-level source subfolder (#451)."""
    name: str
    source_path: str
    file_count: int
    model_ids: list[int]
    # Representative metadata: the common value across the pack's models, or None
    # when they disagree (Child C bulk-sets a single value for the whole pack).
    creator_name: Optional[str] = None
    title: Optional[str] = None
    character: Optional[str] = None
    notes: Optional[str] = None
    source_url: Optional[str] = None
    tags: list[str] = []


class ImportPreviewResponse(BaseModel):
    source: str
    library_id: Optional[int] = None  # inherited destination from the source mapping
    packs: list[ImportPreviewPack]


class SourceContentsEntry(BaseModel):
    """An immediate subfolder of an import source (browse-first card data, #452)."""
    name: str
    path: str
    already_imported: bool  # has inbox models already ingested under it
    file_count: int  # recursive count of STL-family files on disk (#456)


class SourceContentsResponse(BaseModel):
    source: str
    is_flat: bool  # source itself holds STLs directly (single-pack layout)
    entries: list[SourceContentsEntry]
    file_count: int  # recursive STL count of the source root, for the flat card (#456)


class ImportApplyRequest(BaseModel):
    source: str


class DownloadImagesRequest(BaseModel):
    pack_path: str
    image_urls: list[str] = []


class ImportApplyIneligible(BaseModel):
    model_id: int
    proposed_dir: str
    reasons: list[str]


class ImportApplyResponse(BaseModel):
    manifest_id: str
    moved_models: int
    moved_files: int
    skipped: int                       # ineligible entries not moved
    ineligible: list[ImportApplyIneligible]
    undo_log: Optional[str] = None


class DownloadZipRequest(BaseModel):
    file_ids: list[int]
    zip_name: str = "kit-build"

    class Config:
        from_attributes = True


class EnvReloadResult(BaseModel):
    """Outcome of re-reading the .env / environment config (#140). Carries only
    the live-effective values that are safe to show — never secrets."""
    ok: bool = True
    scan_roots: list[str] = []
    drive_mappings: dict[str, str] = {}
    restart_required: list[str] = []


class FilterPreset(BaseModel):
    """A saved Library filter: a display name plus the filter querystring."""
    name: str
    qs: str

    model_config = {"extra": "forbid"}


class ScanTagRule(BaseModel):
    """A user keyword→tag inference rule (#31). When a folder/file name contains
    the whole word `keyword` (case-insensitive), `tag` is added to auto-tags."""
    keyword: str
    tag: str


class AppSettingsRead(BaseModel):
    """Every known app setting with its default — the single source of truth
    for the store's whitelist (routers/settings.py derives DEFAULTS from it)."""
    painting_guides_enabled: bool = False
    show_nsfw: bool = False
    library_page_size: int = 48
    filter_presets: list[FilterPreset] = []
    recent_days: int = 7  # "Recently added" window in days (#170)
    library_sort: str = "name"  # default Library order: name | added | creator (#247)
    # Glob patterns of folders/files the scanner skips, merged with built-in
    # defaults (#31). Matched case-insensitively against a path's basename and
    # its full POSIX path — see services/scan_rules.py.
    scan_ignore_patterns: list[str] = []
    # User keyword→tag inference rules, merged with built-in detection (#31).
    scan_tag_rules: list[ScanTagRule] = []
    # Exact folder names treated as parts/structural (never a product or a
    # variant-grouping character), merged with built-in detection (#31).
    scan_parts_names: list[str] = []
    # App-level default guide theme (#514): new guides inherit these colors when
    # they don't carry their own theme. All-None means "use the corpus default".
    guide_theme_defaults: GuideTheme = GuideTheme()
    # AI model id for guide generation (#517). The API key is NOT here — it's
    # encrypted at rest and handled by the dedicated /settings/ai endpoints.
    ai_model: str = ""
    # AI generation effort → extended-thinking budget (low = off). (#517)
    ai_effort: str = "low"


class AppSettingsUpdate(BaseModel):
    """Partial update for the app_settings store. extra="forbid" keeps the
    whitelist tight: unknown keys are a 422, never silently stored. None
    means "leave unchanged" — the router skips None values on write."""
    painting_guides_enabled: Optional[bool] = None
    show_nsfw: Optional[bool] = None
    library_page_size: Optional[int] = Field(None, ge=12, le=200)
    filter_presets: Optional[list[FilterPreset]] = None
    recent_days: Optional[int] = Field(None, ge=1, le=90)
    # Only the three user-facing Library sorts are persistable defaults; the
    # queue/queued_at/printed_at keys are page-specific, not a Library default.
    library_sort: Optional[str] = Field(None, pattern="^(name|added|creator|rating)$")
    # Up to 200 ignore globs (#31); each non-blank and <=200 chars. Blanks are
    # dropped so an empty editor row can't poison the list.
    scan_ignore_patterns: Optional[list[str]] = Field(None, max_length=200)

    scan_tag_rules: Optional[list[ScanTagRule]] = Field(None, max_length=500)
    scan_parts_names: Optional[list[str]] = Field(None, max_length=500)
    guide_theme_defaults: Optional[GuideTheme] = None
    ai_model: Optional[str] = Field(None, max_length=200)
    ai_effort: Optional[str] = Field(None, pattern="^(low|medium|high)$")

    @field_validator("scan_ignore_patterns", "scan_parts_names")
    @classmethod
    def _clean_patterns(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        cleaned = [p.strip() for p in v if p and p.strip()]
        if any(len(p) > 200 for p in cleaned):
            raise ValueError("entries must be 200 characters or fewer")
        # de-dupe, preserve order
        seen: set[str] = set()
        out: list[str] = []
        for p in cleaned:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    @field_validator("scan_tag_rules")
    @classmethod
    def _clean_tag_rules(cls, v: Optional[list[ScanTagRule]]) -> Optional[list[ScanTagRule]]:
        if v is None:
            return None
        seen: set[tuple[str, str]] = set()
        out: list[ScanTagRule] = []
        for rule in v:
            keyword = rule.keyword.strip()
            tag = rule.tag.strip()
            if not keyword or not tag:
                continue  # blank rows dropped, never a 422
            if len(keyword) > 100 or len(tag) > 100:
                raise ValueError("tag rule keyword/tag must be 100 characters or fewer")
            key = (keyword.lower(), tag.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(ScanTagRule(keyword=keyword, tag=tag))
        return out

    model_config = {"extra": "forbid"}


# --- AI settings (#517) ---------------------------------------------------

class AiSettingsRead(BaseModel):
    """AI settings status. The API key is write-only — never returned in full,
    only whether one is set and a masked hint (e.g. `…wxyz`)."""
    key_set: bool
    key_hint: Optional[str] = None
    model: str = ""
    effort: str = "low"


class AiKeyUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=400)


# --- Cults3D settings -------------------------------------------------------

class Cults3DSettingsRead(BaseModel):
    configured: bool
    username: Optional[str] = None
    key_hint: Optional[str] = None


class Cults3DCredentialsUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=1, max_length=400)


# --- Library reorganize, Phase 1 preview (#323) ---------------------------

FingerprintMethod = Literal["stat", "content_hash"]
MoveKind = Literal["move", "rename", "case_rename", "in_place", "merge"]
CollisionKind = Literal[
    "none", "exact", "case_only", "unicode_only", "legitimate_duplicate"
]


class ReorganizeFileMove(BaseModel):
    stl_file_id: int
    current_path: str          # normalized, '/'-internal
    proposed_path: str
    # Real fingerprint for the Phase 2 drift check (decision D) — not the dead
    # STLFile.file_hash column. stat-only in Phase 1; content_hash deferred.
    size_bytes: int
    mtime_ns: int
    content_hash: Optional[str] = None
    fingerprint_method: FingerprintMethod
    # Source absent/unreadable at preview — (size, mtime) are a zeroed sentinel,
    # not a usable fingerprint for the Phase 2 drift check.
    missing_file: bool = False


class ReorganizeEntry(BaseModel):
    model_id: int
    model_name: str
    files: list[ReorganizeFileMove]   # the move unit is the file set
    kind: MoveKind
    proposed_dir: str
    eligible: bool

    # Path-keyed references this move invalidates (decision D); Phase 2 repaths.
    pack_override_paths: list[str]
    group_override_paths: list[str]

    # Blockers / flags.
    collision: bool
    collision_kind: CollisionKind
    collision_with: list[int]
    unclassifiable: bool
    missing_fields: list[str]
    over_length: bool
    reserved_name: bool
    overlaps_other: bool
    spans_multiple_dirs: bool
    is_symlink: bool
    escapes_scan_root: bool
    missing_files_on_disk: bool = False


class ReorganizeStats(BaseModel):
    total: int
    eligible: int
    moves_needed: int
    already_in_place: int
    collisions: int
    unclassifiable: int
    over_length: int
    reserved: int
    overlaps: int
    blocked: int                      # total ineligible


class ReorganizePreviewResponse(BaseModel):
    manifest_id: str                  # durable, identified artifact
    template: str
    generated_at: str
    entries: list[ReorganizeEntry]
    stats: ReorganizeStats


# --- Library reorganize, Phase 2a apply (#324) ----------------------------

class ReorganizeOverride(BaseModel):
    """User resolution for one flagged entry (Phase 2c). Any field left None
    falls back to the model's metadata; suffix is appended to the title."""
    creator: Optional[str] = None
    character: Optional[str] = None
    title: Optional[str] = None
    suffix: Optional[str] = None

    model_config = {"extra": "forbid"}


class ReorganizePreviewRequest(BaseModel):
    template: Optional[str] = None
    root_id: Optional[int] = None
    overrides: dict[int, ReorganizeOverride] = {}   # keyed by model_id

    model_config = {"extra": "forbid"}


class ReorganizeApplyRequest(BaseModel):
    manifest_id: str
    entry_ids: list[int]              # model_ids to apply (must be eligible)

    model_config = {"extra": "forbid"}


class ReorganizeApplyResponse(BaseModel):
    manifest_id: str
    moved_files: int
    moved_models: int
    undo_log: str                     # path to the crash-safe recovery log


class ReorganizeUndoRequest(BaseModel):
    manifest_id: str

    model_config = {"extra": "forbid"}


class ReorganizeUndoSkip(BaseModel):
    path: str
    reason: str                       # missing | drift | origin_occupied | …


class ReorganizeUndoResponse(BaseModel):
    manifest_id: str
    reversed_files: int
    skipped: list[ReorganizeUndoSkip]

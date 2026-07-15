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


class CreatorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_url: Optional[str] = None


class STLFileRead(BaseModel):
    id: int
    path: str
    filename: str
    size_bytes: Optional[int] = None
    part_type: Optional[str] = None
    part_name: Optional[str] = None
    sup_of_id: Optional[int] = None

    class Config:
        from_attributes = True


class VariantGroupRead(BaseModel):
    """Durable variant group (#613) — surfaced for the explain tooltip + group views."""
    id: int
    creator_id: int
    label: Optional[str] = None
    rep_model_id: Optional[int] = None
    source: str = "auto"            # "auto" | "manual"
    reason: Optional[str] = None
    confidence: Optional[float] = None

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
    variant_group_id: Optional[int] = None
    variant_group: Optional["VariantGroupRead"] = None  # explain: reason/confidence/source
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
    parsed_attributes: dict = {}  # scanner-detected: support_status, cut_status, slicer, version
    needs_review: bool = False
    is_inbox: bool = False
    nsfw: bool = False
    excluded: bool = False
    is_favorite: bool = False
    locked: bool = False
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
    removed_image_paths: list = Field(default_factory=list)
    other_files: list = Field(default_factory=list)
    primary_image_path: Optional[str] = None

    @field_validator("image_paths", "removed_image_paths", "other_files", mode="before")
    @classmethod
    def _coerce_list(cls, v: object) -> list:
        return v if isinstance(v, list) else []

    @field_validator("parsed_attributes", mode="before")
    @classmethod
    def _coerce_dict(cls, v: object) -> dict:
        return v if isinstance(v, dict) else {}
    rating: Optional[float] = None
    like_count: Optional[int] = None
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
    # True when this model's current folder no longer matches where it would
    # land under the library's organize template. Purely informational — never
    # blocks a save; the user still has to run Reorganize to actually move it.
    unorganized: bool = False


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
    removed_image_paths: Optional[list] = None
    creator_name: Optional[str] = None


class OtherFileDeleteRequest(BaseModel):
    """Delete one entry from Model.other_files, on disk and in the DB (#880)."""
    path: str


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


class GroupRepUpdate(BaseModel):
    """Designate (or clear) a model as its variant group's display rep (#193)."""
    is_group_rep: bool = True


class FavoriteUpdate(BaseModel):
    is_favorite: bool


class LockedUpdate(BaseModel):
    locked: bool


class RatingUpdate(BaseModel):
    # 1–5 sets the star rating; None clears it back to unrated (#167).
    rating: Optional[int] = Field(None, ge=1, le=5)


class QueueReorder(BaseModel):
    ids: list[int]   # queued model ids in the desired manual order


class GroupReorder(BaseModel):
    creator_id: Optional[int] = None
    character: Optional[str] = None
    group_id: Optional[int] = None
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
    part_name: Optional[str] = None
    sup_of_id: Optional[int] = None


class BulkTagUpdate(BaseModel):
    ids: list[int]
    add_tags: list[str] = []
    remove_tags: list[str] = []


class TagRenameBody(BaseModel):
    old_tag: str
    new_tag: str


class TagMergeBody(BaseModel):
    source_tag: str
    target_tag: str


class BulkExcludeUpdate(BaseModel):
    ids: list[int]
    excluded: bool


class BulkReviewUpdate(BaseModel):
    ids: list[int]
    needs_review: bool


class BulkEnrichUpdate(BaseModel):
    ids: list[int]
    creator_name: Optional[str] = None
    title: Optional[str] = None
    notes: Optional[str] = None
    source_url: Optional[str] = None
    source_site: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    ids: list[int]
    delete_files: bool = False


class BulkDeleteResponse(BaseModel):
    deleted: int
    folders_removed: int


class GroupMergeBody(BaseModel):
    """Merge models into one manual variant group (#617). Creates the group if
    group_id is omitted; otherwise extends the existing group."""
    model_ids: list[int]
    group_id: Optional[int] = None
    label: Optional[str] = None


class GroupSplitBody(BaseModel):
    """Remove members from a group (#617). They become ungrouped (variant_group_id
    = NULL). The remaining group is marked manual so a rescan won't undo the split."""
    model_ids: list[int]


class GroupPatchBody(BaseModel):
    label: Optional[str] = None
    rep_model_id: Optional[int] = None


class GroupingStrategyBody(BaseModel):
    """Set a per-subtree grouping strategy (#618). strategy ∈ {auto, off}; "auto"
    clears any override (restores the default proposal engine for the subtree)."""
    path: str
    strategy: str  # "auto" | "off"


class InboxScanRequest(BaseModel):
    path: str


class ScanRootCreate(BaseModel):
    path: str
    layout: str = "{creator}"
    name: Optional[str] = None
    is_writable: bool = False
    group_by_character: bool = False


class ScanRootUpdate(BaseModel):
    layout: Optional[str] = None
    enabled: Optional[bool] = None
    name: Optional[str] = None
    is_writable: Optional[bool] = None
    group_by_character: Optional[bool] = None


class LibraryRead(BaseModel):
    """A scan root usable as an import destination (#450)."""
    id: int
    path: str
    name: str
    is_writable: bool
    write_enabled: bool  # the reorganize_enabled app-setting feature flag

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


class ImportApplyStart(BaseModel):
    """Immediate response to POST /import/apply. ``started=False`` means there
    was nothing to move (no eligible files) — ``result`` is already final, no
    need to poll. ``started=True`` means a background job is now running;
    poll GET /import/apply/status for progress and the eventual result."""
    started: bool
    result: Optional[ImportApplyResponse] = None


class ImportApplyStatus(BaseModel):
    running: bool
    message: str
    moved_files: int = 0
    total_files: int = 0
    error: Optional[str] = None
    result: Optional[ImportApplyResponse] = None


class DownloadImagesResult(BaseModel):
    downloaded: int


class DownloadImagesStart(BaseModel):
    """Immediate response to POST /import/download-images. ``started=False``
    means there was nothing to download (``result`` already final, no need to
    poll). ``started=True`` means a background job is now running; poll
    GET /import/download-images/status for progress and the eventual result."""
    started: bool
    result: Optional[DownloadImagesResult] = None


class DownloadImagesStatus(BaseModel):
    running: bool
    message: str
    downloaded: int = 0
    total: int = 0
    error: Optional[str] = None
    result: Optional[DownloadImagesResult] = None


class DownloadZipRequest(BaseModel):
    file_ids: list[int] = Field(..., max_length=500)
    zip_name: str = "kit-build"

    class Config:
        from_attributes = True


class EnvReloadResult(BaseModel):
    """Outcome of re-reading the .env / environment config (#140). Carries only
    the live-effective values that are safe to show — never secrets."""
    ok: bool = True
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
    library_page_size: int = 50
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
    # Group model files by user-assigned category in the file list and 3D viewer.
    part_categories_enabled: bool = False
    # Show STL files as a full-width horizontal table below the two-column layout.
    horizontal_parts_layout: bool = True
    # Model detail image gallery display and auto-rotation.
    gallery_enabled: bool = True
    gallery_auto_rotate: bool = True
    gallery_rotation_seconds: int = 10
    # AI naming & organizing — uses an OpenAI-compatible endpoint (e.g. Ollama).
    # The API key is NOT here; it's encrypted via /settings/ai-organize/key.
    ai_organize_enabled: bool = False
    ai_organize_url: str = ""
    ai_organize_model: str = ""
    # Per-function AI API selection: ID of an AiApiConfig row (or None = unset).
    ai_guides_enabled: bool = False
    ai_guides_api: Optional[int] = None
    ai_organize_api: Optional[int] = None
    # Application log verbosity for the `app.*` loggers. Changing this in the UI
    # takes effect immediately (no restart) and persists across restarts.
    log_level: str = "INFO"
    # Library reorganize destination template ("" = the built-in default,
    # {creator}/{character}/{title}; optional {scale}) and whether every segment is rendered
    # lowercase/hyphenated (import-style) rather than case-preserving.
    reorganize_template: str = ""
    reorganize_slugify: bool = True
    # Independent of reorganize_slugify (directory segments only): also
    # renders each STL's own filename lowercase/hyphenated on reorganize and
    # import-apply. Off by default — renaming files on disk is a bigger step
    # than renaming directories, so this is opt-in.
    reorganize_slugify_filenames: bool = False
    # Feature flag: gates the Library reorganize feature end-to-end — the UI
    # (nav link, /reorganize route/page) AND the destructive apply/undo writes.
    # Default off; toggled from the Library settings tab. Retires the old
    # deployment-level REORGANIZE_WRITE_ENABLED env var.
    reorganize_enabled: bool = False
    # Preserve each release/package subtree while normalizing only the
    # creator/character prefix. Default off until explicitly enabled.
    reorganize_package_mode_enabled: bool = False
    # AI-assisted suggestions (STUDIO-186) for reorganize preview entries the
    # deterministic pass can't classify (unclassifiable/collision): infers
    # creator/character/title from folder name + filenames via the same
    # AiApiConfig as ai_organize_api. Advisory only — suggestions only prefill
    # the existing per-model override fields; the user must confirm before
    # they affect the manifest. Default off; toggled from the Library tab.
    reorganize_ai_suggestions_enabled: bool = False
    # Improve scanner-owned auto groups using the hierarchy-derived character
    # envelope. Manual groups and no_group decisions remain authoritative.
    hierarchy_variant_grouping_enabled: bool = False
    # Collections page: give every card the same box size (the one cover art
    # already uses) instead of a compact box for collections with no cover.
    collections_uniform_size: bool = True


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
    part_categories_enabled: Optional[bool] = None
    horizontal_parts_layout: Optional[bool] = None
    gallery_enabled: Optional[bool] = None
    gallery_auto_rotate: Optional[bool] = None
    gallery_rotation_seconds: Optional[int] = Field(None, ge=3, le=60)
    ai_organize_enabled: Optional[bool] = None
    ai_organize_url: Optional[str] = Field(None, max_length=500)
    ai_organize_model: Optional[str] = Field(None, max_length=200)
    ai_guides_enabled: Optional[bool] = None
    ai_guides_api: Optional[int] = None
    ai_organize_api: Optional[int] = None
    log_level: Optional[str] = Field(None, pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    reorganize_template: Optional[str] = Field(None, max_length=500)
    reorganize_slugify: Optional[bool] = None
    reorganize_slugify_filenames: Optional[bool] = None
    reorganize_enabled: Optional[bool] = None
    reorganize_package_mode_enabled: Optional[bool] = None
    reorganize_ai_suggestions_enabled: Optional[bool] = None
    hierarchy_variant_grouping_enabled: Optional[bool] = None
    collections_uniform_size: Optional[bool] = None

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


# --- Named AI API configs -------------------------------------------------

class AiApiConfigRead(BaseModel):
    """A named AI API endpoint configuration returned to the client.

    Encrypted keys are never returned — only whether one is set and a hint.
    """
    id: int
    name: str
    api_type: str
    url: Optional[str] = None
    model: str
    effort: Optional[str] = None
    # Per-connection request timeout (seconds). Default 10.
    request_timeout: int = 10
    # Max files per AI Organize LLM request/batch. None = service default.
    batch_size: Optional[int] = None
    # OpenAI-compatible only: let the model reason before answering. Off by
    # default — see AiApiConfig.reasoning_enabled.
    reasoning_enabled: bool = False
    key_set: bool
    key_hint: Optional[str] = None


class AiApiConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    api_type: str = Field(..., pattern="^(anthropic|openai)$")
    url: Optional[str] = Field(None, max_length=500)
    model: str = Field("", max_length=200)
    effort: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    request_timeout: int = Field(10, ge=1, le=600)
    batch_size: Optional[int] = Field(None, ge=1, le=50)
    reasoning_enabled: bool = False
    # Optional so a config can still be created key-less (e.g. Ollama), but lets
    # the client set the key in the same request instead of a follow-up call.
    api_key: Optional[str] = Field(None, max_length=400)


class AiApiConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    url: Optional[str] = Field(None, max_length=500)
    model: Optional[str] = Field(None, max_length=200)
    effort: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    request_timeout: Optional[int] = Field(None, ge=1, le=600)
    batch_size: Optional[int] = Field(None, ge=1, le=50)
    reasoning_enabled: Optional[bool] = None
    api_key: Optional[str] = Field(None, max_length=400)


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


class AiOrganizeSettingsRead(BaseModel):
    """Status of AI organize connection. Key is write-only."""
    key_set: bool
    key_hint: Optional[str] = None
    enabled: bool = False
    url: str = ""
    model: str = ""


class AiOrganizeRequest(BaseModel):
    """``strategy`` selects the grouping mode (#878): "parts" (default) suggests
    a physical part_type category (Head, Weapon, ...); "unit" suggests an
    in-game unit/character name instead (e.g. "Royal Guard 1"), written into
    the same part_type field but not constrained to the canonical category list.
    "link_sups" (#967) suggests sup_of_id links for currently-unlinked
    sup/supported/hollowed-named files — a pure heuristic, no AI API needed."""
    strategy: Literal["parts", "unit", "link_sups"] = "parts"


class AiOrganizeSuggestion(BaseModel):
    id: int
    part_type: Optional[str] = None
    part_name: Optional[str] = None
    sup_of_id: Optional[int] = None


class AiOrganizeResult(BaseModel):
    applied: list[AiOrganizeSuggestion]
    message: str = ""


class AiOrganizeSuggestionPreview(BaseModel):
    """Dry-run suggestion with enough context to populate the review modal."""
    id: int
    filename: str
    part_type: Optional[str] = None
    part_name: Optional[str] = None
    sup_of_id: Optional[int] = None
    sup_base_filename: Optional[str] = None


class AiOrganizePreviewResult(BaseModel):
    suggestions: list[AiOrganizeSuggestionPreview]
    # Outcome of the optional LLM pass so the UI can distinguish "AI ran" from
    # "AI failed / was skipped" instead of silently showing heuristics-only.
    # status: "ok" | "skipped" | "disabled" | "error". detail is set on error.
    llm_status: str = "disabled"
    llm_detail: Optional[str] = None


class AiOrganizeApplyItem(BaseModel):
    id: int
    part_type: Optional[str] = None
    part_name: Optional[str] = None
    sup_of_id: Optional[int] = None


class AiOrganizeApplyRequest(BaseModel):
    items: list[AiOrganizeApplyItem]


# --- Cults3D settings (#578) ----------------------------------------------

class CultsSettingsRead(BaseModel):
    """Cults3D credential status. Credentials are write-only."""
    credentials_set: bool
    hint: Optional[str] = None


# --- MyMiniFactory settings -----------------------------------------------

class MmfSettingsRead(BaseModel):
    """MyMiniFactory API key status. The key is write-only — never returned in
    full, only whether one is set and a masked hint (e.g. `…wxyz`)."""
    key_set: bool
    key_hint: Optional[str] = None


class CultsCredentialsUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=1, max_length=400)


# --- Cults3D search/creation responses -----------------------------------

class CultsCreatorRead(BaseModel):
    nick: str
    short_url: str
    bio: Optional[str] = None
    image_url: Optional[str] = None


class CultsCreationRead(BaseModel):
    name: str
    short_url: str
    illustration_image_url: Optional[str] = None
    license_name: Optional[str] = None
    license_code: Optional[str] = None
    category: Optional[str] = None
    published_at: Optional[str] = None
    views_count: Optional[int] = None
    likes_count: Optional[int] = None
    downloads_count: Optional[int] = None
    tags: list[str] = []
    price_amount: Optional[str] = None
    price_currency: Optional[str] = None
    creator: Optional[CultsCreatorRead] = None


class CultsSearchResponse(BaseModel):
    results: list[CultsCreationRead]


# --- Library reorganize, Phase 1 preview (#323) ---------------------------

FingerprintMethod = Literal["stat", "content_hash"]
MoveKind = Literal["move", "rename", "case_rename", "in_place", "merge"]
CollisionKind = Literal[
    "none", "exact", "case_only", "unicode_only", "same_destination"
]


class ReorganizeFileMove(BaseModel):
    stl_file_id: Optional[int] = None
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
    # "stl" repaths an STLFile row (stl_file_id set); "image" repaths one of
    # the model's own image_paths/thumbnail_path/primary_image_path instead.
    kind: str = "stl"


class ReorganizeEntry(BaseModel):
    model_id: int
    model_name: str
    creator_id: Optional[int] = None
    creator_name: str = ""
    model_ids: list[int] = Field(default_factory=list)
    package_mode: bool = False
    package_name: Optional[str] = None
    ambiguous_package: bool = False
    character_source_dir: Optional[str] = None
    character_proposed_dir: Optional[str] = None
    character_package_ids: list[int] = Field(default_factory=list)
    character_model_ids: list[int] = Field(default_factory=list)
    shared_files: list[ReorganizeFileMove] = Field(default_factory=list)
    source_path: str
    files: list[ReorganizeFileMove]   # the move unit is the file set
    kind: MoveKind
    proposed_dir: str
    eligible: bool

    # Path-keyed references this move invalidates (decision D); Phase 2 repaths.
    pack_override_paths: list[str]

    # Blockers / flags.
    collision: bool
    collision_kind: CollisionKind
    collision_with: list[int]
    suggested_suffix: Optional[str] = None
    unclassifiable: bool
    missing_fields: list[str]
    over_length: bool
    reserved_name: bool
    overlaps_other: bool
    spans_multiple_dirs: bool
    source_directories: list[str] = Field(default_factory=list)
    is_symlink: bool
    escapes_scan_root: bool
    missing_files_on_disk: bool = False
    locked: bool = False


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
    scale: Optional[str] = None
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


# --- Library reorganize, AI-assisted field suggestions (STUDIO-186) --------

class ReorganizeAiSuggestRequest(BaseModel):
    manifest_id: str
    model_ids: list[int]               # restrict to these manifest entries

    model_config = {"extra": "forbid"}


class ReorganizeAiSuggestion(BaseModel):
    """One model's inferred fields — a suggestion only. The caller must submit
    it via ReorganizePreviewRequest.overrides for it to affect anything."""
    model_id: int
    creator: Optional[str] = None
    character: Optional[str] = None
    title: Optional[str] = None


class ReorganizeAiSuggestResponse(BaseModel):
    suggestions: list[ReorganizeAiSuggestion]
    llm_status: str                    # ok | disabled | skipped | error
    llm_detail: Optional[str] = None

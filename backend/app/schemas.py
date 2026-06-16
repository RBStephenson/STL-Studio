from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


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
    nsfw: bool = False
    excluded: bool = False
    is_favorite: bool = False
    user_rating: Optional[int] = None
    queued_at: Optional[datetime] = None
    printed_at: Optional[datetime] = None
    print_status: str = "none"
    print_count: int = 0
    thumbnail_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    image_paths: list = []
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
    creator_name: Optional[str] = None


class ThumbnailUpdate(BaseModel):
    thumbnail_path: Optional[str] = None
    thumbnail_url: Optional[str] = None


class ThumbnailFromUrl(BaseModel):
    url: str


class FavoriteUpdate(BaseModel):
    is_favorite: bool


class RatingUpdate(BaseModel):
    # 1–5 sets the star rating; None clears it back to unrated (#167).
    rating: Optional[int] = Field(None, ge=1, le=5)


class QueueReorder(BaseModel):
    ids: list[int]   # queued model ids in the desired manual order


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


class SetGroupBody(BaseModel):
    character: Optional[str] = None  # None = explicitly ungroup; string = target group name


class ScanRootCreate(BaseModel):
    path: str
    layout: str = "{creator}"


class ScanRootUpdate(BaseModel):
    layout: Optional[str] = None
    enabled: Optional[bool] = None


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

    @field_validator("scan_ignore_patterns")
    @classmethod
    def _clean_patterns(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        cleaned = [p.strip() for p in v if p and p.strip()]
        if any(len(p) > 200 for p in cleaned):
            raise ValueError("ignore patterns must be 200 characters or fewer")
        # de-dupe, preserve order
        seen: set[str] = set()
        out: list[str] = []
        for p in cleaned:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    model_config = {"extra": "forbid"}

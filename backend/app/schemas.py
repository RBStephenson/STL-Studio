from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


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
    category: Optional[str] = None
    custom_attributes: dict = {}
    needs_review: bool = False
    nsfw: bool = False
    excluded: bool = False
    is_favorite: bool = False
    in_queue: bool = False
    queued_at: Optional[datetime] = None
    printed_at: Optional[datetime] = None
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


class QueueUpdate(BaseModel):
    in_queue: bool


class QueueReorder(BaseModel):
    ids: list[int]   # queued model ids in the desired manual order


class PrintedUpdate(BaseModel):
    printed: bool


class ExcludeUpdate(BaseModel):
    excluded: bool


class STLFileUpdate(BaseModel):
    part_type: Optional[str] = None


class BulkTagUpdate(BaseModel):
    ids: list[int]
    add_tags: list[str] = []
    remove_tags: list[str] = []


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


class AppSettingsUpdate(BaseModel):
    """Partial update for the app_settings store. extra="forbid" keeps the
    whitelist tight: unknown keys are a 422, never silently stored. None
    means "leave unchanged" — the router skips None values on write."""
    painting_guides_enabled: Optional[bool] = None
    show_nsfw: Optional[bool] = None
    library_page_size: Optional[int] = Field(None, ge=12, le=200)
    filter_presets: Optional[list[FilterPreset]] = None

    model_config = {"extra": "forbid"}

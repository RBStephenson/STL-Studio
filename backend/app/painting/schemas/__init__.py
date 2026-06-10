"""Pydantic contracts for the painting module.

Paint Shelf inventory schemas (M1, #240). The GuideDraft contract
(spec §6.5/Appendix A) lands with M2.

`matchable` is deliberately absent from the create/update schemas: it is
derived from `finish` (spec §8.6 — a flat hex is only honest for opaque
color paints), so the API computes it and clients can never set it.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Finish = Literal[
    "matte", "satin", "gloss", "metallic", "ink", "wash",
    "fluor", "primer", "medium", "pigment", "texture",
]

# Opaque color paints — the only finishes whose swatch hex is honest enough
# for hue matching (spec §8.6). Everything else is value-only or excluded.
MATCHABLE_FINISHES = {"matte", "satin", "gloss"}

HEX_PATTERN = r"^#[0-9a-fA-F]{6}$"


def derive_matchable(finish: str) -> bool:
    return finish in MATCHABLE_FINISHES


# ---------------------------------------------------------------------------
# Brands & lines
# ---------------------------------------------------------------------------

class BrandCreate(BaseModel):
    name: str = Field(min_length=1)

    model_config = {"extra": "forbid"}


class PaintLineRead(BaseModel):
    id: int
    brand_id: int
    name: str
    code_pattern: Optional[str] = None

    model_config = {"from_attributes": True}


class BrandRead(BaseModel):
    id: int
    name: str
    lines: list[PaintLineRead] = []

    model_config = {"from_attributes": True}


class PaintLineCreate(BaseModel):
    brand_id: int
    name: str = Field(min_length=1)
    code_pattern: Optional[str] = None

    model_config = {"extra": "forbid"}


class PaintLineUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    code_pattern: Optional[str] = None

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Paints
# ---------------------------------------------------------------------------

class PaintCreate(BaseModel):
    paint_line_id: int
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    hex: Optional[str] = Field(None, pattern=HEX_PATTERN)
    value_pct: Optional[int] = Field(None, ge=0, le=100)
    finish: Finish
    owned: bool = True
    handling_flags: list[str] = []
    substitute_for: list[int] = []
    notes: Optional[str] = None
    source: Optional[str] = None

    model_config = {"extra": "forbid"}


class PaintUpdate(BaseModel):
    """Partial update; None = leave unchanged. `finish` changes re-derive
    `matchable` server-side."""
    paint_line_id: Optional[int] = None
    code: Optional[str] = Field(None, min_length=1)
    name: Optional[str] = Field(None, min_length=1)
    hex: Optional[str] = Field(None, pattern=HEX_PATTERN)
    value_pct: Optional[int] = Field(None, ge=0, le=100)
    finish: Optional[Finish] = None
    owned: Optional[bool] = None
    handling_flags: Optional[list[str]] = None
    substitute_for: Optional[list[int]] = None
    notes: Optional[str] = None
    source: Optional[str] = None

    model_config = {"extra": "forbid"}


class PaintRead(BaseModel):
    id: int
    paint_line_id: int
    code: str
    name: str
    hex: Optional[str] = None
    value_pct: Optional[int] = None
    finish: str
    matchable: bool
    owned: bool
    handling_flags: list[str] = []
    substitute_for: list[int] = []
    notes: Optional[str] = None
    source: Optional[str] = None

    model_config = {"from_attributes": True}


class PaintList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[PaintRead]

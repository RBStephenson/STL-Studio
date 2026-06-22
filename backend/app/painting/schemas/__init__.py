"""Pydantic contracts for the painting module.

Paint Shelf inventory schemas (M1, #240). The GuideDraft contract
(spec §6.5/Appendix A) lands with M2.

`matchable` is deliberately absent from the create/update schemas: it is
derived from `finish` (spec §8.6 — a flat hex is only honest for opaque
color paints), so the API computes it and clients can never set it.
"""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

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
    size: Optional[str] = None
    count: int = Field(1, ge=0)

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
    size: Optional[str] = None
    count: Optional[int] = Field(None, ge=0)

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
    size: Optional[str] = None
    count: int = 1

    model_config = {"from_attributes": True}


class PaintList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[PaintRead]


# ===========================================================================
# Guides (M2, #258)
#
# The Tab -> Phase -> Step -> Swatch/MixComponent spine is relational (the
# validator walks every swatch; the editor swaps paints in place). The
# fixed-shape display furniture (character_brief, theme, value_map,
# skin_config, metals_config, thinning_config) rides along as JSON blocks on
# its owning row (spec §6.1/§6.4).
#
# Block-embedded "display steps" (inside skin/metals methods) are kept as
# opaque dicts so they round-trip losslessly — the *relational* spine is the
# validated path, and the full paint-id/value validator is M3 (spec §8.4).
# ===========================================================================

GuideScale = Literal["1:6", "1:12", "75mm", "28mm", "bust", "other"]
GuideStatus = Literal["draft", "in_review", "published", "archived"]
StepTechnique = Literal["airbrush", "brush", "wash", "finish", "effects", "filter"]


# --- JSON display blocks (spec §6.4) ---------------------------------------

class CharacterBrief(BaseModel):
    philosophy: str = ""
    light_source: str = ""
    priority_materials: list[str] = []

    model_config = {"extra": "forbid"}


class PaintPill(BaseModel):
    """One chip in the paint-bar (.paint-pill + .pill-dot color)."""
    name: str
    color: Optional[str] = None

    model_config = {"extra": "forbid"}


class GuideTheme(BaseModel):
    """Per-guide :root vars + hero gradient, injected as inline custom props.
    All optional — a partial theme falls back to the app defaults in guide.css."""
    bg: Optional[str] = None
    surface: Optional[str] = None
    surface2: Optional[str] = None
    surface3: Optional[str] = None
    border: Optional[str] = None
    text: Optional[str] = None
    text_muted: Optional[str] = None
    text_dim: Optional[str] = None
    accent: Optional[str] = None
    hero_gradient: Optional[str] = None

    model_config = {"extra": "forbid"}


class ValueChip(BaseModel):
    hex: str = Field(pattern=HEX_PATTERN)
    value_pct: int = Field(ge=0, le=100)
    zone_label: str

    model_config = {"extra": "forbid"}


class ValueMap(BaseModel):
    label: Optional[str] = None          # the .phase-label above the map (may vary per material)
    chips: list[ValueChip] = []

    model_config = {"extra": "forbid"}


class TabSection(BaseModel):
    """.section-header at the top of a tab — heading differs from the tab name."""
    heading: str = ""
    intro: Optional[str] = None          # may carry inline HTML

    model_config = {"extra": "forbid"}


class TabCallout(BaseModel):
    """A tab-level prose node directly under .tab-content (outside any step):
    an intro paragraph (text) or a tip/warning callout (#271). `html` is inner
    HTML, preserved verbatim like step tips."""
    kind: Literal["tip", "warning", "text"]
    html: str

    model_config = {"extra": "forbid"}


class RawBlock(BaseModel):
    """An unmodelled tab-level block captured verbatim so it round-trips without
    a dedicated schema — e.g. wargaming batch-stage / tier-card / trouble-grid /
    resin-callout (#271). `html` is the block's outer HTML, preserved as-is."""
    css_class: str
    html: str

    model_config = {"extra": "forbid"}


class SubTabDef(BaseModel):
    """One sub-tab (e.g. 'Pro Acryl' vs 'Expert Acrylics'); phases with a
    matching subtab_key render inside its .sub-content."""
    key: str                             # dom suffix: id = f"{tab.dom_id}-{key}"
    label: str                           # button text (may include a ✦ marker)
    css_class: Optional[str] = None      # extra class, e.g. "expert-tab" / "folk-art-tab"
    sort_order: int = 0
    # tip/warning/intro-<p> nested in this subtab's .sub-content (#271 residual).
    callouts: list[TabCallout] = []

    model_config = {"extra": "forbid"}


class MethodCard(BaseModel):
    title: str
    body: Optional[str] = None
    pros: Optional[str] = None           # .mc-pros
    cons: Optional[str] = None           # .mc-cons
    best: Optional[str] = None           # .mc-best
    recommended: bool = False
    badge: Optional[str] = None          # .method-card-badge text ("★ Recommended")

    model_config = {"extra": "forbid"}


class MethodBlock(BaseModel):
    """The Skin tab's 'Method Selection' furniture (spec §9.6 .method-* )."""
    recommendation: Optional[str] = None  # .method-rec-block (inline HTML)
    cards: list[MethodCard] = []
    freckle_note: Optional[str] = None    # .freckle-note (inline HTML)

    model_config = {"extra": "forbid"}


class SkinMethod(BaseModel):
    key: str
    title: str
    recommended: bool = False
    steps: list[dict[str, Any]] = []   # display steps — opaque, see module note

    model_config = {"extra": "forbid"}


class SkinConfig(BaseModel):
    recommended: Optional[str] = None          # "basic" | "pinkle" | "wash_tinting"
    anchor_paint_id: Optional[int] = None
    complexion_band: Optional[str] = None
    freckling_note: Optional[str] = None
    methods: list[SkinMethod] = []

    model_config = {"extra": "forbid"}


class MetalsApproach(BaseModel):
    approach: Optional[str] = None             # "gloss_black_1to6" | "standard_small"
    steps: list[dict[str, Any]] = []

    model_config = {"extra": "forbid"}


class MetalsConfig(BaseModel):
    tmm: Optional[MetalsApproach] = None
    nmm: Optional[MetalsApproach] = None       # present only when an NMM sub-tab is added

    model_config = {"extra": "forbid"}


class ThinningAirbrushRow(BaseModel):
    technique: str
    nozzle: Optional[str] = None
    ratio: str
    behavior: Optional[str] = None

    model_config = {"extra": "forbid"}


class ThinningBrushRow(BaseModel):
    technique: str
    ratio: str
    behavior: Optional[str] = None

    model_config = {"extra": "forbid"}


class ThinningCard(BaseModel):
    title: str
    body: str

    model_config = {"extra": "forbid"}


class ThinningConfig(BaseModel):
    airbrush_rows: list[ThinningAirbrushRow] = []
    brush_rows: list[ThinningBrushRow] = []
    thinning_cards: list[ThinningCard] = []

    model_config = {"extra": "forbid"}


class CreatorCredit(BaseModel):
    name: Optional[str] = None           # studio/sculptor (bolded in .creator-credit)
    url: Optional[str] = None
    link_text: Optional[str] = None      # anchor text ("@handle", "Studio — Patreon")

    model_config = {"extra": "forbid"}


# --- Relational spine: Swatch / MixComponent / Step / Phase / Tab ----------

class PaintSummary(BaseModel):
    """Resolved paint display data embedded in swatch/mix reads so the React
    reader (#259) can draw swatch dots/names — the relational spine itself
    stores only paint_id. Populated transiently by the guide endpoints."""
    name: str
    code: str
    brand: str
    hex: Optional[str] = None

    model_config = {"from_attributes": True}


class SwatchIn(BaseModel):
    # paint_id is optional (#477): a swatch that doesn't resolve to a shelf paint
    # is kept by `name` so it round-trips. One of the two is required.
    paint_id: Optional[int] = None
    name: Optional[str] = None
    value_pct: Optional[int] = Field(None, ge=0, le=100)
    role_label: Optional[str] = None
    sort_order: int = 0

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _require_paint_or_name(self):
        if self.paint_id is None and not (self.name and self.name.strip()):
            raise ValueError("a swatch needs a paint_id or a name")
        return self


class SwatchRead(SwatchIn):
    id: int
    paint: Optional[PaintSummary] = None

    model_config = {"from_attributes": True}


class MixComponentIn(BaseModel):
    # paint_id is optional (#425): a component that doesn't resolve to a shelf
    # paint is kept by `name` so the mix still round-trips. One of the two required.
    paint_id: Optional[int] = None
    name: Optional[str] = None
    parts: float = Field(gt=0)
    sort_order: int = 0

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _require_paint_or_name(self):
        if self.paint_id is None and not (self.name and self.name.strip()):
            raise ValueError("a mix component needs a paint_id or a name")
        return self


class MixComponentRead(MixComponentIn):
    id: int
    paint: Optional[PaintSummary] = None

    model_config = {"from_attributes": True}


class StepIn(BaseModel):
    title: str = Field(min_length=1)
    technique_tag: Optional[StepTechnique] = None
    technique_label: Optional[str] = None
    body: Optional[str] = None
    value_intent: Optional[str] = None
    tip: Optional[str] = None
    warning: Optional[str] = None
    ratio_box: Optional[str] = None
    sort_order: int = 0
    swatches: list[SwatchIn] = []
    mix_components: list[MixComponentIn] = []

    model_config = {"extra": "forbid"}


class StepRead(BaseModel):
    id: int
    title: str
    technique_tag: Optional[str] = None
    technique_label: Optional[str] = None
    body: Optional[str] = None
    value_intent: Optional[str] = None
    tip: Optional[str] = None
    warning: Optional[str] = None
    ratio_box: Optional[str] = None
    sort_order: int = 0
    swatches: list[SwatchRead] = []
    mix_components: list[MixComponentRead] = []

    model_config = {"from_attributes": True}


class PhaseIn(BaseModel):
    # May be empty: a run of steps with no .phase-label divider is a legitimate
    # unlabeled phase (the importer produces these). Renderers skip the divider
    # when blank.
    label: str = ""
    subtab_key: Optional[str] = None
    sort_order: int = 0
    steps: list[StepIn] = []

    model_config = {"extra": "forbid"}


class PhaseRead(BaseModel):
    id: int
    label: str
    subtab_key: Optional[str] = None
    sort_order: int = 0
    steps: list[StepRead] = []

    model_config = {"from_attributes": True}


class TabIn(BaseModel):
    name: str = Field(min_length=1)
    dom_id: Optional[str] = None
    sort_order: int = 0
    has_expert_subtab: bool = False
    section: Optional[TabSection] = None
    value_map: Optional[ValueMap] = None
    subtabs: list[SubTabDef] = []
    callouts: list[TabCallout] = []
    raw_blocks: list[RawBlock] = []
    method_block: Optional[MethodBlock] = None
    skin_config: Optional[SkinConfig] = None
    metals_config: Optional[MetalsConfig] = None
    phases: list[PhaseIn] = []

    model_config = {"extra": "forbid"}


class TabRead(BaseModel):
    id: int
    name: str
    dom_id: Optional[str] = None
    sort_order: int = 0
    has_expert_subtab: bool = False
    section: Optional[TabSection] = None
    value_map: Optional[ValueMap] = None
    subtabs: list[SubTabDef] = []
    callouts: list[TabCallout] = []
    raw_blocks: list[RawBlock] = []
    method_block: Optional[MethodBlock] = None
    skin_config: Optional[SkinConfig] = None
    metals_config: Optional[MetalsConfig] = None
    phases: list[PhaseRead] = []

    model_config = {"from_attributes": True}


# --- Guide header / create / update / read ---------------------------------

class SeriesBadgeChip(BaseModel):
    """One chip in the hero .series-badge (#271). The active chip is the current
    guide (no filename); sibling chips carry the legacy filename they link to."""
    label: str
    filename: Optional[str] = None
    active: bool = False

    model_config = {"extra": "forbid"}


class GuideCreate(BaseModel):
    slug: str = Field(min_length=1)
    title: str = Field(min_length=1)
    title_lead: Optional[str] = None
    subtitle: Optional[str] = None
    category_id: Optional[int] = None
    category_label: Optional[str] = None
    series_id: Optional[int] = None
    model_id: Optional[int] = None
    scale: Optional[GuideScale] = None
    status: GuideStatus = "draft"
    franchise: Optional[str] = None
    quote: Optional[str] = None
    creator_credit: Optional[CreatorCredit] = None
    reference_image_id: Optional[int] = None
    light_source: Optional[str] = None
    philosophy_note: Optional[str] = None
    paint_lines_used: list[PaintPill] = []
    technique_tags: list[str] = []
    character_brief: Optional[CharacterBrief] = None
    theme: Optional[GuideTheme] = None
    head_style: Optional[str] = None
    series_badge: Optional[list[SeriesBadgeChip]] = None
    thinning_config: Optional[ThinningConfig] = None
    tabs: list[TabIn] = []

    model_config = {"extra": "forbid"}


class GuideDraft(GuideCreate):
    """A generated/imported guide before it's persisted (#523, M4 §8.3).

    Same shape as `GuideCreate`, with two relaxations for the draft stage:
    - `slug` is optional — a generator focuses on content; the slug is derived
      from the title when the draft is saved.
    - swatch / mix-component paints may be referenced by `name` only; the real
      Paint Shelf `paint_id`s are filled in by
      `services.draft.reconcile_draft_paints` (the `*In` schemas already allow a
      name-only paint, so no field changes are needed for that).

    A draft is always status="draft" — generation never auto-publishes.
    """
    slug: Optional[str] = None
    status: GuideStatus = "draft"

    model_config = {"extra": "forbid"}


class GuideUpdate(BaseModel):
    """Partial update. Scalar/JSON fields use exclude_unset (omitted = unchanged).
    If `tabs` is provided, the entire tab subtree is REPLACED (the natural save
    shape for the structured editor); omit it to leave the content spine alone."""
    slug: Optional[str] = Field(None, min_length=1)
    title: Optional[str] = Field(None, min_length=1)
    title_lead: Optional[str] = None
    subtitle: Optional[str] = None
    category_id: Optional[int] = None
    category_label: Optional[str] = None
    series_id: Optional[int] = None
    model_id: Optional[int] = None
    scale: Optional[GuideScale] = None
    status: Optional[GuideStatus] = None
    franchise: Optional[str] = None
    quote: Optional[str] = None
    creator_credit: Optional[CreatorCredit] = None
    reference_image_id: Optional[int] = None
    light_source: Optional[str] = None
    philosophy_note: Optional[str] = None
    paint_lines_used: Optional[list[PaintPill]] = None
    technique_tags: Optional[list[str]] = None
    character_brief: Optional[CharacterBrief] = None
    theme: Optional[GuideTheme] = None
    head_style: Optional[str] = None
    series_badge: Optional[list[SeriesBadgeChip]] = None
    thinning_config: Optional[ThinningConfig] = None
    tabs: Optional[list[TabIn]] = None

    model_config = {"extra": "forbid"}


class GuideRead(BaseModel):
    id: int
    slug: str
    title: str
    title_lead: Optional[str] = None
    subtitle: Optional[str] = None
    category_id: Optional[int] = None
    category_label: Optional[str] = None
    series_id: Optional[int] = None
    model_id: Optional[int] = None
    scale: Optional[str] = None
    status: str
    franchise: Optional[str] = None
    quote: Optional[str] = None
    creator_credit: Optional[CreatorCredit] = None
    reference_image_id: Optional[int] = None
    light_source: Optional[str] = None
    philosophy_note: Optional[str] = None
    paint_lines_used: list[PaintPill] = []
    technique_tags: list[str] = []
    character_brief: Optional[CharacterBrief] = None
    theme: Optional[GuideTheme] = None
    head_style: Optional[str] = None
    series_badge: Optional[list[SeriesBadgeChip]] = None
    thinning_config: Optional[ThinningConfig] = None
    tabs: list[TabRead] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class GuideListItem(BaseModel):
    """Lightweight card for the guide grid — no content spine."""
    id: int
    slug: str
    title: str
    category_id: Optional[int] = None
    series_id: Optional[int] = None
    model_id: Optional[int] = None
    scale: Optional[str] = None
    status: str
    franchise: Optional[str] = None
    technique_tags: list[str] = []
    paint_lines_used: list[PaintPill] = []
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class GuideList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[GuideListItem]


class PaintOverride(BaseModel):
    """A user decision mapping an unresolved swatch/mix paint to a shelf paint
    (#417). `name`/`brand` echo the report's unresolved entry; the resolver keys
    on the canonicalized name so the override wins before catalog matching."""
    name: str = Field(min_length=1)
    brand: Optional[str] = None
    paint_id: int

    model_config = {"extra": "forbid"}


class GuideImportRequest(BaseModel):
    html: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    # Parse + report only, don't persist — lets the UI resolve unresolved paints
    # before committing (#417).
    dry_run: bool = False
    # User-supplied resolutions for paints that wouldn't otherwise match (#417).
    paint_overrides: list[PaintOverride] = []

    model_config = {"extra": "forbid"}


class GuideImportResult(BaseModel):
    # None on a dry_run preview — nothing is persisted (#417).
    guide: Optional[GuideRead] = None
    report: dict


class ForcedPaintCreate(BaseModel):
    """Force-add a paint that isn't on the shelf during guide import (#417):
    lands in a synthetic 'Imported / Uncategorized' line as known-but-not-owned,
    so the swatch can reference it. The user can re-file it later."""
    name: str = Field(min_length=1)
    hex: Optional[str] = Field(None, pattern=HEX_PATTERN)

    model_config = {"extra": "forbid"}


# --- Categories & series ---------------------------------------------------

class CategoryCreate(BaseModel):
    slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    sort_order: int = 0
    description: Optional[str] = None

    model_config = {"extra": "forbid"}


class CategoryRead(BaseModel):
    id: int
    slug: str
    display_name: str
    sort_order: int = 0
    description: Optional[str] = None
    guide_count: int = 0

    model_config = {"from_attributes": True}


class SeriesCreate(BaseModel):
    slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)

    model_config = {"extra": "forbid"}


class SeriesRead(BaseModel):
    id: int
    slug: str
    display_name: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Guide validation (#489, spec §8.4)
# ---------------------------------------------------------------------------

class ValidationFlag(BaseModel):
    """One validator finding. `block` flags prevent publish; `warn` is advisory.

    The index locator (tab/phase/step/swatch) lets the editor jump to the node;
    `path` is a human breadcrumb for display."""
    severity: Literal["block", "warn"]
    code: str
    message: str
    tab_index: Optional[int] = None
    phase_index: Optional[int] = None
    step_index: Optional[int] = None
    swatch_index: Optional[int] = None
    path: Optional[str] = None


class GuideValidationResult(BaseModel):
    ok: bool                       # True when no block-severity flags remain
    flags: list[ValidationFlag]

"""SQLAlchemy ORM for the painting module (spec §6.2/§6.4).

Tables are namespaced paint_* / guide_* and live in the host app's SQLite DB
(same Base/engine), so they ride along in backup/restore automatically. The
only cross-module relation is guides.model_id -> models.id (nullable).

Conventions match the host app: Integer PKs, String for enum-ish fields,
JSON for list/dict columns, utcnow timestamps.
"""
from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, Boolean,
    ForeignKey, JSON,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import utcnow


# ---------------------------------------------------------------------------
# Paint inventory ("Paint Shelf")
# ---------------------------------------------------------------------------

class PaintBrand(Base):
    __tablename__ = "paint_brands"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)  # Monument Hobbies, Vallejo, …

    lines = relationship("PaintLine", back_populates="brand")


class PaintLine(Base):
    __tablename__ = "paint_lines"

    id = Column(Integer, primary_key=True)
    brand_id = Column(Integer, ForeignKey("paint_brands.id"), nullable=False)
    name = Column(String, nullable=False)          # Pro Acryl Standard, Speedpaint 2.0, …
    code_pattern = Column(String, nullable=True)   # validation regex, e.g. ^MPA-\d{3}$

    brand = relationship("PaintBrand", back_populates="lines")
    paints = relationship("Paint", back_populates="line")


class Paint(Base):
    """The inventory atom — one physical paint."""
    __tablename__ = "paints"

    id = Column(Integer, primary_key=True)
    paint_line_id = Column(Integer, ForeignKey("paint_lines.id"), nullable=False)
    code = Column(String, nullable=False)          # "002", "S18", "77.702"
    name = Column(String, nullable=False)          # "Coal Black"
    hex = Column(String(7), nullable=True)         # "#2A2A2A" approximate swatch color
    value_pct = Column(Integer, nullable=True)     # 0..100 approximate L*-derived value
    # matte|satin|gloss|metallic|ink|wash|fluor|primer|medium|pigment|texture
    finish = Column(String, nullable=False)
    matchable = Column(Boolean, default=False)     # derived from finish (spec §8.6)
    owned = Column(Boolean, default=True)          # false = known-but-not-owned
    handling_flags = Column(JSON, default=list)    # ["enamel", …]
    substitute_for = Column(JSON, default=list)    # paint ids this can sub for
    notes = Column(Text, nullable=True)
    source = Column(String, nullable=True)         # "PaintRack 2026-05-29" | "manual"
    # PaintRack passthrough fields — preserved verbatim so CSV export
    # round-trips losslessly (#242/#243).
    size = Column(String, nullable=True)           # "18 ml", "17|18 ml", "1 oz"
    count = Column(Integer, default=1)             # bottles owned

    line = relationship("PaintLine", back_populates="paints")


# ---------------------------------------------------------------------------
# Guide organization
# ---------------------------------------------------------------------------

class GuideCategory(Base):
    __tablename__ = "guide_categories"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)   # "film-tv"
    display_name = Column(String, nullable=False)
    sort_order = Column(Integer, default=0)
    description = Column(Text, nullable=True)


class GuideSeries(Base):
    __tablename__ = "guide_series"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)   # "batman-1966"
    display_name = Column(String, nullable=False)


class Guide(Base):
    __tablename__ = "guides"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)   # "robocop-1987"
    title = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey("guide_categories.id"), nullable=True)
    series_id = Column(Integer, ForeignKey("guide_series.id"), nullable=True)
    # The one cross-module FK: the STL model this figure was printed from.
    model_id = Column(Integer, ForeignKey("models.id"), nullable=True, index=True)

    scale = Column(String, nullable=True)            # 1:6|1:12|75mm|28mm|bust|other
    status = Column(String, nullable=False, default="draft")  # draft|in_review|published|archived
    franchise = Column(String, nullable=True)
    creator_credit = Column(JSON, default=dict)      # {name, url} — sculptor, not the author
    # Real FK lives here; guide_reference_images.guide_id stays a plain int to
    # avoid a circular FK pair (resolved in code).
    reference_image_id = Column(Integer, ForeignKey("guide_reference_images.id"), nullable=True)
    light_source = Column(String, nullable=True)     # temperature/direction note
    philosophy_note = Column(Text, nullable=True)    # value-first brief
    paint_lines_used = Column(JSON, default=list)    # denormalized for paint bar + filtering
    technique_tags = Column(JSON, default=list)      # ["OSL","NMM","TMM",…]

    # JSON display blocks (spec §6.4)
    character_brief = Column(JSON, nullable=True)    # {philosophy, light_source, priority_materials}
    theme = Column(JSON, nullable=True)              # :root vars + hero gradient
    thinning_config = Column(JSON, nullable=True)    # GUIDE_THINNING analog

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    published_at = Column(DateTime, nullable=True)

    tabs = relationship("GuideTab", back_populates="guide", order_by="GuideTab.sort_order")


# ---------------------------------------------------------------------------
# Guide content spine: Tab -> Phase -> Step -> Swatch / MixComponent
# ---------------------------------------------------------------------------

class GuideTab(Base):
    __tablename__ = "guide_tabs"

    id = Column(Integer, primary_key=True)
    guide_id = Column(Integer, ForeignKey("guides.id"), nullable=False, index=True)
    name = Column(String, nullable=False)            # "Skin", "Armor", "Metals", …
    sort_order = Column(Integer, default=0)
    has_expert_subtab = Column(Boolean, default=False)

    # JSON display blocks owned by a tab (spec §6.4)
    value_map = Column(JSON, nullable=True)          # 5-chip greyscale ladder
    skin_config = Column(JSON, nullable=True)        # 3 method cards (Skin tab)
    metals_config = Column(JSON, nullable=True)      # TMM + optional NMM (Metals tab)

    guide = relationship("Guide", back_populates="tabs")
    phases = relationship("GuidePhase", back_populates="tab", order_by="GuidePhase.sort_order")


class GuidePhase(Base):
    __tablename__ = "guide_phases"

    id = Column(Integer, primary_key=True)
    tab_id = Column(Integer, ForeignKey("guide_tabs.id"), nullable=False, index=True)
    label = Column(String, nullable=False)           # "Zenithal Sequence" (.phase-label)
    sort_order = Column(Integer, default=0)

    tab = relationship("GuideTab", back_populates="phases")
    steps = relationship("GuideStep", back_populates="phase", order_by="GuideStep.sort_order")


class GuideStep(Base):
    __tablename__ = "guide_steps"

    id = Column(Integer, primary_key=True)
    phase_id = Column(Integer, ForeignKey("guide_phases.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    # airbrush|brush|wash|finish|effects|filter — the colored pill
    technique_tag = Column(String, nullable=True)
    body = Column(Text, nullable=True)               # instructions incl. value intent
    value_intent = Column(String, nullable=True)     # 'should read ~85% value'
    tip = Column(Text, nullable=True)                # .tip green callout
    warning = Column(Text, nullable=True)            # .warning red callout
    ratio_box = Column(String, nullable=True)        # "4:1 Bold Pyrrole Red 003 to Orange 007"
    sort_order = Column(Integer, default=0)

    phase = relationship("GuidePhase", back_populates="steps")
    swatches = relationship("GuideSwatch", back_populates="step", order_by="GuideSwatch.sort_order")
    mix_components = relationship(
        "GuideMixComponent", back_populates="step", order_by="GuideMixComponent.sort_order"
    )


class GuideSwatch(Base):
    """A paint reference inside a step — must resolve to an owned paint."""
    __tablename__ = "guide_swatches"

    id = Column(Integer, primary_key=True)
    step_id = Column(Integer, ForeignKey("guide_steps.id"), nullable=False, index=True)
    paint_id = Column(Integer, ForeignKey("paints.id"), nullable=False)
    value_pct = Column(Integer, nullable=True)       # role value at this usage
    role_label = Column(String, nullable=True)       # "mid-tone base", "final specular"
    sort_order = Column(Integer, default=0)

    step = relationship("GuideStep", back_populates="swatches")


class GuideMixComponent(Base):
    """One paint in a multi-paint mix; the ratio string is derived from parts."""
    __tablename__ = "guide_mix_components"

    id = Column(Integer, primary_key=True)
    step_id = Column(Integer, ForeignKey("guide_steps.id"), nullable=False, index=True)
    paint_id = Column(Integer, ForeignKey("paints.id"), nullable=False)
    parts = Column(Float, nullable=False)
    sort_order = Column(Integer, default=0)

    step = relationship("GuideStep", back_populates="mix_components")


# ---------------------------------------------------------------------------
# Reference images & color matching
# ---------------------------------------------------------------------------

class GuideReferenceImage(Base):
    __tablename__ = "guide_reference_images"

    id = Column(Integer, primary_key=True)
    # Plain int (not FK) to avoid a circular FK with guides.reference_image_id.
    guide_id = Column(Integer, nullable=True, index=True)
    storage_key = Column(String, nullable=False)     # local image path (shared volume)
    # stl_model_folder|artist_render|web_research|ai_generated|user_upload
    provenance = Column(String, nullable=False)
    source_url = Column(String, nullable=True)       # attribution
    alt_text = Column(String, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class GuideColorMatchSession(Base):
    __tablename__ = "guide_color_match_sessions"

    id = Column(Integer, primary_key=True)
    guide_id = Column(Integer, ForeignKey("guides.id"), nullable=True, index=True)
    reference_image_id = Column(Integer, ForeignKey("guide_reference_images.id"), nullable=True)
    samples = Column(JSON, default=list)             # [{region, lab, value, candidate_paint_ids[]}]
    created_at = Column(DateTime, default=utcnow)

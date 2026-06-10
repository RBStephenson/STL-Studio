"""
M0 smoke tests for the painting module: tables created via the host schema
mechanism, the router wired into the app, and the cross-module model FK.
"""
from sqlalchemy import inspect

from tests.conftest import make_creator, make_model

PAINTING_TABLES = {
    "paint_brands",
    "paint_lines",
    "paints",
    "guide_categories",
    "guide_series",
    "guides",
    "guide_tabs",
    "guide_phases",
    "guide_steps",
    "guide_swatches",
    "guide_mix_components",
    "guide_reference_images",
    "guide_color_match_sessions",
}


class TestTables:
    def test_all_painting_tables_created(self, test_engine):
        """Base.metadata.create_all must produce every painting table (#179)."""
        existing = set(inspect(test_engine).get_table_names())
        missing = PAINTING_TABLES - existing
        assert not missing, f"painting tables missing from DB init: {sorted(missing)}"

    def test_host_tables_untouched(self, test_engine):
        """The module is additive — existing tables still present."""
        existing = set(inspect(test_engine).get_table_names())
        assert {"models", "creators", "stl_files", "collections"} <= existing

    def test_guide_model_fk_round_trip(self, db):
        """The one cross-module relation: guides.model_id -> models.id."""
        from app.painting.models import Guide

        creator = make_creator(db)
        model = make_model(db, creator)
        db.add(Guide(slug="robocop-1987", title="RoboCop", model_id=model.id))
        db.commit()

        saved = db.query(Guide).filter(Guide.slug == "robocop-1987").one()
        assert saved.model_id == model.id
        assert saved.status == "draft"

    def test_guide_content_spine(self, db):
        """Tab -> Phase -> Step -> Swatch relational spine holds together."""
        from app.painting.models import (
            Guide, GuideTab, GuidePhase, GuideStep, GuideSwatch,
            Paint, PaintBrand, PaintLine,
        )

        brand = PaintBrand(name="Monument Hobbies")
        db.add(brand)
        db.flush()
        line = PaintLine(brand_id=brand.id, name="Pro Acryl Standard", code_pattern=r"^\d{3}$")
        db.add(line)
        db.flush()
        paint = Paint(paint_line_id=line.id, code="002", name="Coal Black",
                      hex="#2A2A2A", finish="matte", matchable=True, owned=True)
        guide = Guide(slug="test-figure", title="Test Figure")
        db.add_all([paint, guide])
        db.flush()

        tab = GuideTab(guide_id=guide.id, name="Skin", sort_order=0)
        db.add(tab)
        db.flush()
        phase = GuidePhase(tab_id=tab.id, label="Zenithal Sequence", sort_order=0)
        db.add(phase)
        db.flush()
        step = GuideStep(phase_id=phase.id, title="Black primer", technique_tag="airbrush")
        db.add(step)
        db.flush()
        db.add(GuideSwatch(step_id=step.id, paint_id=paint.id, role_label="shadow base"))
        db.commit()

        loaded = db.query(Guide).filter(Guide.slug == "test-figure").one()
        assert loaded.tabs[0].phases[0].steps[0].swatches[0].paint_id == paint.id


class TestRouter:
    def test_health_returns_200(self, client):
        resp = client.get("/painting/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_guides_stub_returns_501(self, client):
        assert client.get("/painting/guides").status_code == 501
        assert client.post("/painting/guides").status_code == 501

    def test_paints_endpoints_live(self, client):
        """The Paint Shelf stubs were replaced by real endpoints in M1 (#240) —
        full coverage lives in test_painting_inventory.py."""
        resp = client.get("/painting/paints")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

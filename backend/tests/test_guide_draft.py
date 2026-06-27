"""GuideDraft contract + paint reconciliation (#523, M4 §8.3)."""
from app.painting.schemas import GuideDraft
from app.painting.services.draft import reconcile_draft_paints

from tests.test_painting_guides import mk_paint


def _shelf_paint(client, name="Coal Black", code="002"):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    line = client.post(
        "/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}
    ).json()
    return mk_paint(client, line["id"], code=code, name=name)


def _draft_with_swatches(swatches, mix_components=None):
    return GuideDraft.model_validate({
        "title": "Presto",
        "tabs": [{
            "name": "Skin",
            "phases": [{
                "label": "Base",
                "steps": [{
                    "title": "Basecoat",
                    "swatches": swatches,
                    "mix_components": mix_components or [],
                }],
            }],
        }],
    })


def test_draft_allows_missing_slug():
    # A generator focuses on content; slug is derived at save time.
    draft = GuideDraft.model_validate({"title": "Presto", "tabs": []})
    assert draft.slug is None
    assert draft.status == "draft"


def test_reconciles_name_only_swatch_to_shelf_id(client, db):
    paint = _shelf_paint(client)
    draft = _draft_with_swatches([{"name": "Coal Black", "value_pct": 20}])

    result = reconcile_draft_paints(db, draft)

    sw = result.draft.tabs[0].phases[0].steps[0].swatches[0]
    assert sw.paint_id == paint["id"]
    assert result.unresolved == []


def test_reports_unresolved_name(client, db):
    _shelf_paint(client)
    draft = _draft_with_swatches([{"name": "Nonexistent Purple"}])

    result = reconcile_draft_paints(db, draft)

    sw = result.draft.tabs[0].phases[0].steps[0].swatches[0]
    assert sw.paint_id is None
    assert len(result.unresolved) == 1
    assert result.unresolved[0].name == "Nonexistent Purple"
    assert result.unresolved[0].step == "Basecoat"


def test_existing_paint_id_untouched(client, db):
    _shelf_paint(client)
    draft = _draft_with_swatches([{"paint_id": 999, "name": "Coal Black"}])

    result = reconcile_draft_paints(db, draft)

    # An explicit id is never re-resolved, even if the name would match.
    assert result.draft.tabs[0].phases[0].steps[0].swatches[0].paint_id == 999
    assert result.unresolved == []


def test_reconciles_mix_components(client, db):
    paint = _shelf_paint(client)
    draft = _draft_with_swatches(
        swatches=[],
        mix_components=[{"name": "Coal Black", "parts": 3}, {"name": "Ghost Grey", "parts": 1}],
    )

    result = reconcile_draft_paints(db, draft)

    comps = result.draft.tabs[0].phases[0].steps[0].mix_components
    assert comps[0].paint_id == paint["id"]
    assert comps[1].paint_id is None
    assert [u.name for u in result.unresolved] == ["Ghost Grey"]

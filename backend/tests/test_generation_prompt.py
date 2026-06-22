"""Generation prompt assembly (#525, M4 §8.3)."""
from app.painting.models import Guide
from app.painting.services.generation_prompt import (
    assemble_system_prompt,
    build_shelf_constraint,
    build_user_prompt,
)

from tests.test_painting_guides import mk_paint


def _line(client):
    brand = client.post("/painting/brands", json={"name": "Monument Hobbies"}).json()
    return client.post(
        "/painting/lines", json={"brand_id": brand["id"], "name": "Pro Acryl"}
    ).json()


def test_system_prompt_includes_rules_and_owned_paints(client, db):
    line = _line(client)
    mk_paint(client, line["id"], code="002", name="Coal Black")

    prompt = assemble_system_prompt(db)

    # Domain rules are present.
    assert "value first" in prompt.lower()
    assert "INVENTORY CONSTRAINT" in prompt
    assert "GuideDraft" in prompt
    # The owned paint is injected.
    assert "Coal Black" in prompt
    # The placeholder was substituted.
    assert "{shelf}" not in prompt


def test_system_prompt_includes_enriched_rule_blocks(client, db):
    # Folded-in domain specifics (#525 enrichment): skin method selection, eye
    # order, thinning rule.
    prompt = assemble_system_prompt(db).lower()
    assert "pick one method" in prompt
    assert "sclera" in prompt
    assert "vallejo metal color" in prompt  # thinning exception


def test_shelf_constraint_excludes_unowned(client, db):
    line = _line(client)
    mk_paint(client, line["id"], code="002", name="Coal Black")
    # An explicitly not-owned paint must not leak into the constraint.
    client.post("/painting/paints", json={
        "paint_line_id": line["id"], "code": "099", "name": "Unowned Teal",
        "hex": "#008080", "finish": "matte", "owned": False,
    })

    constraint = build_shelf_constraint(db)
    assert "Coal Black" in constraint
    assert "Unowned Teal" not in constraint


def test_empty_shelf_message(client, db):
    constraint = build_shelf_constraint(db)
    assert "EMPTY" in constraint


def test_user_prompt_includes_context(db):
    guide = Guide(slug="presto", title="Presto the Magician", scale="1:6",
                  franchise="D&D", technique_tags=["OSL"])
    db.add(guide)
    db.commit()

    prompt = build_user_prompt(guide)
    assert "Presto the Magician" in prompt
    assert "1:6" in prompt
    assert "OSL" in prompt
    assert "GuideDraft JSON" in prompt

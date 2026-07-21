"""
Tests for source_url propagation across a variant group (#202, STUDIO-304): a
URL written to one variant is copied to same-group siblings that don't have
one, via all three write paths (metadata editor, Find on Web apply, storefront
enrichment). Propagation is keyed on the durable variant_group_id (#678), not
the legacy `character` field — two distinct durable groups can share a
character (e.g. a bust split from a 75mm figure), so grouping here must not.
"""
from unittest.mock import AsyncMock

from app.services import enrich_refresh
from tests.conftest import make_creator, make_model, make_variant_group

URL = "https://www.myminifactory.com/object/print-ada-wong-12345"


def _group(db, n=3, character="Ada Wong"):
    """Creator + n models in the same durable variant group; returns (creator, models)."""
    creator = make_creator(db)
    models = [
        make_model(db, creator, name=f"Ada Wong v{i}", character=character)
        for i in range(n)
    ]
    make_variant_group(db, creator, models)
    db.commit()
    return creator, models


class TestUpdateModelPropagation:
    def test_fills_null_and_empty_siblings(self, client, db):
        _, (target, null_sib, empty_sib) = _group(db)
        empty_sib.source_url = ""  # the editor saves cleared fields as ""
        db.commit()

        resp = client.patch(f"/models/{target.id}",
                            json={"source_url": URL, "source_site": "myminifactory"})
        assert resp.status_code == 200

        for sib in (null_sib, empty_sib):
            db.refresh(sib)
            assert sib.source_url == URL
            assert sib.source_site == "myminifactory"

    def test_existing_url_not_overwritten(self, client, db):
        _, (target, sib, _) = _group(db)
        sib.source_url = "https://cults3d.com/other-listing"
        sib.source_site = "cults3d"
        db.commit()

        client.patch(f"/models/{target.id}", json={"source_url": URL})

        db.refresh(sib)
        assert sib.source_url == "https://cults3d.com/other-listing"
        assert sib.source_site == "cults3d"

    def test_other_groups_and_creators_untouched(self, client, db):
        creator, (target, *_) = _group(db)
        other_group = make_model(db, creator, name="Leon", character="Leon Kennedy")
        other_creator = make_creator(db, name="Other Studio")
        same_char_other_creator = make_model(db, other_creator, name="Ada Clone",
                                             character="Ada Wong")
        db.commit()

        client.patch(f"/models/{target.id}", json={"source_url": URL})

        db.refresh(other_group)
        db.refresh(same_char_other_creator)
        assert other_group.source_url is None
        assert same_char_other_creator.source_url is None

    def test_no_propagation_when_ungrouped(self, client, db):
        creator = make_creator(db)
        target = make_model(db, creator, name="Loner")          # character=None
        other = make_model(db, creator, name="Other model")
        db.commit()

        client.patch(f"/models/{target.id}", json={"source_url": URL})

        db.refresh(other)
        assert other.source_url is None

    def test_no_propagation_on_empty_url(self, client, db):
        _, (target, sib, _) = _group(db)

        client.patch(f"/models/{target.id}", json={"source_url": ""})

        db.refresh(sib)
        assert sib.source_url is None


class TestScrapeApplyPropagation:
    def test_apply_propagates_to_group(self, client, db):
        _, (target, sib, _) = _group(db)

        resp = client.post(f"/scrape/apply/{target.id}",
                           json={"source_url": URL, "source_site": "myminifactory"})
        assert resp.status_code == 200

        db.refresh(sib)
        assert sib.source_url == URL
        assert sib.source_site == "myminifactory"


class TestEnrichApplyPropagation:
    def test_bulk_apply_propagates_to_group(self, client, db, monkeypatch):
        _, (target, sib, _) = _group(db)

        # No live fetch: force the shallow path so the match's own source
        # fields are what propagate (a real MMF fetch would rewrite them).
        monkeypatch.setattr(enrich_refresh.scrapers, "fetch_url", AsyncMock(return_value=None))

        resp = client.post("/enrich/storefront/apply", json={"items": [{
            "model_id": target.id,
            "source_url": URL,
            "source_site": "loot-studios",
        }]})
        assert resp.status_code == 200

        db.refresh(target)
        db.refresh(sib)
        assert target.source_url == URL
        assert sib.source_url == URL
        assert sib.source_site == "loot-studios"

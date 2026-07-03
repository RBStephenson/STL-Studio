"""Phase 0 (#614): variant_groups schema, ORM relationships, and the migration
backfill from existing (creator, character) groups."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

from app.models import Model, VariantGroup
from app.utils import utcnow
from tests.conftest import make_creator, make_model


def _load_migration():
    """Import the 0017 migration module by path (digit-led name isn't importable)."""
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0017_variant_groups.py"
    spec = importlib.util.spec_from_file_location("mig_0017", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# ORM relationships
# ---------------------------------------------------------------------------

class TestVariantGroupORM:
    def test_round_trip_membership(self, db):
        creator = make_creator(db)
        m1 = make_model(db, creator, name="A")
        m2 = make_model(db, creator, name="B")
        grp = VariantGroup(creator_id=creator.id, label="Ada Wong", source="auto")
        db.add(grp)
        db.flush()
        m1.variant_group_id = grp.id
        m2.variant_group_id = grp.id
        grp.rep_model_id = m1.id
        db.flush()

        assert {m.id for m in grp.models} == {m1.id, m2.id}
        assert m1.variant_group.label == "Ada Wong"
        assert grp.rep_model.id == m1.id

    def test_source_defaults_auto(self, db):
        creator = make_creator(db)
        grp = VariantGroup(creator_id=creator.id, label="X")
        db.add(grp)
        db.flush()
        db.refresh(grp)
        assert grp.source == "auto"


# ---------------------------------------------------------------------------
# Migration backfill
# ---------------------------------------------------------------------------

class TestBackfill:
    def _run(self, db):
        # _backfill needs a Connection (SA 2.0 Engine has no .execute); the
        # session's own connection keeps the writes in the same transaction.
        _load_migration()._backfill(db.connection())
        db.expire_all()

    def test_multi_member_character_gets_group(self, db):
        creator = make_creator(db)
        a1 = make_model(db, creator, name="Ada 1", character="Ada Wong")
        a2 = make_model(db, creator, name="Ada 2", character="Ada Wong")
        db.commit()

        self._run(db)

        groups = db.query(VariantGroup).all()
        assert len(groups) == 1
        g = groups[0]
        assert g.label == "Ada Wong"
        assert g.source == "auto"
        assert {m.id for m in g.models} == {a1.id, a2.id}

    def test_rep_prefers_is_group_rep(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="x1", character="Leon")
        rep = make_model(db, creator, name="x2", character="Leon")
        rep.is_group_rep = True
        db.commit()

        self._run(db)

        g = db.query(VariantGroup).filter_by(label="Leon").one()
        assert g.rep_model_id == rep.id

    def test_singleton_character_gets_no_group(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="Solo", character="Lone Wolf")
        db.commit()

        self._run(db)

        assert db.query(VariantGroup).count() == 0

    def test_excluded_members_ignored(self, db):
        creator = make_creator(db)
        keep = make_model(db, creator, name="k1", character="Goblin")
        gone = make_model(db, creator, name="k2", character="Goblin")
        gone.excluded = True
        db.commit()

        self._run(db)

        # Only one non-excluded member remains → not a group.
        assert db.query(VariantGroup).count() == 0
        db.refresh(keep)
        assert keep.variant_group_id is None

    def test_distinct_characters_get_distinct_groups(self, db):
        creator = make_creator(db)
        make_model(db, creator, name="a1", character="Ada")
        make_model(db, creator, name="a2", character="Ada")
        make_model(db, creator, name="b1", character="Leon")
        make_model(db, creator, name="b2", character="Leon")
        db.commit()

        self._run(db)

        labels = {g.label for g in db.query(VariantGroup).all()}
        assert labels == {"Ada", "Leon"}


# ---------------------------------------------------------------------------
# set_grouping_strategy() only regroups creators under the target path (#650)
# ---------------------------------------------------------------------------

class TestSetGroupingStrategyScope:
    """POST /grouping-strategy must regroup only creators whose models live
    under the requested path — not every creator in the library."""

    def _make_model_at(self, db, creator, path):
        m = Model(
            name=Path(path).name,
            folder_path=path,
            creator_id=creator.id,
            tags=[],
            auto_tags=[],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(m)
        db.flush()
        return m

    def test_only_affected_creator_regroups(self, client, db):
        creator_a = make_creator(db, "CreatorA")
        creator_b = make_creator(db, "CreatorB")

        self._make_model_at(db, creator_a, "/mnt/lib/CreatorA/Product/STL")
        self._make_model_at(db, creator_b, "/mnt/lib/CreatorB/Other/STL")
        db.commit()

        regroups: list[int] = []

        import app.services.grouping as grouping_mod
        real_regroup = grouping_mod.regroup_creator

        def tracking_regroup(db, creator_id):
            regroups.append(creator_id)
            real_regroup(db, creator_id)

        with patch.object(grouping_mod, "regroup_creator", tracking_regroup):
            resp = client.post(
                "/models/grouping-strategy",
                json={"path": "/mnt/lib/CreatorA", "strategy": "off"},
            )

        assert resp.status_code == 200
        assert regroups == [creator_a.id], (
            f"Expected only creator_a ({creator_a.id}) to regroup; got {regroups}"
        )

    def test_unrelated_creator_not_regrouped(self, client, db):
        creator_a = make_creator(db, "CreatorX")
        creator_b = make_creator(db, "CreatorY")

        self._make_model_at(db, creator_a, "/lib/CreatorX/Product")
        self._make_model_at(db, creator_b, "/lib/CreatorY/Product")
        db.commit()

        regroups: list[int] = []

        import app.services.grouping as grouping_mod
        real_regroup = grouping_mod.regroup_creator

        def tracking_regroup(db, creator_id):
            regroups.append(creator_id)
            real_regroup(db, creator_id)

        with patch.object(grouping_mod, "regroup_creator", tracking_regroup):
            resp = client.post(
                "/models/grouping-strategy",
                json={"path": "/lib/CreatorX", "strategy": "off"},
            )

        assert resp.status_code == 200
        assert creator_b.id not in regroups

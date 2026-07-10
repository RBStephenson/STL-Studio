"""Tests for the one-off cleanup script (backend/scripts/cleanup_hash_suffix_names.py)
that repairs Model.name rows left with a stray trailing "#" by the
Patreon-style release-marker bug (#959), fixed going forward in
name_parser.py but not retroactively.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cleanup_hash_suffix_names import cleaned_name  # noqa: E402
from app.models import Model  # noqa: E402


class TestCleanedName:
    def test_strips_trailing_hash(self):
        assert cleaned_name("Cold Giant#") == "Cold Giant"

    def test_strips_trailing_hash_with_space(self):
        assert cleaned_name("Cold Giant #") == "Cold Giant"

    def test_leaves_name_without_trailing_hash_untouched(self):
        assert cleaned_name("Cold Giant") == "Cold Giant"

    def test_bare_hash_reduces_to_empty(self):
        # main() must skip this row rather than apply an empty name.
        assert cleaned_name("#") == ""

    def test_only_strips_trailing_hash_not_an_internal_one(self):
        # A "#" that isn't at the end (however unlikely) is left alone —
        # this script only targets the specific trailing-marker defect.
        assert cleaned_name("Product #7 Special") == "Product #7 Special"


class TestAffectedQuery:
    def test_like_filter_matches_only_trailing_hash(self, db):
        db.add(Model(name="Cold Giant#", folder_path="/lib/a"))
        db.add(Model(name="Product #7 Special", folder_path="/lib/b"))
        db.add(Model(name="Clean Name", folder_path="/lib/c"))
        db.commit()

        affected = db.query(Model).filter(Model.name.like("%#")).all()

        assert {m.name for m in affected} == {"Cold Giant#"}

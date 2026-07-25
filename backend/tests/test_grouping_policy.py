"""The grouping policy/persistence boundary (STUDIO-247).

Behaviour of the policy functions themselves is covered in `test_grouping.py`,
which reaches them through `grouping`'s re-exports. This file guards the split
itself: that the pure module stays pure, and that the re-exports are the same
objects rather than copies that could drift.
"""
import ast
import pathlib

import pytest

from app.services import grouping, grouping_policy

_POLICY_SOURCE = pathlib.Path(grouping_policy.__file__)

#: Anything that would drag persistence into the pure layer.
_FORBIDDEN_ROOTS = {"sqlalchemy", "app.models", "app.database"}


def _imported_modules(source: pathlib.Path) -> set[str]:
    """Every module named by an import statement in `source`."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class TestPolicyModuleStaysPure:
    """The pure layer must not acquire a database dependency (STUDIO-247).

    Enforced by parsing imports rather than by review, so reaching for a session
    here fails a test instead of passing unnoticed.
    """

    def test_imports_nothing_persistence_related(self):
        imported = _imported_modules(_POLICY_SOURCE)

        offenders = sorted(
            name
            for name in imported
            if any(name == root or name.startswith(root + ".") for root in _FORBIDDEN_ROOTS)
        )

        assert offenders == [], f"grouping_policy must stay database-free; found {offenders}"

    def test_module_namespace_exposes_no_session_type(self):
        # A late/local import would evade the AST check above.
        assert not hasattr(grouping_policy, "Session")
        assert not hasattr(grouping_policy, "VariantGroup")
        assert not hasattr(grouping_policy, "Model")

    def test_the_orchestrator_by_contrast_does_use_the_database(self):
        # Sanity check that the previous assertions mean something.
        assert "sqlalchemy.orm" in _imported_modules(pathlib.Path(grouping.__file__))


class TestReExportsAreTheSameObjects:
    """`grouping.X is grouping_policy.X` — callers and tests keep one contract."""

    @pytest.mark.parametrize("name", [
        "CandidateFacts",
        "CandidateModel",
        "EligibilityDecision",
        "Evidence",
        "EvidenceLedger",
        "GroupProposal",
        "IneligibilityReason",
        "SIGNAL_POLICY",
        "SignalKind",
        "SignalPolicy",
        "assert_policies_complete",
        "build_clusters",
        "filename_evidence",
        "hash_evidence",
        "hierarchy_evidence",
        "name_evidence",
        "name_keys",
        "order_candidates",
        "policy_for",
        "product_boundaries",
        "propose_groups",
        "select_eligible",
        "select_label",
        "select_representative",
    ])
    def test_name_is_re_exported_by_identity(self, name):
        assert getattr(grouping, name) is getattr(grouping_policy, name)

    def test_every_policy_name_in_all_resolves(self):
        missing = [name for name in grouping.__all__ if not hasattr(grouping, name)]

        assert missing == []

    def test_orchestration_entry_points_live_in_grouping(self):
        for name in ("regroup_creator", "prune_empty_groups", "materialise_proposals"):
            assert hasattr(grouping, name)
            assert not hasattr(grouping_policy, name)

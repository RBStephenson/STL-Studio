"""Unit tests for the shared scan-root boundary abstraction (STUDIO-229).

These pin the safety-critical comparison the destructive prunes depend on. The
sibling-prefix and empty-input cases are the ones that turn into data loss if they
regress, so they are asserted in both directions rather than only the happy path.
"""
import os

import pytest

from app.services.path_boundary import PathBoundary, normalize

WINDOWS = os.name == "nt"


def p(*parts: str) -> str:
    """Build a host-native absolute path so tests read the same on both OSes."""
    root = "C:\\" if WINDOWS else "/"
    return os.path.join(root, *parts)


class TestNormalize:
    def test_collapses_redundant_separators_and_dots(self):
        assert normalize(p("lib", "STL", "..", "STL", "Creator")) == normalize(
            p("lib", "STL", "Creator")
        )

    def test_does_not_touch_the_filesystem(self, tmp_path):
        """A path that no longer exists must normalize the same as a live one —
        prune membership compares against rows whose folders may be long gone."""
        missing = tmp_path / "gone" / "Creator"
        assert normalize(missing) == normalize(str(missing))


class TestContains:
    def test_exact_root_matches(self):
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert b.contains(p("lib", "STL"))

    def test_descendant_matches(self):
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert b.contains(p("lib", "STL", "Creator", "Model"))

    def test_sibling_prefix_does_not_match(self):
        """The bug this anchoring exists to prevent: STLBackup is not under STL.
        Without the separator anchor a plain startswith would prune the backup."""
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert not b.contains(p("lib", "STLBackup"))
        assert not b.contains(p("lib", "STLBackup", "Creator"))

    def test_parent_of_a_root_does_not_match(self):
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert not b.contains(p("lib"))

    def test_unrelated_path_does_not_match(self):
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert not b.contains(p("elsewhere", "Creator"))

    def test_matches_any_of_several_roots(self):
        b = PathBoundary.from_paths([p("lib", "A"), p("lib", "B")])
        assert b.contains(p("lib", "B", "Creator"))

    @pytest.mark.parametrize("value", [None, ""])
    def test_missing_path_is_not_contained(self, value):
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert not b.contains(value)

    def test_empty_boundary_contains_nothing(self):
        """'No roots' must never mean 'everything' — that would hand every
        destructive prune the whole library."""
        assert not PathBoundary.from_paths([]).contains(p("lib", "STL"))

    def test_trailing_separator_on_root_still_matches(self):
        b = PathBoundary.from_paths([p("lib", "STL") + os.sep])
        assert b.contains(p("lib", "STL", "Creator"))


class TestIsRoot:
    def test_exact_root_matches(self):
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert b.is_root(p("lib", "STL"))

    def test_descendant_does_not_match(self):
        """The distinction from contains(): the ignore walk-up must climb PAST
        descendants and stop only on the root itself."""
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert not b.is_root(p("lib", "STL", "Creator"))

    @pytest.mark.parametrize("value", [None, ""])
    def test_missing_path_is_not_a_root(self, value):
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert not b.is_root(value)

    def test_empty_boundary_has_no_roots(self):
        assert not PathBoundary.from_paths([]).is_root(p("lib", "STL"))


class TestFromPaths:
    def test_deduplicates_equivalent_roots(self):
        b = PathBoundary.from_paths([
            p("lib", "STL"),
            p("lib", "STL") + os.sep,
            p("lib", "STL", "..", "STL"),
        ])
        assert len(b) == 1

    def test_drops_blank_entries(self):
        """normpath('') is '.', which as a root would match every relative path."""
        b = PathBoundary.from_paths(["", None, p("lib", "STL")])
        assert len(b) == 1
        assert not b.contains("anything/relative")

    def test_none_iterable_is_empty(self):
        assert len(PathBoundary.from_paths(None)) == 0

    def test_is_falsy_when_empty_and_truthy_otherwise(self):
        assert not PathBoundary.from_paths([])
        assert PathBoundary.from_paths([p("lib", "STL")])

    def test_is_immutable(self):
        b = PathBoundary.from_paths([p("lib", "STL")])
        with pytest.raises(Exception):
            b.roots = ()  # type: ignore[misc]


class TestHostCasingSemantics:
    """Casing follows the host filesystem, per STUDIO-229. This is deliberately
    NOT portable — making stored identity host-independent is STUDIO-359."""

    @pytest.mark.skipif(not WINDOWS, reason="Windows casing semantics")
    def test_windows_treats_case_variants_as_the_same_path(self):
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert b.contains(p("LIB", "stl", "Creator"))
        assert b.is_root(p("LIB", "stl"))

    @pytest.mark.skipif(WINDOWS, reason="POSIX casing semantics")
    def test_posix_treats_case_variants_as_distinct_paths(self):
        b = PathBoundary.from_paths([p("lib", "STL")])
        assert not b.contains(p("lib", "stl", "Creator"))
        assert not b.is_root(p("lib", "stl"))


class TestMatchesCurrentScannerBehavior:
    """Characterization: the extracted logic must agree with the closures still
    inlined in scanner.py, which STUDIO-230 will replace with this class."""

    def _legacy_under_root(self, roots: list[str], folder_path: str | None) -> bool:
        if not folder_path:
            return False
        roots_norm = [os.path.normcase(os.path.normpath(r)) for r in roots]
        n = os.path.normcase(os.path.normpath(folder_path))
        return any(n == r or n.startswith(r + os.sep) for r in roots_norm)

    def _legacy_is_root(self, roots: list[str], folder_path: str) -> bool:
        roots_norm = {os.path.normcase(os.path.normpath(r)) for r in roots}
        return os.path.normcase(os.path.normpath(folder_path)) in roots_norm

    @pytest.mark.parametrize("candidate", [
        p("lib", "STL"),
        p("lib", "STL", "Creator"),
        p("lib", "STL", "Creator", "Model"),
        p("lib", "STLBackup"),
        p("lib", "STLBackup", "Creator"),
        p("lib"),
        p("elsewhere"),
        p("lib", "STL") + os.sep,
    ])
    def test_contains_matches_legacy_closure(self, candidate):
        roots = [p("lib", "STL"), p("lib", "Other")]
        assert (
            PathBoundary.from_paths(roots).contains(candidate)
            == self._legacy_under_root(roots, candidate)
        )

    @pytest.mark.parametrize("candidate", [
        p("lib", "STL"),
        p("lib", "STL", "Creator"),
        p("lib", "STLBackup"),
        p("lib"),
    ])
    def test_is_root_matches_legacy_closure(self, candidate):
        roots = [p("lib", "STL"), p("lib", "Other")]
        assert (
            PathBoundary.from_paths(roots).is_root(candidate)
            == self._legacy_is_root(roots, candidate)
        )

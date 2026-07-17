"""Unit tests for the wiki generator (scripts/wiki/build_wiki.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import build_wiki as bw  # noqa: E402


# --- rewrite_target ---------------------------------------------------------

@pytest.mark.parametrize(
    "target, source, expected",
    [
        # Relative link within docs/ -> wiki page.
        ("getting-started.md", "docs/README.md", "Getting-Started"),
        ("features.md", "docs/docker.md", "Feature-Guide"),
        ("support-policy.md", "docs/README.md", "Support-and-compatibility-policy"),
        # Anchor is preserved when mapping to a wiki page.
        (
            "features.md#variant-grouping",
            "docs/scanning-and-folders.md",
            "Feature-Guide#variant-grouping",
        ),
        # Same-page anchor is left untouched.
        ("#standalone-recommended", "docs/getting-started.md", "#standalone-recommended"),
        # External links untouched.
        (
            "https://github.com/RBStephenson/STL-Inventory/releases",
            "docs/README.md",
            "https://github.com/RBStephenson/STL-Inventory/releases",
        ),
        # ROADMAP at repo root linking into docs/painting (no wiki page) -> blob URL.
        (
            "docs/painting/spec.md",
            "ROADMAP.md",
            f"{bw.BLOB_BASE}docs/painting/spec.md",
        ),
        # A doc linking to ROADMAP.md resolves to the Roadmap wiki page.
        ("../ROADMAP.md", "docs/features.md", "Roadmap"),
        # Leading ./ is normalized.
        ("./troubleshooting.md", "docs/docker.md", "Troubleshooting-and-FAQ"),
    ],
)
def test_rewrite_target(target, source, expected):
    assert bw.rewrite_target(target, source) == expected


def test_non_wiki_md_keeps_anchor():
    out = bw.rewrite_target("docs/painting/spec.md#section-15", "ROADMAP.md")
    assert out == f"{bw.BLOB_BASE}docs/painting/spec.md#section-15"


# --- transform (links + strip) ---------------------------------------------

def test_transform_rewrites_inline_links():
    text = "See the [Feature Guide](features.md#library) for details."
    out = bw.transform(text, "docs/getting-started.md")
    assert "(Feature-Guide#library)" in out
    assert "features.md" not in out


def test_transform_strips_wiki_only_block():
    text = (
        "# Title\n\n"
        "<!-- wiki-only:strip -->\n"
        "> Edit here, not the wiki.\n"
        "<!-- /wiki-only -->\n"
        "Body stays.\n"
    )
    out = bw.transform(text, "docs/README.md")
    assert "Edit here, not the wiki." not in out
    assert "Body stays." in out
    assert "# Title" in out


def test_transform_leaves_external_and_anchor_links():
    text = "[rel](https://example.com) and [a](#here)"
    out = bw.transform(text, "docs/README.md")
    assert out == text


# --- build (end to end) -----------------------------------------------------

def test_build_writes_all_pages(tmp_path):
    repo_root = Path(bw.__file__).resolve().parents[2]
    out = tmp_path / "wiki"
    written = bw.build(repo_root, out)

    for page in bw.SOURCES.values():
        assert (out / f"{page}.md").exists()
    assert "_Sidebar.md" in written
    assert "_Footer.md" in written

    # The Home page must not leak any repo-only banner.
    home = (out / "Home.md").read_text(encoding="utf-8")
    assert "wiki-only:strip" not in home


def test_build_home_has_no_unmapped_doc_links(tmp_path):
    repo_root = Path(bw.__file__).resolve().parents[2]
    out = tmp_path / "wiki"
    bw.build(repo_root, out)
    home = (out / "Home.md").read_text(encoding="utf-8")
    # No raw relative *.md links should survive in generated output.
    assert "](getting-started.md)" not in home
    assert "](features.md)" not in home

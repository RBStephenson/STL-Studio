#!/usr/bin/env python3
"""Generate the GitHub Wiki from the in-repo docs.

The ``docs/`` folder (plus ``ROADMAP.md``) is the single source of truth for
user documentation. This script transforms those Markdown files into the page
set the GitHub Wiki expects:

* source files are renamed to their wiki page names (see ``SOURCES``);
* cross-document links and anchors are rewritten to wiki links;
* links to ``.md`` files that have no wiki page (e.g. ``docs/painting/spec.md``)
  are rewritten to absolute links into the repository on ``main``;
* repo-only blocks wrapped in ``<!-- wiki-only:strip -->`` / ``<!-- /wiki-only -->``
  are removed (so e.g. the "edit here, not the wiki" banner never lands on the
  wiki itself);
* the static ``templates/`` (``_Sidebar.md``, ``_Footer.md``) are copied through.

The wiki is *generated* — never hand-edited. Edit ``docs/`` and the publish
workflow rebuilds the wiki on merge to ``main``.

Usage::

    python scripts/wiki/build_wiki.py --out _wiki_build
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

REPO = "RBStephenson/STL-Inventory"
BLOB_BASE = f"https://github.com/{REPO}/blob/main/"

# Repo-relative source path -> wiki page name (no .md extension).
SOURCES: dict[str, str] = {
    "docs/README.md": "Home",
    "docs/getting-started.md": "Getting-Started",
    "docs/features.md": "Feature-Guide",
    "docs/scanning-and-folders.md": "Scanning-and-Folder-Structure",
    "docs/docker.md": "Docker-Drive-Mounts",
    "docs/troubleshooting.md": "Troubleshooting-and-FAQ",
    "docs/support-policy.md": "Support-and-compatibility-policy",
    "ROADMAP.md": "Roadmap",
}

STRIP_RE = re.compile(
    r"[ \t]*<!--\s*wiki-only:strip\s*-->.*?<!--\s*/wiki-only\s*-->[ \t]*\n?",
    re.DOTALL,
)

# Matches the target inside a Markdown inline link: ](TARGET)
LINK_RE = re.compile(r"(?<=\]\()([^)\s]+)(?=\))")


def _posix_normpath(path: str) -> str:
    """Normalize a POSIX-style relative path without touching the filesystem."""
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def rewrite_target(target: str, source_relpath: str) -> str:
    """Rewrite a single link target for the wiki.

    ``source_relpath`` is the repo-relative path of the file the link lives in
    (e.g. ``docs/features.md``), used to resolve relative links.
    """
    # Leave external links, in-page anchors, and non-document protocols alone.
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return target

    path, sep, anchor = target.partition("#")
    suffix = f"#{anchor}" if sep else ""

    if not path:  # pure same-page anchor like "(#foo)"
        return target

    src_dir = source_relpath.rsplit("/", 1)[0] if "/" in source_relpath else ""
    repo_rel = _posix_normpath(f"{src_dir}/{path}" if src_dir else path)

    if repo_rel in SOURCES:
        return f"{SOURCES[repo_rel]}{suffix}"

    if repo_rel.lower().endswith(".md"):
        # A real doc with no wiki page (painting spec, CONTRIBUTING, etc.).
        return f"{BLOB_BASE}{repo_rel}{suffix}"

    # Images or other assets: point at the raw repo path so they still resolve.
    return f"{BLOB_BASE}{repo_rel}{suffix}"


def transform(text: str, source_relpath: str) -> str:
    text = STRIP_RE.sub("", text)
    return LINK_RE.sub(lambda m: rewrite_target(m.group(0), source_relpath), text)


def build(repo_root: Path, out_dir: Path) -> list[str]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    written: list[str] = []
    for source_relpath, page in SOURCES.items():
        src = repo_root / source_relpath
        if not src.exists():
            raise FileNotFoundError(f"Source doc missing: {source_relpath}")
        rendered = transform(src.read_text(encoding="utf-8"), source_relpath)
        (out_dir / f"{page}.md").write_text(rendered, encoding="utf-8")
        written.append(f"{page}.md")

    templates = Path(__file__).parent / "templates"
    for tpl in sorted(templates.glob("*.md")):
        shutil.copyfile(tpl, out_dir / tpl.name)
        written.append(tpl.name)

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="_wiki_build",
        help="Output directory for the generated wiki (default: _wiki_build).",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (defaults to two levels above this script).",
    )
    args = parser.parse_args()

    repo_root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[2]
    )
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = (repo_root / out_dir).resolve()

    written = build(repo_root, out_dir)
    print(f"Wrote {len(written)} wiki pages to {out_dir}:")
    for name in written:
        print(f"  - {name}")


if __name__ == "__main__":
    main()

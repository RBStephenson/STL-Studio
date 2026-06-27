"""Bulk-import legacy HTML painting guides via the /painting/guides/import API.

Usage:
    python scripts/bulk_import_guides.py [--base-url URL] [--dry-run] [--report-csv PATH]

Defaults:
    --base-url   http://localhost:8000
    --dry-run    False  (pass to preview without persisting)
    --report-csv bulk_import_report.csv

The script walks by-category/**/*.html, derives the slug from the filename
stem, and POSTs each file to POST /api/painting/guides/import.

Exit codes:
    0  all guides imported (or dry-ran) without error
    1  one or more guides failed or had unresolved paints
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import urllib.request
import urllib.error

GUIDES_DIR = (
    Path.home()
    / "OneDrive/Documents/Claude/Projects/Figure Painting/painting-guides/by-category"
)

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_API_PREFIX = ""  # empty when hitting uvicorn directly; "/api" for standalone binary
DEFAULT_REPORT = Path("bulk_import_report.csv")


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def import_guide(base_url: str, api_prefix: str, html: str, slug: str, dry_run: bool) -> dict:
    url = f"{base_url}{api_prefix}/painting/guides/import"
    return post_json(url, {"html": html, "slug": slug, "dry_run": dry_run})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-prefix", default=DEFAULT_API_PREFIX, help="e.g. /api for standalone binary; empty for direct uvicorn")
    parser.add_argument("--dry-run", action="store_true", help="Parse + report only, no persist")
    parser.add_argument("--report-csv", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    html_files = sorted(GUIDES_DIR.rglob("*.html"))
    if not html_files:
        print(f"No HTML files found under {GUIDES_DIR}", file=sys.stderr)
        return 1

    print(f"Found {len(html_files)} guides. Mode: {'DRY RUN' if args.dry_run else 'IMPORT'}")
    print(f"Endpoint: {args.base_url}{args.api_prefix}/painting/guides/import")
    print()

    rows: list[dict] = []
    had_errors = False
    had_unresolved = False

    for path in html_files:
        slug = path.stem
        category = path.parent.name
        html = path.read_text(encoding="utf-8", errors="replace")

        try:
            result = import_guide(args.base_url, args.api_prefix, html, slug, args.dry_run)
        except RuntimeError as e:
            print(f"  FAIL  {category}/{slug}: {e}")
            rows.append({
                "category": category,
                "slug": slug,
                "status": "error",
                "guide_id": "",
                "resolved_paints": "",
                "unresolved_count": "",
                "unresolved_paints": "",
                "unmapped_nodes": "",
                "error": str(e),
            })
            had_errors = True
            continue

        report = result.get("report", {})
        guide = result.get("guide")
        unresolved = report.get("unresolved_paints", [])
        unmapped = report.get("unmapped_nodes", [])
        resolved = report.get("resolved_paints", 0)

        status = "dry-run" if args.dry_run else "imported"
        if unresolved:
            had_unresolved = True
            status += "+unresolved"

        unresolved_names = "; ".join(
            f"{u.get('name', '?')} ({u.get('step', '?')})" for u in unresolved
        )
        guide_id = guide["id"] if guide else ""

        print(
            f"  {'DRY' if args.dry_run else 'OK ':3}  {category}/{slug}"
            f"  resolved={resolved}"
            + (f"  UNRESOLVED={len(unresolved)}" if unresolved else "")
            + (f"  unmapped_nodes={len(unmapped)}" if unmapped else "")
        )

        rows.append({
            "category": category,
            "slug": slug,
            "status": status,
            "guide_id": guide_id,
            "resolved_paints": resolved,
            "unresolved_count": len(unresolved),
            "unresolved_paints": unresolved_names,
            "unmapped_nodes": len(unmapped),
            "error": "",
        })

    # Write CSV report.
    fieldnames = [
        "category", "slug", "status", "guide_id",
        "resolved_paints", "unresolved_count", "unresolved_paints",
        "unmapped_nodes", "error",
    ]
    with args.report_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"Report written to {args.report_csv}")

    total = len(rows)
    errors = sum(1 for r in rows if r["status"] == "error")
    unresolved_guides = sum(1 for r in rows if "unresolved" in str(r["status"]))
    print(f"Total: {total}  Errors: {errors}  With unresolved paints: {unresolved_guides}")

    return 1 if (had_errors or had_unresolved) else 0


if __name__ == "__main__":
    sys.exit(main())

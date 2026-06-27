"""Run validate_guide over all imported guides and report flag distribution.

Usage:
    python scripts/corpus_validation_report.py [--base-url URL] [--api-prefix PREFIX]

Hits GET /painting/guides (all pages) then GET /painting/guides/{id}/validation
for each. Outputs a summary of flag codes + severity, and a CSV with per-guide
detail so we can spot false-positive patterns.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_API_PREFIX = ""
DEFAULT_REPORT = Path("corpus_validation_report.csv")


def get_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_all_guides(base: str, prefix: str) -> list[dict]:
    guides = []
    page = 1
    while True:
        data = get_json(f"{base}{prefix}/painting/guides?page={page}&page_size=100")
        items = data.get("items", [])
        guides.extend(items)
        if len(items) < 100:
            break
        page += 1
    return guides


def fetch_validation(base: str, prefix: str, guide_id: int, strict: bool = False) -> list[dict]:
    qs = "?strict=true" if strict else "?strict=false"
    data = get_json(f"{base}{prefix}/painting/guides/{guide_id}/validation{qs}")
    return data.get("flags", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-prefix", default=DEFAULT_API_PREFIX)
    parser.add_argument("--report-csv", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--strict", action="store_true", default=False,
                        help="Include authoring-quality checks (value_intent_missing, "
                             "value_compression). Default: off for import corpus runs.")
    args = parser.parse_args()

    print(f"Fetching guides from {args.base_url}{args.api_prefix}/painting/guides …")
    guides = fetch_all_guides(args.base_url, args.api_prefix)
    print(f"Found {len(guides)} guides")

    rows: list[dict] = []
    code_counter: Counter = Counter()
    severity_counter: Counter = Counter()

    for g in guides:
        gid = g["id"]
        slug = g.get("slug", str(gid))
        try:
            flags = fetch_validation(args.base_url, args.api_prefix, gid, strict=args.strict)
        except Exception as e:
            print(f"  ERR  {slug}: {e}")
            continue

        blocks = [f for f in flags if f.get("severity") == "block"]
        warns  = [f for f in flags if f.get("severity") == "warn"]

        for f in flags:
            code_counter[f.get("code", "unknown")] += 1
            severity_counter[f.get("severity", "?")] += 1

        codes = ", ".join(sorted({f.get("code", "?") for f in flags}))
        status = "CLEAN" if not flags else f"flags={len(flags)}"
        print(f"  {status:12}  {slug}  blocks={len(blocks)} warns={len(warns)}"
              + (f"  [{codes}]" if codes else ""))

        rows.append({
            "id": gid,
            "slug": slug,
            "title": g.get("title", ""),
            "total_flags": len(flags),
            "block_count": len(blocks),
            "warn_count": len(warns),
            "flag_codes": codes,
            "block_messages": " | ".join(f["message"] for f in blocks),
        })

    # Summary
    print()
    print("=== Flag code distribution ===")
    for code, count in code_counter.most_common():
        print(f"  {count:4}  {code}")
    print()
    print(f"Total flags: {sum(code_counter.values())}  "
          f"(block={severity_counter['block']}  warn={severity_counter['warn']})")
    clean = sum(1 for r in rows if r["total_flags"] == 0)
    print(f"Clean guides: {clean}/{len(rows)}")

    fieldnames = ["id", "slug", "title", "total_flags", "block_count",
                  "warn_count", "flag_codes", "block_messages"]
    with args.report_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Report written to {args.report_csv}")

    return 0 if severity_counter["block"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

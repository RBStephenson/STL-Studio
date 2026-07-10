"""
One-off cleanup: strip a stray trailing "#" left on Model.name by the
Patreon-style "#1234" release-marker bug (#959) — name_parser.py strips the
digits of a marker like "Cold Giant#4521" but, before that fix, left the "#"
itself behind, so already-scanned models came out named e.g. "Cold Giant#".

Fixed going forward in name_parser.py, but this does NOT retroactively repair
rows already in the database: the scanner's rename guard deliberately won't
overwrite a Model.name that's since diverged from both the raw folder name
and the freshly computed clean name, to protect user customizations. This
script is the one-time repair for names affected before the fix landed.

Only touches rows whose name literally ends in "#" (optionally with trailing
whitespace) — nothing else about the name is touched, so it can't clobber a
name you've since customized to legitimately end some other way.

Usage (run inside the backend container, which has app + DB access — -m so
the "app" package resolves without needing an extra PYTHONPATH):
    docker exec stl-studio-backend-1 python -m scripts.cleanup_hash_suffix_names
    docker exec stl-studio-backend-1 python -m scripts.cleanup_hash_suffix_names --apply

Defaults to a dry run (prints what would change, touches nothing) — pass
--apply to actually update and commit.
"""
import argparse
import sys

from app.database import SessionLocal
from app.models import Model


def cleaned_name(name: str) -> str:
    """Strip a trailing '#' (and any whitespace around it) from a model name."""
    return name.rstrip("# ").rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually update and commit (default: dry run, prints only)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        affected = db.query(Model).filter(Model.name.like("%#")).all()
        if not affected:
            print("No model names end in a stray '#'. Nothing to do.")
            return 0

        print(f"{len(affected)} model name(s) end in a stray '#':")
        skipped = []
        to_update = []
        for m in affected:
            new_name = cleaned_name(m.name)
            if not new_name:
                # A name that's nothing but "#"/whitespace — refuse to leave a
                # model with an empty name; needs a human to pick a real one.
                skipped.append(m)
                print(f"  [{m.id}] {m.name!r} -> SKIPPED (would leave an empty name)")
                continue
            to_update.append((m, new_name))
            print(f"  [{m.id}] {m.name!r} -> {new_name!r}")

        if skipped:
            print(f"\n{len(skipped)} row(s) skipped — nothing but '#'/whitespace, rename these by hand.")

        if not args.apply:
            print(f"\nDry run only — no changes made. Re-run with --apply to update {len(to_update)} name(s).")
            return 0

        for m, new_name in to_update:
            m.name = new_name
        db.commit()
        print(f"\nUpdated {len(to_update)} model name(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

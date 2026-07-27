# STL Studio — Feature Summary

A condensed tour of what STL Studio does. For exhaustive detail on any
screen, see the canonical [docs/features.md](docs/features.md) (also
published as the [GitHub Wiki](https://github.com/RBStephenson/STL-Studio/wiki)).

## Library

The home screen: a searchable, filterable grid of every model in your
collection.

- Search plus filters for creator (include/exclude), site, tag
  (include/exclude), NSFW, thumbnail presence, review status, and star rating
- **Hide printed** and **negative tag filter** (click a tag twice to exclude)
- **Variant grouping** — same-character folders collapse into one card with a
  variant count badge; drag one card onto another (or use *Merge into
  group*/*Move to group*) to fix grouping by hand, and it survives rescans
- All filter/sort/page state lives in the URL — shareable, back-button-safe
- Saved filter presets

## Triage Queue

Keyboard-driven review of models flagged `needs_review` — `→`/Space to
dismiss, `S` to skip, `←` to go back. Live count badge in the nav.

## Model Detail

- Edit tags (inline, no full form needed), metadata, source URL, NSFW flag
- Thumbnail picker: from the model's own folder, a URL, or direct upload
- 3D STL preview
- **Part labeling** — tag each STL file with a part category (head, arm,
  base, weapon, …)

## Favorites & Print Queue

★ Favorite, 🖨 Queue, ✓ Mark printed — from a card or the model header. The
**Queue** page is a drag-to-reorder print list (favorites float up) with a
**Recently Printed** history and a live nav badge.

## Kit Builder

Launched from a model's detail page. Groups every STL file by part label;
pick one file per part group to assemble a build, then **Copy list** grabs
the selected filenames for your slicer.

## Bulk Editor

Select multiple models in the grid → floating bar to add/remove tags across
the selection, or **Enrich** to set creator/character/title on all of them
at once (the fast path for making messy imports reorganize-eligible).

## Collections

Named groups of models independent of tags/creators — projects, wishlists,
whatever. Cover image + description, add models from the detail panel or a
bulk selection. Stored in the DB and included in every backup.

## Reorganize Library

Preview-then-apply a folder template (default
`{creator}/{character}/{title}`) to tidy files on disk. Filter the preview by
creator, use status tabs and page-level select-all for targeted runs. A
model's own images travel with it; the source folder is removed once empty.
Optional **Preserve release package structure** mode keeps a multi-file
release intact as one unit instead of flattening it.

## Import Folder

Bring a loose downloads folder or unsorted ZIP contents into the catalog
without adding it as a permanent scan root — the full
**import → enrich → organize** pipeline on one screen:

1. **Import Preview** shows one card per pack (each source subfolder)
2. Enrich each pack with creator/character/title/tags, pick a destination
   **Library**
3. **Move N imported packs → library** files them in via the reorganize
   engine (drift-checked, undoable)

A **Quick import** one-shot path also exists, flagging models `inbox` until
organized. Moving requires the Reorganize Library feature flag and a
writable destination (Docker mounts are read-only, so moving is effectively
standalone-only — import/enrich work everywhere).

## Storefront Enrichment

Paste a Gumroad, Cults3D, MyMiniFactory, or Loot Studios creator URL. Fuzzy-
matches scraped listings against local models, then pulls each match's full
product detail and bulk-applies title, description, tags, category, license,
thumbnail, source URL, and external ID — across every model in a variant
group. Uses official APIs when keys are configured (faster, richer),
otherwise falls back to scraping.

## Painting Guides

- **Paint Shelf** (always available): paint inventory with brand/line/finish
  filters, color swatches, per-line code-pattern validation, and PaintRack
  CSV import/export with a diff preview
- **Color-Match Studio**: match a reference photo against your shelf — a
  value ladder, hue ranking, and glaze/wash suggestions, each with a
  confidence band (never auto-applied); eyedropper sampling and automatic
  palette overview
- **Guides**: author from scratch (structured editor with drag-to-reorder
  tabs/phases/steps/swatches) or import an HTML guide with a paint-resolution
  step for anything unrecognized. Mix swatches, validation/publish gates,
  per-guide theming, print/PDF export (with optional reward stamping and
  multi-guide bundle export), and model-linked badges

## Scan

Parallel scan (up to 4 creator directories concurrently), incremental
(mtime-based skip of unchanged folders), cancellable, auto-refreshing
Library on completion. Tag index stays in sync via a normalized table for
fast filtering.

## Data Management

Settings → Data Management: download a backup snapshot, run a health check
(SQLite integrity + repair), restore from backup (also how you migrate
machines), or reset the whole index. Backups cover the catalog only — your
STL files on disk are never touched.

## AI-assisted features (all opt-in, all review-then-confirm)

- **AI Organize** — LLM-backed part-type/unit categorization suggestions for
  STL files; never auto-applied
- **AI-assisted painting guide generation** — draft a guide from your Paint
  Shelf, review, then publish

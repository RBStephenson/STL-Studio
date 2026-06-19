# STL Library

[![Release](https://github.com/RBStephenson/STL-Inventory/actions/workflows/release.yml/badge.svg)](https://github.com/RBStephenson/STL-Inventory/actions/workflows/release.yml)
[![Build Check](https://github.com/RBStephenson/STL-Inventory/actions/workflows/build-check.yml/badge.svg)](https://github.com/RBStephenson/STL-Inventory/actions/workflows/build-check.yml)
[![Tests](https://github.com/RBStephenson/STL-Inventory/actions/workflows/tests.yml/badge.svg)](https://github.com/RBStephenson/STL-Inventory/actions/workflows/tests.yml)
[![Wiki](https://img.shields.io/badge/docs-Wiki-2496ED?logo=github&logoColor=white)](https://github.com/RBStephenson/STL-Inventory/wiki)
&nbsp;
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

Local web app for cataloguing, browsing, and managing an STL file library.

📖 **User documentation:** the **[STL Library Wiki](https://github.com/RBStephenson/STL-Inventory/wiki)** is the canonical user guide.
🗺️ **What's coming next:** [ROADMAP.md](ROADMAP.md)


[Getting Started](https://github.com/RBStephenson/STL-Inventory/wiki/Getting-Started) ·
[Feature Guide](https://github.com/RBStephenson/STL-Inventory/wiki/Feature-Guide) ·
[Scanning & Folder Structure](https://github.com/RBStephenson/STL-Inventory/wiki/Scanning-and-Folder-Structure) ·
[Troubleshooting](https://github.com/RBStephenson/STL-Inventory/wiki/Troubleshooting-and-FAQ)

> The wiki is generated from the in-repo [`docs/`](docs/README.md) folder (the single source of truth, which also backs the in-app **Help** page).

## Installation

### Standalone (recommended for most users — no Docker needed)

1. Go to the [Releases page](https://github.com/RBStephenson/STL-Inventory/releases) and download the file for your OS:
   - **Windows**: `stl-library-windows.exe`
   - **Linux**: `stl-library-linux`

2. Run the file. Your browser will open automatically to `http://localhost:8484`.

3. Go to **Settings** and add the folder paths where your STL files live.

4. Click **Scan Library** — models appear within a few minutes.

Your library database is stored in your user data folder and survives app updates:
- **Windows**: `%LOCALAPPDATA%\STL-Inventory\`
- **macOS**: `~/Library/Application Support/STL-Inventory/`
- **Linux**: `~/.local/share/stl-inventory/`

> **Linux note**: You may need to mark the binary as executable before running it: `chmod +x stl-library-linux`

---

### Docker (for advanced users)

1. Copy `.env.example` to `.env` and set your drive path (forward slashes, even
   on Windows):
   ```
   STL_DRIVE_1=D:/3D STLs
   ```

2. Start everything:
   ```
   docker compose up --build
   ```

3. Open **http://localhost** in your browser.

4. Click **Scan Library** to index your files.

> Got models on more than one drive, or need to change mounts? See
> [docs/docker.md](docs/docker.md) — Docker can't be configured purely from the
> Settings page the way the standalone app can.

## Disk Structure Expected

```
<drive root>/
  <Creator Name>/
    <Model Name>/
      *.stl / *.3mf / *.obj
      *.jpg / *.png       ← first image used as thumbnail
```

A folder is only indexed as a model if it contains 3D files.

## Features

### Library
- Grid view with search, filter by creator (include or exclude), site, tag (include or exclude), NSFW flag, thumbnail presence, review status, and star rating
- **Hide printed** chip excludes already-printed models while keeping variant grouping on; **negative tag filter** (click a tag twice) excludes by tag
- Filter presets saved server-side; all filter state lives in the URL
- **Variant grouping** — folders that share a parent character (e.g. `Full_cutted`, `No_cuts`, `Semi_cutted` under `Akuma/`) are collapsed into a single group card with a variant count badge; click to open the group and select individual variants
- **Fix grouping** — drag a card onto another from the same creator to group them, or use **Set group** on a model / **Move to group** in a group view; overrides persist across rescans
- Pagination with jump-to-page input (Prev / page / Next)

### Triage Queue (`/triage`)
- Keyboard-driven review of flagged models
- `→` / Space = dismiss, `S` = skip, `←` = back
- Navbar shows live needs_review count badge

### Model Detail
- View and edit tags, metadata, source URL, NSFW flag
- **Inline tag editing** — add or remove tags directly from the detail view without opening the full edit form
- Image picker for choosing the thumbnail from the model's folder
- STL preview (3D viewer)
- **Part labeling** — tag each STL file with a part category (head, right arm, base, weapon, etc.) using a free-text input with common suggestions

### Favorites & Print Queue
- ★ Favorite models, 🖨 queue them to print, and ✓ mark them printed — all
  toggleable from a card or the model header
- The **Queue** page is a drag-to-reorder print list (favorites float to the
  top) with a live count badge in the nav and a **Recently Printed** history

### Kit Builder
- Launched from any model's detail page
- Groups all STL files in the model by their part label
- Click to select one file per part group to assemble a character build
- Sticky build summary with a **Copy list** button (copies selected filenames to clipboard)
- Uncategorized files shown at the bottom

### Bulk Tag Editor
- Checkbox-select multiple models in the Library grid
- Floating bar to add or remove tags across the selection at once

### Collections
- Group models into named sets independent of tags/creators (projects, wishlists, etc.)
- Create / rename / delete from the Collections page; add a model from its detail panel, or bulk-add from the Library selection bar
- Stored in the database and included in every backup

### Storefront Enrichment
- Paste a Gumroad, Cults3D, MyMiniFactory, or Loot Studios creator URL
- Fuzzy-matches scraped listings against local models and bulk-applies metadata (source URL, thumbnail, external ID)

### Painting Guides module
Enable under **Settings → Painting Guides** — adds **Guides** and **Paint Shelf** to the nav.

**Paint Shelf** — opt-in paint inventory: search/filter by brand, line, finish, and owned state, with color chips for swatches. Per-line **code patterns** (regex) validate paint codes on entry. **PaintRack CSV import/export** with a diff preview (never a blind overwrite); optional `Color` column (`#RRGGBB`, `"rgb(r,g,b)"`, or `"hsv(h,s,v)"`) pre-populates swatches on import.

**Painting Guides** — step-by-step guides tied to your Paint Shelf:
- Import an HTML guide file (click or drag-and-drop). Unresolved paints trigger a **Paint resolution** step — map each to a shelf paint, force-add it, or skip — so nothing is silently dropped.
- **Mix swatches** (*Paint A + Paint B, 3:1*) import, render as blended chips, and round-trip cleanly.
- In-app structured editor for tabs, phases, steps, and swatches.
- **Print** or **Export PDF** the whole guide in one pass.
- **Model links** — guides appear as a badge on Library cards and a button on model detail pages.

### Scan
- **Parallel** — scans up to 4 creator directories concurrently for faster indexing on large libraries
- Incremental — skips unchanged folders (mtime check), caches STL file walks
- Cancel button; Library auto-refreshes on completion
- On each rescan, `needs_review` is cleared for any model that already has indexed STL files (reduces false-positive review queue)
- Tag index kept in sync via normalized `model_tags` table for fast filtering

### In-app Help
- A built-in **Help & Guide** page plus contextual "?" deep-links on each screen, mirroring the docs in [docs/](docs/README.md)

### Data Management
- **Settings → Data Management** to back up, restore, or reset the catalog
- **Download Backup** saves a consistent snapshot (`.db`) of your index — tags,
  favorites, and print queue
- **Restore** swaps in a validated backup (also how you migrate to a new
  machine); **Reset** wipes the index to empty
- Backups only cover the index — your STL files on disk are never touched

## Development

Both frontend and backend are baked into their images — rebuild after any code change:
```
docker compose build backend && docker compose up -d backend
docker compose build frontend && docker compose up -d frontend
```

Or rebuild both at once:
```
docker compose build && docker compose up -d
```

For backend development, the `docker-compose.dev.yml` overlay bind-mounts the
source and runs uvicorn with `--reload`, so Python edits take effect without a
rebuild:
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```
(The base image runs without `--reload` — it's a dev-only flag.)

## Tests

The backend suite lives in `backend/tests` (pytest, in-memory SQLite — no
external services needed). Run it locally:
```
cd backend
pip install -r requirements-test.txt
pytest
```
Every PR to `main` (and every push to `main`) runs the suite via the **Tests**
workflow, so logic regressions are caught alongside the binary **Build Check**.

## Releasing

Standalone executables (Windows/macOS/Linux) are built by GitHub Actions.

**One-click release:** Go to the **Actions** tab → **Release** → **Run workflow**, pick
`patch`/`minor`/`major`. It computes the next version, creates the tag, and builds +
publishes a GitHub Release with auto-generated notes.

**Manual tag** (alternative): `git tag v1.2.3 && git push origin v1.2.3` triggers the
same build.

Every PR to `main` runs **Build Check**, which compiles all three platform binaries
(without releasing) so packaging breaks are caught before merge.

## Ports

| Service | Port |
|---------|------|
| App (nginx) | 80 |
| Backend (FastAPI) | 8000 |
| Frontend (Vite dev) | 3000 |

## Stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy + SQLite
- **Frontend**: React 18 + Vite + TypeScript + TailwindCSS
- **Proxy**: nginx

## About & Support

### Like STL Library?

STL Library started because I had a problem: way too many STL files and no good
way to keep track of them all. What began as a personal tool turned into
something I thought other makers, painters, gamers, and hobbyists might find
useful too.

If STL Library has helped you organize your collection, rediscover forgotten
models, or simply spend less time hunting through folders, please consider
supporting the project through
[Patreon](https://www.patreon.com/BrentStephenson) or
[Buy Me a Coffee](https://www.buymeacoffee.com/brent_the_programmer).

Your support helps fund continued development, but it also helps keep resin in
the printer, paint on the hobby desk, and supports my family as I balance
software development, creativity, and caregiving.

There's absolutely no obligation—STL Library is, and will remain, a passion
project. But every bit of support is deeply appreciated and helps me continue
building tools and content for the community.

Thank you for being here, and happy printing!

— Brent the Programmer

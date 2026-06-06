# STL Inventory

[![Release](https://github.com/RBStephenson/STL-Inventory/actions/workflows/release.yml/badge.svg)](https://github.com/RBStephenson/STL-Inventory/actions/workflows/release.yml)
[![Build Check](https://github.com/RBStephenson/STL-Inventory/actions/workflows/build-check.yml/badge.svg)](https://github.com/RBStephenson/STL-Inventory/actions/workflows/build-check.yml)
[![Tests](https://github.com/RBStephenson/STL-Inventory/actions/workflows/tests.yml/badge.svg)](https://github.com/RBStephenson/STL-Inventory/actions/workflows/tests.yml)
&nbsp;
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

Local web app for cataloguing, browsing, and managing an STL file library.

📖 **User documentation:** see the **[docs/](docs/README.md)** folder —
🗺️ **What's coming next:** [ROADMAP.md](ROADMAP.md)


[Getting Started](docs/getting-started.md) ·
[Feature Guide](docs/features.md) ·
[Scanning & Folder Structure](docs/scanning-and-folders.md) ·
[Troubleshooting](docs/troubleshooting.md).

## Installation

### Standalone (recommended for most users — no Docker needed)

1. Go to the [Releases page](https://github.com/RBStephenson/STL-Inventory/releases) and download the file for your OS:
   - **Windows**: `stl-inventory-windows.exe`
   - **macOS**: `stl-inventory-macos`
   - **Linux**: `stl-inventory-linux`

2. Run the file. Your browser will open automatically to `http://localhost:8484`.

3. Go to **Settings** and add the folder paths where your STL files live.

4. Click **Scan Library** — models appear within a few minutes.

Your library database is stored in your user data folder and survives app updates:
- **Windows**: `%LOCALAPPDATA%\STL-Inventory\`
- **macOS**: `~/Library/Application Support/STL-Inventory/`
- **Linux**: `~/.local/share/stl-inventory/`

> **macOS note**: You may need to right-click → Open the first time to bypass Gatekeeper, since the binary isn't notarized.

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
- Grid view with search, filter by creator, site, tag, NSFW flag, thumbnail presence, and review status
- Filter presets saved in localStorage; all filter state lives in the URL
- **Variant grouping** — folders that share a parent character (e.g. `Full_cutted`, `No_cuts`, `Semi_cutted` under `Akuma/`) are collapsed into a single group card with a variant count badge; click to open the group and select individual variants
- Pagination with jump-to-page input (Prev / page / Next)

### Triage Queue (`/triage`)
- Keyboard-driven review of flagged models
- `→` / Space = dismiss, `S` = skip, `←` = back
- Navbar shows live needs_review count badge

### Model Detail
- View and edit tags, metadata, source URL, NSFW flag
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

### Storefront Enrichment
- Paste a Gumroad, Cults3D, or MyMiniFactory creator URL
- Fuzzy-matches scraped listings against local models and bulk-applies metadata (source URL, thumbnail, external ID)

### Scan
- **Parallel** — scans up to 4 creator directories concurrently for faster indexing on large libraries
- Incremental — skips unchanged folders (mtime check), caches STL file walks
- Cancel button; Library auto-refreshes on completion
- On each rescan, `needs_review` is cleared for any model that already has indexed STL files (reduces false-positive review queue)
- Tag index kept in sync via normalized `model_tags` table for fast filtering

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

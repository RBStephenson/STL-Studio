# STL Inventory

Local web app for cataloguing, browsing, and managing a large STL file library (12,500+ models).

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

## Quick Start

1. Copy `.env.example` to `.env` and set your drive paths:
   ```
   STL_DRIVE_1=D:/3D STLs
   STL_DRIVE_2=E:/3D STLs
   ```

2. Start everything:
   ```
   docker compose up --build
   ```

3. Open **http://localhost** in your browser.

4. Click **Scan Library** to index your files.

## Disk Structure Expected

```
<drive root>/
  <Creator Name>/
    <Model Name>/
      config.orynt3d      ← parsed automatically if present
      *.stl / *.3mf
      *.jpg / *.png       ← first image used as thumbnail
```

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

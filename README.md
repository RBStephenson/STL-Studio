# STL Inventory

Local web app for cataloguing, browsing, and managing a large STL file library (12,500+ models).

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

- **Library** — grid view with search, filter by creator, site, tag, NSFW flag, thumbnail presence, and review status; filter presets saved in localStorage; all filter state in the URL
- **Triage queue** (`/triage`) — keyboard-driven review of flagged models; `→`/Space = dismiss, `S` = skip, `←` = back
- **Model detail** — view/edit tags, metadata, and STL preview; image picker for thumbnail selection
- **Bulk tag editor** — checkbox-select multiple models in the grid, then add or remove tags via floating bar
- **Storefront enrichment** — paste a Gumroad, Cults3D, or MMF creator URL; fuzzy-matches scraped listings against local models and bulk-applies metadata
- **Incremental scan** — skips unchanged folders (mtime check), caches STL file walks, supports cancel; Library auto-refreshes on completion
- **Tag index** — normalized `model_tags` table keeps tag filtering fast regardless of library size

## Development

After any Python/backend change, rebuild the backend image:
```
docker compose build backend && docker compose up -d backend
```

Frontend changes are bind-mounted and hot-reload automatically during development.

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

# STL Studio — User Guide

A practical walkthrough for getting set up and using STL Studio day to day.
For the full reference, see [docs/](docs/README.md) (also published as the
[GitHub Wiki](https://github.com/RBStephenson/STL-Studio/wiki)); for a quick
feature-by-feature list, see [FEATURES.md](FEATURES.md).

## 1. Install

Two ways to run it:

| Option | Best for |
|---|---|
| **Standalone** | Most people — no Docker, single download |
| **Docker** | Already running Docker, want the containerized version |

There is no supported prebuilt macOS build — use Docker on a Mac.

### Standalone

1. Go to [Releases](https://github.com/RBStephenson/STL-Studio/releases) and
   download for your OS:
   - **Windows**: `STL-Studio-Setup-<version>.exe`
   - **Linux**: `stl-studio-linux`
2. **Windows**: run the installer, launch **STL Studio** from the Start
   menu. It's unsigned for now — SmartScreen may warn on first run: click
   **More info → Run anyway**.
   **Linux**: `chmod +x stl-studio-linux`, run it, then open
   `http://localhost:8484` (or pass `--open-browser` to have it open for
   you, `--port <n>` for a different port).
3. Open **Settings** and add the folder path(s) where your STL files live.
4. Click **Scan Library**. First scan can take a few minutes on a large
   collection — models appear as they're found, and you can keep using the
   app while it runs.

Your catalog database lives in your user-data folder and survives updates:

| OS | Location |
|---|---|
| Windows | `%LOCALAPPDATA%\STL-Inventory\` |
| Linux | `~/.local/share/stl-inventory/` |

### Docker

1. Copy `.env.example` to `.env`, set your drive path(s) (forward slashes
   even on Windows):
   ```
   STL_DRIVE_1=D:/3D STLs
   STL_DRIVE_2=E:/More STLs   # optional
   STL_ROOTS=/mnt/drive1,/mnt/drive2
   ```
2. `docker compose up --build`
3. Open `http://localhost`, click **Scan Library**.

Drives are mounted read-only in Docker — the app can never modify your
source files. More than two drives, or need different mounts? See
[docs/docker.md](docs/docker.md).

### Expected disk layout

```
<drive root>/
  <Creator Name>/
    <Model Name>/
      *.stl / *.3mf / *.obj
      *.jpg / *.png       ← first image becomes the thumbnail
```

A folder is only indexed as a model if it actually contains a 3D file. See
[docs/scanning-and-folders.md](docs/scanning-and-folders.md) if your layout
doesn't match this.

## 2. Everyday workflow

### Browse and organize

- **Library** is your home screen — search, filter by creator/tag/site/
  rating, and page through your collection. Filters live in the URL, so you
  can bookmark or share a view.
- Models that look like format variants of the same character (e.g.
  `Full_cutted` / `No_cuts` / `Semi_cutted` under one folder) automatically
  collapse into a single grouped card. Wrong grouping? Drag one card onto
  another from the same creator to fix it — the fix sticks across rescans.
- Click into **Model Detail** to edit tags/metadata, pick a thumbnail, and
  preview the STL in 3D.

### Print planning

- ★ favorite a model, 🖨 add it to the **print queue**, ✓ mark it printed
  once done.
- The **Queue** page is a drag-to-reorder list — rearrange print order,
  favorites float to the top, and a **Recently Printed** history tracks
  what's already made.
- For multi-part figures, open **Kit Builder** from the model's detail page:
  it groups every STL by part label so you can pick exactly one file per
  part and copy the resulting filename list straight into your slicer.

### Cleaning up a messy import

1. Drop the new files anywhere — they don't need to already match your
   library's folder structure.
2. Open **Import Folder** (`/import`) and point it at the loose folder.
   **Import Preview** shows one card per subfolder ("pack").
3. Fill in creator/character/title/tags per pack (or use the **Bulk
   Editor**'s Enrich mode across many models at once), pick a destination
   **Library**.
4. **Move N imported packs → library** files everything into place using
   the reorganize engine — this step is undoable and needs the Reorganize
   Library flag on plus a writable destination.

Already have a big pile of unsorted models in your library? **Reorganize
Library** (Settings-gated) previews and applies a folder template
(`{creator}/{character}/{title}` by default) across your whole collection,
not just fresh imports.

### Filling in metadata automatically

If a model came from Gumroad, Cults3D, MyMiniFactory, or Loot Studios: paste
the creator's page URL into **Storefront Enrichment**. It matches scraped
listings against your local models and bulk-fills title, description, tags,
category, license, thumbnail, and source URL — across every variant in a
group at once.

### Painting

- **Paint Shelf** (always on) is your paint inventory — track what you own,
  import/export CSV in PaintRack format.
- **Color-Match Studio** takes a reference photo and suggests a shadow →
  mid → highlight ramp from your own shelf, plus glaze/wash ideas — every
  suggestion is a starting point to eyeball, not an auto-apply.
- Turn on **Settings → Painting Guides** to unlock **Guides**: author a
  step-by-step paint recipe from scratch, or import an existing HTML guide
  (any paint it can't recognize gets a resolution step before import
  finishes). Export to print or PDF when done.

### Keeping your data safe

**Settings → Data Management**:
- **Download Backup** — a point-in-time snapshot of your catalog (tags,
  favorites, queue, everything except the STL files themselves)
- **Check Health** / **Repair Database** — integrity check, and a
  conservative repair if something's off
- **Restore** — load a backup (this is also how you move to a new machine)
- **Reset** — wipe the catalog back to empty

Before any major upgrade, take a backup. STL Studio also auto-snapshots
your database before a schema upgrade and restores it automatically if the
upgrade fails.

## 3. Upgrading

Direct upgrades are supported from **v0.18.0 or newer** — just install the
new version, and the database schema upgrades itself on first launch. Your
STL files are never touched by this. Downgrading after a schema upgrade
isn't supported; if you need to roll back, reinstall the older version and
restore the pre-upgrade backup snapshot STL Studio took automatically (kept
in the `backups` folder, three newest retained).

## 4. Where to go next

- [docs/features.md](docs/features.md) — every screen, in full detail
- [docs/scanning-and-folders.md](docs/scanning-and-folders.md) — how the
  scanner reads your folders and auto-tags models
- [docs/troubleshooting.md](docs/troubleshooting.md) — models not showing
  up, wrong thumbnails, rescan vs. full scan, and other common questions
- [docs/support-policy.md](docs/support-policy.md) — supported platforms,
  upgrade/rollback limits, diagnostic privacy
- In-app: the **Help** page and the "?" links on each screen mirror these
  docs contextually

# Docker — Drive Mounts & Configuration

Running STL Studio in Docker works a little differently from the standalone
app when it comes to telling it where your models live. A container can only see
the folders you **mount into it** — so unlike standalone, you can't just type any
host path into the Settings page and have it work. This page explains how drive
mounts are wired and how to add or change them.

> **Just want point-and-click?** Use the **[standalone app](getting-started.md#standalone-recommended)**
> instead. It sees your host filesystem directly, so you add and change library
> folders entirely from the Settings page — no file editing, no container
> mounts. Docker is the advanced option.

---

## How a drive mount is wired

There are two things you need to set for Docker mode to see your library:

| Where | What it does |
|-------|--------------|
| `.env` → `LIBRARY_DIR` | The **host** path to your main library (e.g. `F:/3DModelLibrary`). |
| `.env` → `IMPORT_DIR` | The **host** path where you drop zips/folders to import (optional). |

The `docker-compose.yml` mounts these into the container at fixed paths:

- `LIBRARY_DIR` → `/library` (your scanned model library)
- `IMPORT_DIR` → `/import` (your import staging area)

On first boot the backend seeds `/library` as a scan root automatically — you
don't need to add it in Settings.

---

## Setting up your `.env`

Copy `.env.example` to `.env` and fill in your paths:

```
LIBRARY_DIR=F:/3DModelLibrary
IMPORT_DIR=F:/Downloads/STL-Imports
```

> **Windows / macOS paths:** use **forward slashes** in `.env`
> (`D:/3D STLs`, not `D:\3D STLs`). On macOS your drive lives under
> `/Volumes`, e.g. `LIBRARY_DIR=/Volumes/MyDrive/STLs`.

Then start the stack:

```
docker compose up -d
```

---

## Why a path typed into Settings must already be mounted

In Docker mode the Settings page and folder browser operate **inside the
container**, so they show container paths like `/library/...` — not host
paths like `F:/...`. A scan root you add there must point at something that is
already mounted into the container. Typing a raw host path such as
`F:/3DModelLibrary` will not work, because the container has no `F:` drive.

The rule of thumb: **mount it in `docker-compose.yml` first, then point Settings
at the container path.**

---

## Adding a second library drive

If your models span multiple drives, add another volume mount to
`docker-compose.yml` and point Settings at the new container path.

1. **`.env`** — add the second host path:

   ```
   LIBRARY_DIR=F:/3DModelLibrary
   LIBRARY_DIR_2=G:/MoreModels
   ```

2. **`docker-compose.yml`** — add a volume mount for it:

   ```yaml
   services:
     backend:
       volumes:
         - ./data:/data
         - "${LIBRARY_DIR}:/library"
         - "${LIBRARY_DIR_2}:/library2"   # add this
         - "${IMPORT_DIR}:/import"
   ```

3. **Recreate the container** so the new mount takes effect:

   ```
   docker compose up -d
   ```

4. **Add the new root in Settings** — go to Settings → Library Roots and add
   `/library2`. The scanner will pick it up on the next scan.

> **Heads-up:** changing `docker-compose.yml` requires a `docker compose up -d`
> to recreate the container — a running container does not pick up new mounts on
> its own. (Merging code changes also requires a rebuild; see
> [Troubleshooting](troubleshooting.md).)

---

## See also

- **[Getting Started → Docker](getting-started.md#docker-advanced)** — the quick
  start for spinning everything up.
- **[Scanning & Folder Structure](scanning-and-folders.md)** — what the scanner
  expects to find under each mounted root.

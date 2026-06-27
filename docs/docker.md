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

## How drive mounts are wired

There are three things you need to set for Docker mode to see your library:

| Where | What it does |
|-------|--------------|
| `.env` → `STL_DRIVE_1` | The **host** path to your first library drive (e.g. `F:/3DModelLibrary`). |
| `.env` → `STL_DRIVE_2` | The **host** path to a second drive (optional). |
| `.env` → `STL_ROOTS` | Comma-separated **container** paths to auto-register as scan roots on first boot. |

The `docker-compose.yml` mounts these into the container at fixed paths:

- `STL_DRIVE_1` → `/mnt/drive1`
- `STL_DRIVE_2` → `/mnt/drive2`
- `IMPORT_DIR` → `/import` (your import staging area — optional)

On first boot the backend seeds every path listed in `STL_ROOTS` as a scan root
automatically — you don't need to add them in Settings.

---

## Setting up your `.env`

Copy `.env.example` to `.env` and fill in your paths:

```
STL_DRIVE_1=F:/3DModelLibrary
STL_DRIVE_2=G:/MoreModels
STL_ROOTS=/mnt/drive1,/mnt/drive2
IMPORT_DIR=F:/Downloads/STL-Imports
```

> **Windows / macOS paths:** use **forward slashes** in `.env`
> (`D:/3D STLs`, not `D:\3D STLs`). On macOS your drive lives under
> `/Volumes`, e.g. `STL_DRIVE_1=/Volumes/MyDrive/STLs`.

Then start the stack:

```
docker compose up -d
```

---

## Why a path typed into Settings must already be mounted

In Docker mode the Settings page and folder browser operate **inside the
container**, so they show container paths like `/mnt/drive1/...` — not host
paths like `F:/...`. A scan root you add there must point at something that is
already mounted into the container. Typing a raw host path such as
`F:/3DModelLibrary` will not work, because the container has no `F:` drive.

The rule of thumb: **mount it in `docker-compose.yml` first, then point Settings
at the container path.**

---

## Adding a third (or more) library drive

The default `docker-compose.yml` supports two drives out of the box. To add more:

1. **`.env`** — add the new host path:

   ```
   STL_DRIVE_3=H:/EvenMoreModels
   ```

2. **`docker-compose.yml`** — add a volume mount under `backend.volumes`:

   ```yaml
   - "${STL_DRIVE_3:-/dev/null}:/mnt/drive3"
   ```

   And add `STL_DRIVE_3` to the `environment` block:

   ```yaml
   environment:
     - STL_DRIVE_3=${STL_DRIVE_3:-}
   ```

3. **`.env`** — add `/mnt/drive3` to `STL_ROOTS`:

   ```
   STL_ROOTS=/mnt/drive1,/mnt/drive2,/mnt/drive3
   ```

4. **Recreate the container** so the new mount takes effect:

   ```
   docker compose up -d
   ```

The new root is seeded automatically on next boot — no manual Settings step needed.

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

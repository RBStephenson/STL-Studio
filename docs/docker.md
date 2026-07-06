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

## Pre-built images

Every release publishes backend and frontend images to the GitHub Container
Registry (GHCR), so you don't have to build from source:

- `ghcr.io/rbstephenson/stl-inventory-backend`
- `ghcr.io/rbstephenson/stl-inventory-frontend`

**Available tags**

| Tag | Points at |
|-----|-----------|
| `latest` | the newest tagged release |
| `1.2.3` / `1.2` / `1` | a specific release — pin `1.2.3` for reproducibility |
| `main` | the latest commit on `main` (moving, may be unstable) |
| `sha-<hash>` | one specific commit build |

Pull them directly:

```
docker pull ghcr.io/rbstephenson/stl-inventory-backend:latest
docker pull ghcr.io/rbstephenson/stl-inventory-frontend:latest
```

> The bundled `docker-compose.yml` builds the images from source
> (`docker compose up --build`). To run the published images instead, add an
> `image:` key to the `backend` and `frontend` services pointing at the tags
> above.

---

## Networking: the frontend is the single entry point

The **frontend** container serves the web UI **and** reverse-proxies `/api` to
the backend. It is the only container you need to expose — you browse to it, and
it forwards API calls internally. There is no separate proxy container.

This works because the app calls the API at the relative path `/api`. The
frontend's nginx routes `/api/*` to the backend and serves the single-page app
for everything else.

### `BACKEND_ORIGIN`

The frontend finds the backend via the `BACKEND_ORIGIN` environment variable:

| | |
|---|---|
| **Default** | `http://backend:8000` (matches the `backend` service in `docker-compose.yml`) |
| **Override when** | your backend service/container has a different name, e.g. `BACKEND_ORIGIN=http://stl-inventory-backend:8000` |

It must resolve on the Docker network the two containers share (a compose
project puts them on one network automatically, so the service name works).

> **`VITE_API_URL` does nothing.** It was only read by the old dev-server image.
> The production image ignores it — remove it from your compose. Routing is
> controlled entirely by `BACKEND_ORIGIN`.

### Behind your own reverse proxy (Nginx Proxy Manager, Traefik, Caddy…)

Point your proxy at the **frontend** container as a single upstream — do **not**
try to split `/api` yourself, and do not expose the backend to your proxy. The
frontend already handles the `/api` split internally.

```yaml
# Two containers; only the frontend is published. Your external proxy forwards
# everything for the hostname to the frontend's published port.
services:
  stl-inventory-backend:
    image: ghcr.io/rbstephenson/stl-inventory-backend:latest
    environment:
      - DATABASE_URL=sqlite:////data/stl_inventory.db
      - STL_ROOTS=/mnt/drive1
    volumes:
      - /host/data:/data
      - /host/library:/mnt/drive1

  stl-inventory-frontend:
    image: ghcr.io/rbstephenson/stl-inventory-frontend:latest
    environment:
      - BACKEND_ORIGIN=http://stl-inventory-backend:8000   # match the backend name
    ports:
      - "3000"          # publish/forward this to your reverse proxy
    depends_on:
      - stl-inventory-backend
```

A `405` when saving settings, or a folder browser that "can't open" anything,
almost always means `/api` isn't reaching the backend — check that you're
pointing at the **frontend** (not the backend) and that `BACKEND_ORIGIN` names
your backend correctly.

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

# Docker — Drive Mounts & Configuration

Running STL Library in Docker works a little differently from the standalone
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

There are three places a drive has to line up for Docker mode to see it:

| Where | What it does |
|-------|--------------|
| `.env` → `STL_DRIVE_1` | The **host** path to your drive (e.g. `F:/3DModelLibrary`). |
| `docker-compose.yml` → `volumes` | Mounts that host path to a **container** path (`/mnt/drive1`), read-only. |
| `docker-compose.yml` → `STL_ROOTS` | Tells the scanner which **container** paths to walk (`/mnt/drive1`). |

The default `docker-compose.yml` ships with **one** drive wired up:

```yaml
services:
  backend:
    volumes:
      - ./data:/data
      - "${STL_DRIVE_1:-/mnt/drive1}:/mnt/drive1:ro"
    environment:
      - STL_ROOTS=/mnt/drive1
      - STL_DRIVE_1=${STL_DRIVE_1:-}
```

So you set one value in `.env`:

```
STL_DRIVE_1=F:/3DModelLibrary
```

> **Windows / macOS paths:** use **forward slashes** in `.env`
> (`D:/3D STLs`, not `D:\3D STLs`). On macOS your drive lives under
> `/Volumes`, e.g. `STL_DRIVE_1=/Volumes/MyDrive/STLs`.

Your drives are always mounted **read-only** (`:ro`) — the app can browse and
index them but can never modify your source files.

---

## Why a path typed into Settings must already be mounted

In Docker mode the Settings page and folder browser operate **inside the
container**, so they show container paths like `/mnt/drive1/...` — not host
paths like `F:/...`. A scan root you add there must point at something that is
already mounted into the container (i.e. under `/mnt/drive1`). Typing a raw host
path such as `F:/3DModelLibrary` will not work, because the container has no
`F:` drive.

The rule of thumb: **mount it in `docker-compose.yml` first, then point Settings
at the container path.**

---

## Host-path translation (Location / "Open folder")

So the app can still show you the *real* location of a model — and so the
"Open folder" action makes sense — the backend translates container paths back
to host paths using the `STL_DRIVE_1` value from your `.env`:

```
/mnt/drive1/Creator/Model   →   F:/3DModelLibrary/Creator/Model
```

This is why `STL_DRIVE_1` is passed into the backend environment as well as used
for the volume mount: the volume makes the files *visible*, and the env var lets
the app *name* them in host terms. If you leave `STL_DRIVE_1` unset, the app
falls back to showing the container path.

---

## Adding another drive

Say you keep models on a second drive and want both indexed. You need to add the
new drive in **all three** places, then recreate the container.

1. **`.env`** — add the host path:

   ```
   STL_DRIVE_1=F:/3DModelLibrary
   STL_DRIVE_2=G:/MoreModels
   ```

2. **`docker-compose.yml`** — add a volume mount and pass the env var, and add
   the new container path to `STL_ROOTS`:

   ```yaml
   services:
     backend:
       volumes:
         - ./data:/data
         - "${STL_DRIVE_1:-/mnt/drive1}:/mnt/drive1:ro"
         - "${STL_DRIVE_2:-/mnt/drive2}:/mnt/drive2:ro"   # add this
       environment:
         - STL_ROOTS=/mnt/drive1,/mnt/drive2              # add /mnt/drive2
         - STL_DRIVE_1=${STL_DRIVE_1:-}
         - STL_DRIVE_2=${STL_DRIVE_2:-}                   # add this
   ```

3. **Recreate the container** so the new mount and env take effect:

   ```
   docker compose up -d
   ```

The backend already understands `/mnt/drive2` ↔ `STL_DRIVE_2` for host-path
translation, so the Location/Open-folder display works for the second drive too.
Add `/mnt/drive3`, `/mnt/drive4`, … the same way if you have more.

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

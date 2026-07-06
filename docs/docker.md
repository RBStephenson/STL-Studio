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

Every successful `main` build and every release publishes backend and frontend
images to the GitHub Container Registry (GHCR), so you don't have to build from
source:

- `ghcr.io/rbstephenson/stl-inventory-backend`
- `ghcr.io/rbstephenson/stl-inventory-frontend`

**Available tags**

| Tag | Points at |
|-----|-----------|
| `latest` | the newest successful `main` build (moving, may be unstable) |
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
      - TRUSTED_HOSTS=stl.example.com     # ← your public hostname (see below)
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

### `TRUSTED_HOSTS` — required behind a reverse proxy

The backend rejects **writes** (adding a folder, saving settings, scanning…)
from any hostname it doesn't trust — a CSRF / DNS-rebinding guard that defaults
to **localhost only**. Accessed via a domain like `stl.example.com`, every write
comes back as **`403 Cross-origin request blocked`** or **`Request Host not
allowed`** until you allowlist that hostname:

```yaml
environment:
  - TRUSTED_HOSTS=stl.example.com        # comma-separated for multiple
```

Set it to the hostname(s) you browse to. Reads work without it; only writes are
gated. Localhost stays trusted regardless, and unlisted domains stay blocked.

### Troubleshooting

- **`405` on save, or folder browser "can't open" anything** → `/api` isn't
  reaching the backend. Point your proxy at the **frontend** (not the backend),
  and check `BACKEND_ORIGIN` names your backend service.
- **`403 Cross-origin request blocked` / `Request Host not allowed`** → set
  `TRUSTED_HOSTS` to your public hostname (above).

---

## For NAS servers (TrueNAS, Synology, Unraid…)

A complete, copy-paste example for a NAS behind a reverse proxy. Replace the
paths and hostname with your own; everything else is deployment-ready.

```yaml
services:
  stl-inventory-backend:
    image: ghcr.io/rbstephenson/stl-inventory-backend:latest
    container_name: stl-inventory-backend
    restart: unless-stopped
    environment:
      - DATABASE_URL=sqlite:////data/stl_inventory.db
      - STL_ROOTS=/mnt/drive1                 # container path seeded as a scan root
      - TRUSTED_HOSTS=stl.example.com         # the hostname you browse to
      - PYTHONUNBUFFERED=1
    volumes:
      # app DB + encryption key — MUST be a writable, persistent dataset
      - /mnt/pool/appdata/stl-inventory/data:/data
      # your STL library — this host path appears at /mnt/drive1 in the container
      - /mnt/pool/models/library:/mnt/drive1
      # optional import staging area
      - /mnt/pool/models/import:/import

  stl-inventory-frontend:
    image: ghcr.io/rbstephenson/stl-inventory-frontend:latest
    container_name: stl-inventory-frontend
    restart: unless-stopped
    environment:
      # must match the backend's service/container name and port
      - BACKEND_ORIGIN=http://stl-inventory-backend:8000
    ports:
      # host:container — point your reverse proxy at <nas-ip>:8080
      - "8080:3000"
    depends_on:
      - stl-inventory-backend
```

**The three knobs that make a NAS + reverse-proxy deployment work:**

| Setting | On | Value |
|---------|-----|-------|
| Volume mount `…:/mnt/drive1` | backend | your library dataset → `/mnt/drive1` |
| `STL_ROOTS` | backend | `/mnt/drive1` (the **container** path, not the host path) |
| `TRUSTED_HOSTS` | backend | the public hostname, e.g. `stl.example.com` |
| `BACKEND_ORIGIN` | frontend | `http://<backend-service-name>:8000` |

**Reverse proxy:** create one proxy host for your domain and forward it to the
**frontend** at `<nas-ip>:8080`. Do **not** add a separate `/api` rule — the
frontend serves the UI and proxies `/api` to the backend internally. Don't
publish the backend port at all.

**NAS dataset paths** differ by platform — use yours in place of `/mnt/pool/…`:

| NAS | Typical path prefix |
|-----|---------------------|
| TrueNAS SCALE | `/mnt/<pool>/…` |
| Synology | `/volume1/…` |
| Unraid | `/mnt/user/…` |

> **Private registry?** If you mirror the images (e.g. a self-hosted registry),
> swap `ghcr.io/rbstephenson/…` for your own path — the config is otherwise
> identical.

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

## Optional environment variables

**`LOG_LEVEL`** (backend) sets the initial log verbosity — one of `DEBUG`,
`INFO` (default), `WARNING`, `ERROR`, `CRITICAL`:

```yaml
services:
  backend:
    environment:
      - LOG_LEVEL=INFO
```

You can also change the level live in the UI under **Settings → Preferences →
Logging** — that value overrides `LOG_LEVEL` and persists across restarts. See
[Logging](features.md#logging).

**`STL_SECRET_KEY`** (backend) is **not** another API key — it's the
encryption key that protects the API keys/credentials you already entered in
Settings (AI provider keys, Cults3D, MyMiniFactory). Those are stored in the
database as ciphertext, never plaintext; `STL_SECRET_KEY` is what decrypts
them back into usable keys at runtime.

It's kept deliberately separate from the database itself: if the database file
ever leaks (a backup uploaded somewhere, a misconfigured volume, a stolen
disk), the ciphertext alone is useless without this key. If the key lived
*inside* the database it protects, that protection would be pointless — a
leak would hand over the lock and the key together.

It is **never written to a file** by the app. If unset, a key is generated in
memory for that process's lifetime only — the app still works, but every
restart forgets it, so anything encrypted with the old one becomes permanently
undecryptable (you'd just re-enter your API keys). Set a stable value once to
make your stored keys survive restarts/upgrades:

```yaml
services:
  backend:
    environment:
      - STL_SECRET_KEY=your-generated-key-here
```

Generate one with:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep this value itself somewhere safe (a password manager, alongside your
other infra secrets) — it's the one credential that isn't recoverable by
re-entering anything in the UI.

Keep this value secret and back it up — if it's lost, previously stored keys
become undecryptable and must be re-entered.

Tail the backend's output with `docker compose logs -f backend`.
`PYTHONUNBUFFERED=1` (already set in the shipped compose files) keeps log lines
from being buffered.

---

## See also

- **[Getting Started → Docker](getting-started.md#docker-advanced)** — the quick
  start for spinning everything up.
- **[Scanning & Folder Structure](scanning-and-folders.md)** — what the scanner
  expects to find under each mounted root.

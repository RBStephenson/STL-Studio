# Getting Started

There are two ways to run STL Inventory:

- **[Standalone](#standalone-recommended)** — a single downloadable app. No Docker, no setup. Recommended for most people.
- **[Docker](#docker-advanced)** — for people who already run Docker and want the containerized version.

---

## Standalone (recommended)

### 1. Download

Go to the [Releases page](https://github.com/RBStephenson/STL-Inventory/releases)
and download the file for your operating system:

| OS | File |
|----|------|
| Windows | `stl-inventory-windows.exe` |
| macOS | `stl-inventory-macos` |
| Linux | `stl-inventory-linux` |

### 2. Run it

Double-click (or run from a terminal). Your browser opens automatically to
**http://localhost:8484**.

> **macOS first run:** because the binary isn't notarized yet, macOS may block
> it. Right-click the file → **Open** → **Open** to bypass Gatekeeper the first
> time. After that it launches normally.

### 3. Tell it where your STLs are

Open the **Settings** page and add the folder path(s) where your model library
lives — for example `D:\3D STLs` or `/Volumes/MyDrive/STLs`. You can add more
than one (e.g. two external drives).

### 4. Scan

Click **Scan Library**. The first scan walks your whole library and can take a
few minutes for a large collection — models appear as they're found. You can
keep using the app while it runs, and there's a **Cancel** button if you need
to stop.

That's it. Your library database is stored in your user data folder and
survives app updates:

| OS | Location |
|----|----------|
| Windows | `%LOCALAPPDATA%\STL-Inventory\` |
| macOS | `~/Library/Application Support/STL-Inventory/` |
| Linux | `~/.local/share/stl-inventory/` |

---

## Docker (advanced)

If you prefer the containerized version:

### 1. Configure your drive

Copy `.env.example` to `.env` and set your drive path (use **forward slashes**,
even on Windows):

```
STL_DRIVE_1=D:/3D STLs
```

This mounts that folder into the container as the default library root. Got
models on **more than one drive**, or need to change where things are mounted?
See **[Docker — Drive Mounts & Configuration](docker.md)** for the full rundown
(adding extra drives, why Settings paths must be mounted first, and host-path
display).

### 2. Start everything

```
docker compose up --build
```

### 3. Open the app

Go to **http://localhost** in your browser, then click **Scan Library**.

| Service | Port |
|---------|------|
| App (nginx) | 80 |
| Backend (FastAPI) | 8000 |
| Frontend (Vite) | 3000 |

> In Docker mode your drives are mounted read-only into the container — the app
> can never modify your source files. To add more drives or change mounts, see
> **[Docker — Drive Mounts & Configuration](docker.md)**.

---

## Next steps

- Learn what every screen does in the **[Feature Guide](features.md)**.
- Understand how the scanner reads your folders in
  **[Scanning & Folder Structure](scanning-and-folders.md)** — worth a skim if
  your models are laid out in an unusual way.

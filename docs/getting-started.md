# Getting Started

There are two ways to run STL Studio:

- **[Standalone](#standalone-recommended)** — a single downloadable app. No Docker, no setup. Recommended for most people.
- **[Docker](#docker-advanced)** — for people who already run Docker and want the containerized version.

---

## Standalone (recommended)

### 1. Download

Go to the [Releases page](https://github.com/RBStephenson/STL-Inventory/releases)
and download the file for your operating system:

| OS | File |
|----|------|
| Windows | `stl-library-windows.exe` |
| macOS | `stl-library-macos` |
| Linux | `stl-library-linux` |

### 2. Run it

Double-click (or run from a terminal). On **Windows** the app opens in its own
desktop window. On **Linux** (and if anything goes wrong opening the window) it
falls back to your default browser at **http://localhost:8484**. To always use
the browser instead of a window, set `STL_NO_WINDOW=1` before launching.

> **Windows desktop window:** the native window uses Microsoft **WebView2**,
> which ships with Windows 11 and current Windows 10. On an older Windows
> without it, the app falls back to your browser — or install the free
> [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
> to get the window.

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

> **Optional — PDF export of painting guides:** exporting a painting guide to PDF
> needs a headless browser that can't be bundled into the standalone app. The
> first time you use **Export PDF**, run `playwright install chromium` once from a
> terminal (Playwright ships with the app). The Docker image already includes it.

---

## Docker (advanced)

If you prefer the containerized version:

### 1. Configure your drive

Copy `.env.example` to `.env` and set your drive path (use **forward slashes**,
even on Windows):

```
STL_DRIVE_1=D:/3D STLs
STL_DRIVE_2=E:/More STLs      # optional second drive
STL_ROOTS=/mnt/drive1,/mnt/drive2
```

`STL_DRIVE_1` is mounted at `/mnt/drive1` in the container, `STL_DRIVE_2` at
`/mnt/drive2`. Both are seeded as scan roots automatically on first boot.
Got models on **more than two drives**, or need to change where things are mounted?
See **[Docker — Drive Mounts & Configuration](docker.md)** for the full rundown.

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

# Getting Started

There are two ways to run STL Studio:

- **[Standalone](#standalone-recommended)** — a single downloadable app. No Docker, no setup. Recommended for most people.
- **[Docker](#docker-advanced)** — for people who already run Docker and want the containerized version.

Before installing, review the [Support and compatibility policy](support-policy.md)
for supported operating systems and architectures, upgrade paths, rollback limits,
and diagnostic privacy.

---

## Standalone (recommended)

### 1. Download

Go to the [Releases page](https://github.com/RBStephenson/STL-Studio/releases)
and download the file for your operating system:

| OS | File |
|----|------|
| Windows | `STL-Studio-Setup-<version>.exe` (installer) |
| Linux | `stl-studio-linux` |

For testing the newest successful `main` build before a versioned release, use
the rolling `Main Build` prerelease on the same Releases page.

> **macOS:** there is no supported prebuilt macOS download. Use the
> [Docker](#docker-advanced) setup if you want to run STL Studio on a Mac.

### 2. Run it

**Windows:** run the installer, then launch **STL Studio** from the Start menu.
It opens a real desktop window (no terminal, no console) — the Electron shell
starts the local server for you and shows the app. It's unsigned for now, so
Windows SmartScreen may warn on first run: **More info → Run anyway**.

**Linux:** run the binary from a terminal. It serves the app headlessly at
**http://localhost:8484** — open that URL in your browser. Pass `--open-browser`
to have it open the browser for you once it's ready, or `--port <n>` to listen on
a different port.

> **Desktop window:** Windows uses the Electron desktop app. Linux still
> runs the headless binary you open in your browser; a packaged window there is
> future work.

### Upgrading an existing installation

STL Studio supports direct upgrades from **v0.18.0 or newer**. The installer
keeps the catalog database in your user-data folder and upgrades its schema on
the first launch of the new version. Your STL files are never stored in that
database or modified by the schema upgrade.

Before a major upgrade, use **Settings → Data Management → Download Backup**.
Downgrading after the database has been upgraded is not supported; restore the
backup with the older version instead.

A backup made by a newer STL Studio version is not guaranteed to work in an older
version. For rollback, retain a backup or automatic `pre_upgrade_*.db` snapshot
created by the older version, reinstall that older application version, and
restore the matching backup. The application does not reverse schema migrations.

When an existing database needs a schema upgrade, STL Studio first writes a
consistent `pre_upgrade_<timestamp>.db` snapshot in the `backups` folder beside
the catalog database. If migration fails, startup stops and the original database
is restored automatically from that snapshot. The three newest upgrade snapshots
are retained. Keep the snapshot when reporting an upgrade failure; after returning
to the older app version, it can also be restored through **Settings → Data
Management → Restore Backup**.

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

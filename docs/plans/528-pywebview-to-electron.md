# Plan — #528: replace pywebview desktop shell with Electron

**Type:** packaging / desktop-shell refactor. **Multi-PR — do not land in one shot.**
**v1 scope (decided 2026-07-02):** Windows only · auto-update deferred · unsigned · PyInstaller sidecar.

---

## Why

The current standalone build ([packaging/standalone.py](../../packaging/standalone.py)) wraps the
localhost FastAPI server in a **pywebview** WebView2 window, packaged by PyInstaller as a single exe
with `console=True`. Problems #528 calls out:

- **Visible console window** — `console=True` in [stl-library.spec](../../packaging/stl-library.spec)
  ships a black cmd window alongside the app. `console=False` on pywebview loses the only error
  surface on first-run failures, so it was kept on deliberately.
- **Not a "real" installed app** — single loose exe, no Start-menu entry, no icon, no installer,
  no update path.
- pywebview's WebView2 backend still depends on pythonnet / clr-loader and the OS WebView2 runtime.

Electron gives a proper Chromium shell, a native installer (NSIS), a real update channel (later),
and no stray console — while the Python backend stays untouched behind `create_app()`.

## Architecture

Electron is Node/Chromium; the backend is Python. Do **not** rewrite the backend. Run it as a
**sidecar child process** the Electron main process owns:

```
Electron main (Node)
  ├─ pick a free port; spawn backend exe --port <port>   (windowless, no console)
  │     stdout/stderr piped to a log file + dev console
  ├─ poll http://127.0.0.1:<port>/api/health until ok
  ├─ BrowserWindow.loadURL('http://127.0.0.1:<port>')
  ├─ single-instance lock (second launch focuses existing window)
  └─ on 'window-all-closed' / 'before-quit' → SIGTERM sidecar, wait, SIGKILL fallback
```

Key point: **the backend keeps its own PyInstaller build**. We reuse the existing spec almost
verbatim — just drop the pywebview collection and flip `console` off — and Electron packages that exe
as an electron-builder `extraResources` sidecar. `create_app` stays the single source shared with
Docker; `standalone.py` shrinks to a headless "serve the app + static frontend, no window" entry
point.

### What standalone.py becomes

Today it does three jobs: configure env → serve → open a window/browser. Under Electron it does the
first two only. The window/browser logic (pywebview import, `should_use_window`,
`_open_browser_when_ready`) is deleted; Electron owns presentation. Add a `--headless-serve` mode (or
just make that the sole behavior) that serves in the foreground and exits cleanly on SIGTERM.

The browser fallback for Linux/headless (#463) is preserved *only* as the source-run path
(`python packaging/standalone.py`), not in the shipped Windows app. Linux packaging is out of v1
scope, so its exe is unaffected by this epic.

## Repo layout

```
desktop/                     # new Electron project (own package.json, not the frontend's)
  package.json
  electron-builder.yml
  src/
    main.ts                  # app lifecycle, sidecar spawn/kill, BrowserWindow
    sidecar.ts               # spawn + health-poll + graceful shutdown
    paths.ts                 # dev vs packaged resource resolution
  resources/
    icon.ico
  tsconfig.json
```

electron-builder `extraResources` copies `dist-standalone/stl-library.exe` into the packaged app's
`resources/`; `paths.ts` resolves it via `process.resourcesPath` when packaged, or a dev path when
running `electron .`.

## Phasing (each phase = its own PR, CI green before merge)

**Phase 0 — Electron skeleton (no backend wiring).**
`desktop/` project boots an Electron window that loads a placeholder. Establishes toolchain
(electron, electron-builder, TS build) and CI can install/build it. No behavior change to the
shipped product yet.

**Phase 1 — sidecar spawn + health + lifecycle.**
`sidecar.ts`: spawn a *manually built* backend exe, poll health, load localhost, kill on quit,
single-instance lock. Prove the whole loop locally against a hand-built exe. Backend still built by
the old flow.

**Phase 2 — headless backend entry point.**
Strip window/browser logic from [standalone.py](../../packaging/standalone.py); add graceful SIGTERM
shutdown; replace the fixed `PORT = 8484` constant with a `--port`/env-driven value (dynamic port
decision, see below); flip the PyInstaller spec to `console=False` and drop the pywebview collection
block. Delete pywebview from [requirements-desktop.txt](../../backend/requirements-desktop.txt) (file
may go away entirely). Update [test_standalone_launch.py](../../backend/tests/test_standalone_launch.py)
— `should_use_window` tests go; add tests for the headless serve path, port override, and SIGTERM
handling.

**Phase 3 — electron-builder packaging.** ✅ Done (STUDIO-73).
`electron-builder.yml`: NSIS target, `extraResources` sidecar, app icon, product metadata. Produce
an installed app with a Start-menu entry and no console window. Verify installed run end-to-end.
Also closed the Phase-2 leftover: the Electron shell now picks a free port (`findFreePort` in
runtime.ts) and passes `--port` to the sidecar instead of the fixed 8484, and `resolveBackendExe`
resolves the sidecar from `process.resourcesPath` when packaged. Full installed E2E (real PyInstaller
sidecar) is deferred to Phase 4 CI — the backend exe can't be built in the dev env here.

**Phase 4 — CI wiring in [build.yml](../../.github/workflows/build.yml).**
Windows job: build frontend → PyInstaller backend exe → `npm ci && npm run build` in `desktop/` →
electron-builder → upload the NSIS installer as the release artifact. Retire the raw
`stl-library.exe` Windows artifact (Linux job unchanged; still ships the loose binary + browser
fallback).

**Phase 5 — docs.**
[docs/getting-started.md](../../docs/getting-started.md) + [ROADMAP.md](../../ROADMAP.md): install-via-installer
instructions, close #528.

## Deferred (explicit non-goals for v1)

- **Auto-update** (electron-updater / GitHub Releases feed) — follow-up ticket.
- **Code signing** — ships unsigned; users will see a SmartScreen warning. Follow-up.
- **Linux/macOS Electron packaging** — Linux keeps the current loose-binary + browser fallback;
  macOS notarization stays in backlog (#17).

## Risks

- **Sidecar orphaning** — if Electron crashes without killing the child, a stray backend lingers on
  its (random) port. A fixed-port "is it already ours?" probe no longer applies. Mitigate: on spawn,
  write the child PID + chosen port to a lockfile in the user-data dir; on startup, if a live PID from
  a prior run is found, kill it before spawning a fresh one. Plus kill-tree on quit + single-instance
  lock.
- **Port already in use** — solved by the dynamic-port decision below (free-port pick), not a
  residual risk.
- **Cross-origin write blocker + dynamic port — verified safe.** `_block_cross_origin_writes`
  ([main.py:266](../../backend/app/main.py)) checks hostname only (`localhost`/`127.0.0.1`/`::1`),
  ignoring port, so a randomly-chosen port passes. No change needed there.
- **Startup latency** — Electron + Chromium + Python cold start is slower than pywebview. Need a
  splash/loading window while the health poll runs so the app doesn't look hung.
- **Installer size** — Electron (~150 MB) + PyInstaller backend. Acceptable for a desktop app; note
  it in the release.
- **First-run error visibility** — losing the console means backend startup failures are silent.
  Replace with: pipe sidecar stdout/stderr to a logfile in the user-data dir + show an error dialog
  if the health poll times out.
- **CI complexity** — the Windows job now chains three build systems (Vite → PyInstaller → Electron).
  Longer, more failure surface. Keep the Linux job on the old path to limit blast radius.

## Decisions log

- **Dynamic port (2026-07-03):** backend takes `--port` (or reads an env var), Electron picks a free
  OS-assigned port at startup and passes it to both the sidecar spawn args and `loadURL`. Drop the
  fixed `PORT = 8484` constant in [standalone.py](../../packaging/standalone.py) — becomes a CLI/env
  override with a random free-port default. Sequencing: Phase 1 proves the sidecar loop against a
  fixed-port hand-built exe (the backend can't accept `--port` yet); the full dynamic-port wiring
  lands in Phase 2, when the headless entry point starts honoring `--port`.
- **Jira epic (2026-07-03):** filed — STUDIO-69 (epic) + STUDIO-70..75 (phase tasks).

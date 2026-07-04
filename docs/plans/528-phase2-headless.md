# Plan — STUDIO-72 (Phase 2): headless backend entry point + `--port`

**Parent:** epic STUDIO-69 · overall plan [528-pywebview-to-electron.md](528-pywebview-to-electron.md)
**Depends on:** Phase 1 sidecar (STUDIO-71, merged).
**Scope:** backend only. The desktop-side dynamic free-port pick is a follow-up;
the sidecar keeps using the fixed default (8484) until then.

---

## Goal

`packaging/standalone.py` becomes a **headless** foreground server: no native
window, no pywebview. It honours `--port` (Electron passes the chosen port) and
shuts down gracefully on SIGTERM. The PyInstaller exe is built windowless
(`console=False`).

## Changes

| File | Change |
|------|--------|
| `packaging/standalone.py` | Strip window/browser logic (pywebview import, `should_use_window`, `_serve_background`, window branch). Add `--port` / `STL_PORT` (default 8484) via `resolve_port` + `build_parser`. Graceful SIGTERM via `install_sigterm` → `server.should_exit`. Opt-in `--open-browser` (off by default) for dev source-runs. |
| `packaging/stl-library.spec` | `console=False`; drop the `webview`/`clr_loader`/`pythonnet` `collect_all` block and all `webview_*` wiring. |
| `backend/requirements-desktop.txt` | **Deleted** — its only dep was pywebview. |
| `.github/workflows/build.yml` | Remove the "Install desktop shell (Windows)" step (`pip install -r requirements-desktop.txt`). |
| `backend/tests/test_standalone_launch.py` | Drop the 3 `should_use_window` tests; add port-resolution, arg-parsing, SIGTERM-handler, and headless-surface tests. Keep `_frontend_dist` / `_user_data_dir`. |

## Design notes

- **Port default stays 8484.** Backward-compatible and matches the Phase-1
  sidecar's fixed port, so nothing breaks before the desktop free-port switch.
- **SIGTERM is graceful on POSIX only.** Electron uses `taskkill /F`
  (TerminateProcess) on Windows, which is uncatchable — documented as a no-op
  there; the reap-on-next-start (Phase 1) is the Windows backstop.
- **Testability:** `resolve_port`, `build_parser`, `_make_sigterm_handler`,
  `install_sigterm` are pure/injectable and unit-tested without a live server.

## Testing

- `backend/tests/test_standalone_launch.py` — 11 cases: paths, port resolution
  (default / cli-wins / env / invalid-fallback), arg parsing, SIGTERM handler +
  registration, and assertions that the window helpers are gone.
- **Not run locally** — this machine's Python is a Store-stub; validated in CI
  (pytest) + the build-check exe build.
- Manual (later, with a working env): `python packaging/standalone.py --port 8600`
  serves headlessly; SIGTERM drains cleanly; `--open-browser` pops the browser.

## Deferred

- Desktop free-port pick + passing `--port` from Electron (config.ts / main.ts) —
  follow-up within Phase 2.
- Electron packaging of the windowless exe — Phase 3 (STUDIO-73).

## Exit

Headless `--port` server + windowless exe; pywebview fully removed; CI green
(pytest + both build-check platforms). Unblocks Phase 3 packaging.

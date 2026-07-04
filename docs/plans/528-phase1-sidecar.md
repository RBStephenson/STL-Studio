# Plan — STUDIO-71 (Phase 1): sidecar spawn + health poll + lifecycle

**Parent:** epic STUDIO-69 · overall plan [528-pywebview-to-electron.md](528-pywebview-to-electron.md)
**Depends on:** Phase 0 skeleton (STUDIO-70, merged).
**Scope:** Electron main owns the Python backend as a child process. Backend still
built by the old flow — this phase proves the spawn/health/lifecycle loop.

---

## Goal

The Electron app spawns a **manually-built** backend exe, waits for it to answer
`/api/health`, loads it in the window, and cleanly terminates it on quit — with a
single-instance lock and orphan reaping. No behaviour change to the shipped
product (still not packaged).

## Fixed port this phase

The backend does **not** accept `--port` until Phase 2 (STUDIO-72). Phase 1 uses
the fixed port `8484` (matching `packaging/standalone.py`). Every port reference
is marked `Phase 2:` so the dynamic free-port swap has an obvious seam.

## Files

| File | Purpose |
|------|---------|
| `desktop/src/config.ts` | Fixed port, host, health path, poll/shutdown timings, lockfile name, backend-exe path resolution (dev/override; packaged path deferred to Phase 3). |
| `desktop/src/sidecar.ts` | Pure lifecycle logic — `pollHealth`, `reapStale`, `startSidecar`, `stopSidecar` — over an injected `SidecarDeps` boundary. Unit-tested. |
| `desktop/src/runtime.ts` | Real `SidecarDeps`: `child_process.spawn`, `fetch` probe, tree-kill, JSON lockfile in userData. Not unit-tested (thin I/O). |
| `desktop/src/main.ts` | Wires it together: single-instance lock, boot backend → health → `loadURL`, error dialog on failure, kill on `before-quit`. |
| `desktop/src/sidecar.test.ts` | Vitest suite (12 cases) over the pure logic with fakes. |
| `desktop/vitest.config.ts`, `package.json` | vitest + `@types/node`; `test` script. |

## Key decisions

- **Windows kill = `taskkill /pid <pid> /T /F`** (tree kill). A PyInstaller
  one-file exe spawns a child bootloader running the real uvicorn server; killing
  only the parent pid orphans it. POSIX uses SIGTERM → SIGKILL after a grace.
- **PID-reuse guard on reap.** A stale lockfile pid may have been recycled. We
  terminate a prior-run backend **only when its recorded port is actually serving
  our health endpoint**; otherwise the stale record is discarded, never killed.
- **Testability via dependency injection.** All I/O (spawn, fetch, kill, clock,
  fs) is injected, so lifecycle branches are tested without real processes.

## Testing

- `npm test` (vitest): `pollHealth` (first-hit / retry / timeout-terminates),
  `reapStale` (no lock / ours→kill / not-ours→discard), `startSidecar`
  (healthy / never-healthy→kill+throw / reap-before-spawn), `stopSidecar`
  (pid / no-pid / null). 12 cases, all green.
- **Manual (local):** build a backend exe (or run
  `STL_NO_WINDOW=1 python packaging/standalone.py` for a fixed-port foreground
  server on 8484), then `STL_BACKEND_EXE=<path> npm start` in `desktop/` — window
  loads the app; closing it terminates the sidecar; a second launch focuses the
  first window. (Source-run pops a stray browser tab — a `standalone.py` quirk
  removed in Phase 2's headless mode; harmless to the proof.)

## Deferred to later phases

- Dynamic `--port` + free-port pick — Phase 2 (STUDIO-72), with the headless
  backend entry point.
- Splash/loading window during the health poll — polish, later.
- Dedicated sidecar logfile in userData (currently piped to the dev console) —
  Phase 3/packaging, when the console is gone.
- Packaged backend-exe resolution via `process.resourcesPath` — Phase 3.

## Risks

- **Orphaned backend on a hard Electron crash** (no `before-quit`): mitigated by
  the startup reap (lockfile pid + port-ownership probe) + single-instance lock.
- **`taskkill` unavailable / access denied**: kill is best-effort and logged; the
  reap on next start is the backstop.

## Exit

Spawn → health → load → quit-kill loop works locally against a hand-built exe;
unit tests green; CI green. Unblocks Phase 2 (STUDIO-72, headless `--port`).

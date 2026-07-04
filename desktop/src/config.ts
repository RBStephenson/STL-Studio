/**
 * Sidecar/runtime configuration — Phase 1 (STUDIO-71).
 *
 * PORT IS FIXED at 8484 this phase: the backend does not accept `--port` until
 * Phase 2 (STUDIO-72), so Phase 1 proves the spawn/health/lifecycle loop against
 * a fixed-port, hand-built backend exe. Everywhere the port is used is marked
 * `Phase 2:` so the dynamic free-port wiring has an obvious seam.
 *
 * Ref: docs/plans/528-pywebview-to-electron.md,
 *      docs/plans/528-phase1-sidecar.md
 */
import { join } from "node:path";

export const BACKEND_HOST = "127.0.0.1";

// Phase 2: replace with an OS-assigned free port chosen at startup and passed to
// the sidecar via `--port`. Until then this must match standalone.py's PORT.
export const BACKEND_PORT = 8484;

export const HEALTH_PATH = "/api/health";

/** Health-poll cadence and ceiling (ms). Python + uvicorn cold start is the
 *  slow part; 30s is generous headroom before we surface a startup error. */
export const HEALTH_POLL_INTERVAL_MS = 250;
export const HEALTH_POLL_TIMEOUT_MS = 30_000;

/** Grace period between SIGTERM and the SIGKILL fallback on POSIX (ms). */
export const SHUTDOWN_GRACE_MS = 5_000;

/** Lockfile (PID + port of the spawned backend) lives in the Electron userData
 *  dir; the absolute path is resolved at runtime from `app.getPath('userData')`. */
export const LOCKFILE_NAME = "sidecar.lock.json";

export function baseUrl(port: number = BACKEND_PORT): string {
  return `http://${BACKEND_HOST}:${port}`;
}

export function healthUrl(port: number = BACKEND_PORT): string {
  return `${baseUrl(port)}${HEALTH_PATH}`;
}

/**
 * Absolute path to the backend executable to spawn.
 *
 * Phase 1 runs against a *manually built* exe: set `STL_BACKEND_EXE` to point at
 * it (e.g. the PyInstaller output). Absent that, we fall back to the conventional
 * dev build location `dist-standalone/stl-library.exe` at the repo root.
 *
 * Phase 3 (packaging) resolves this from `process.resourcesPath` for the
 * installed app; that branch is intentionally not wired yet.
 */
export function resolveBackendExe(repoRoot: string): string {
  const override = process.env.STL_BACKEND_EXE;
  if (override && override.trim()) {
    return override.trim();
  }
  const exeName =
    process.platform === "win32" ? "stl-library.exe" : "stl-library";
  return join(repoRoot, "dist-standalone", exeName);
}

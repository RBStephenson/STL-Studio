/**
 * Sidecar/runtime configuration.
 *
 * The backend port is chosen dynamically at startup (an OS-assigned free port)
 * and passed to the sidecar via `--port` and to `loadURL` — see `main.ts`. The
 * constant below is only a last-resort fallback matching standalone.py's default.
 *
 * Ref: docs/plans/528-pywebview-to-electron.md,
 *      docs/plans/528-phase1-sidecar.md
 */
import { join } from "node:path";

export const BACKEND_HOST = "127.0.0.1";

/** Fallback port only. The live port is an OS-assigned free port picked at
 *  startup (`findFreePort` in runtime.ts) and handed to the backend via `--port`;
 *  this default matches standalone.py's `DEFAULT_PORT` for source/dev runs. */
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

/** Inputs for locating the backend exe: whether Electron is packaged, the
 *  packaged `resources/` dir (`process.resourcesPath`), and the dev repo root. */
export interface BackendExeLocation {
  packaged: boolean;
  resourcesPath: string;
  repoRoot: string;
}

/**
 * Absolute path to the backend executable to spawn.
 *
 * Resolution order:
 *   1. `STL_BACKEND_EXE` override — used by devs / CI to point at a hand-built exe.
 *   2. Packaged: `<resourcesPath>/stl-library.exe`, where electron-builder's
 *      `extraResources` copied the PyInstaller sidecar.
 *   3. Dev (`electron .`): `<repoRoot>/dist-standalone/stl-library.exe`.
 */
export function resolveBackendExe(loc: BackendExeLocation): string {
  const override = process.env.STL_BACKEND_EXE;
  if (override && override.trim()) {
    return override.trim();
  }
  const exeName =
    process.platform === "win32" ? "stl-library.exe" : "stl-library";
  if (loc.packaged) {
    return join(loc.resourcesPath, exeName);
  }
  return join(loc.repoRoot, "dist-standalone", exeName);
}

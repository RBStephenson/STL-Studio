/**
 * Real (production) implementations of the injected sidecar I/O boundaries.
 *
 * Kept apart from sidecar.ts so the lifecycle logic there stays free of Node
 * built-ins and is unit-testable with fakes. main.ts wires these into the pure
 * functions. Nothing here is exercised by the unit tests.
 *
 * Ref: docs/plans/528-phase1-sidecar.md
 */
import { execFile, spawn as nodeSpawn } from "node:child_process";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { join } from "node:path";

import { BACKEND_HOST, SHUTDOWN_GRACE_MS } from "./config";
import type { LockRecord, SidecarDeps, SidecarProcess } from "./sidecar";

/**
 * Ask the OS for a free TCP port on the loopback interface.
 *
 * Binds a throwaway server to port 0 (kernel picks a free port), reads the
 * assigned port, then closes it and hands the number to the sidecar. There's an
 * inherent TOCTOU gap — the port could be taken between close and the backend's
 * bind — but on a single-user desktop that race is negligible, and the health
 * poll surfaces a failed bind as a startup error rather than a silent hang.
 */
export function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.once("error", reject);
    srv.listen(0, BACKEND_HOST, () => {
      const addr = srv.address();
      if (addr === null || typeof addr === "string") {
        srv.close(() => reject(new Error("could not determine a free port")));
        return;
      }
      const { port } = addr;
      srv.close(() => resolve(port));
    });
  });
}

/** GET `url`, resolving true only on a 2xx. Network errors resolve false so the
 *  health poll simply keeps trying rather than throwing. */
async function probe(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { redirect: "manual" });
    return res.ok;
  } catch {
    return false;
  }
}

/** Terminate a whole process tree by pid.
 *
 * Windows: `taskkill /pid <pid> /T /F`. A PyInstaller one-file exe spawns a
 * child bootloader that runs the real uvicorn server, so killing only the parent
 * pid would orphan it — `/T` kills the tree, `/F` forces it.
 *
 * POSIX: SIGTERM for a graceful stop, then a SIGKILL fallback after a grace
 * window if the process is still alive. */
function killTree(pid: number): Promise<void> {
  if (process.platform === "win32") {
    return new Promise<void>((resolve) => {
      execFile("taskkill", ["/pid", String(pid), "/T", "/F"], () => resolve());
    });
  }
  return new Promise<void>((resolve) => {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      resolve();
      return;
    }
    const timer = setTimeout(() => {
      try {
        process.kill(pid, "SIGKILL");
      } catch {
        // already gone
      }
      resolve();
    }, SHUTDOWN_GRACE_MS);
    // If it dies cleanly before the grace elapses we still resolve via the
    // timer; unref so a lingering timer never keeps the app alive.
    timer.unref?.();
  });
}

/**
 * Build the production `SidecarDeps`. The lockfile lives under the Electron
 * userData dir (passed in so this module never imports `electron`, keeping it
 * loadable in plain-Node contexts).
 */
export function runtimeDeps(
  userDataDir: string,
  lockfileName: string,
  persistentLog?: (level: string, values: unknown[]) => void,
): SidecarDeps {
  const lockPath = join(userDataDir, lockfileName);

  return {
    spawn(exePath: string, args: string[], env?: Record<string, string>): SidecarProcess {
      // Detached false: the child stays in our process group so a hard crash of
      // Electron is still followed by OS cleanup where supported. stdout/stderr
      // are piped to our logger; a dedicated logfile lands in a later phase.
      const child = nodeSpawn(exePath, args, {
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        env: env ? { ...process.env, ...env } : process.env,
      });
      child.stdout?.on("data", (d) => {
        process.stdout.write(`[backend] ${d}`);
        persistentLog?.("BACKEND", [d.toString()]);
      });
      child.stderr?.on("data", (d) => {
        process.stderr.write(`[backend] ${d}`);
        persistentLog?.("BACKEND-ERROR", [d.toString()]);
      });
      return child as unknown as SidecarProcess;
    },
    probe,
    killTree,
    readLock(): LockRecord | null {
      try {
        if (!existsSync(lockPath)) {
          return null;
        }
        const raw = JSON.parse(readFileSync(lockPath, "utf-8")) as Partial<LockRecord>;
        if (typeof raw.pid === "number" && typeof raw.port === "number") {
          return { pid: raw.pid, port: raw.port };
        }
        return null;
      } catch {
        return null;
      }
    },
    writeLock(record: LockRecord): void {
      writeFileSync(lockPath, JSON.stringify(record), "utf-8");
    },
    clearLock(): void {
      try {
        rmSync(lockPath, { force: true });
      } catch {
        // best-effort
      }
    },
    now: () => Date.now(),
    sleep: (ms: number) => new Promise((r) => setTimeout(r, ms)),
    log: (message: string) => console.log(`[sidecar] ${message}`),
  };
}

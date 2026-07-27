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

/** Minimal slice of `child_process.execFile` this module depends on, so tests
 *  can inject a fake without a real process. */
type ExecFileFn = (
  file: string,
  args: string[],
  options: { timeout: number },
  callback: (error: Error | null) => void,
) => unknown;

/** Terminate a Windows process tree via `taskkill /pid <pid> /T /F`. A
 *  PyInstaller one-file exe spawns a child bootloader that runs the real
 *  uvicorn server, so killing only the parent pid would orphan it — `/T`
 *  kills the tree, `/F` forces it.
 *
 * Two independent defenses against a wedged `taskkill` blocking quit forever
 * (STUDIO-340): `execFile`'s own `timeout` option (primary — Node kills the
 * child and still invokes the callback), and an unref'd `setTimeout` that
 * resolves regardless (backstop, in case `execFile`'s timeout itself never
 * fires — the case a test can actually exercise with a fake that never calls
 * back). Either path logs so a hung kill shows up in diagnostics instead of
 * silently taking the full grace window every time. */
export function killTreeWindows(
  pid: number,
  execFileFn: ExecFileFn = execFile as unknown as ExecFileFn,
  timeoutMs: number = SHUTDOWN_GRACE_MS,
  log: (message: string) => void = () => {},
): Promise<void> {
  return new Promise<void>((resolve) => {
    let settled = false;
    const settle = (): void => {
      if (settled) return;
      settled = true;
      resolve();
    };
    const backstop = setTimeout(() => {
      log(`taskkill for pid ${pid} did not confirm within ${timeoutMs}ms; giving up (STUDIO-340)`);
      settle();
    }, timeoutMs);
    backstop.unref?.();
    execFileFn("taskkill", ["/pid", String(pid), "/T", "/F"], { timeout: timeoutMs }, (error) => {
      clearTimeout(backstop);
      if (error) {
        log(`taskkill for pid ${pid} failed or timed out: ${error.message}`);
      }
      settle();
    });
  });
}

function killTree(pid: number): Promise<void> {
  if (process.platform === "win32") {
    return killTreeWindows(pid, execFile as unknown as ExecFileFn, SHUTDOWN_GRACE_MS, (message) =>
      console.error(`[sidecar] ${message}`),
    );
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

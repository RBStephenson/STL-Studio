/**
 * Backend sidecar lifecycle — Phase 1 (STUDIO-71).
 *
 * The Electron main process owns the Python backend as a child process: spawn it,
 * poll `/api/health` until it answers, and terminate it (with a stale-run reap on
 * startup) so no orphaned server lingers. All I/O boundaries — process spawn,
 * HTTP fetch, tree-kill, clock, filesystem — are injected via `SidecarDeps` so
 * the control flow is unit-testable without a real backend or real processes.
 *
 * Port is FIXED at 8484 this phase (see config.ts); dynamic `--port` is Phase 2.
 *
 * Ref: docs/plans/528-phase1-sidecar.md
 */
import {
  HEALTH_POLL_INTERVAL_MS,
  HEALTH_POLL_TIMEOUT_MS,
  healthUrl,
} from "./config";

/** The subset of a Node ChildProcess this module relies on. */
export interface SidecarProcess {
  readonly pid: number | undefined;
  on(event: "exit", listener: (code: number | null) => void): void;
  on(event: "error", listener: (err: Error) => void): void;
}

/** Persisted record of the running sidecar, used to reap a crashed prior run. */
export interface LockRecord {
  pid: number;
  port: number;
}

/** Injected I/O boundaries — real implementations live in `runtimeDeps()`. */
export interface SidecarDeps {
  /** Spawn the backend exe with the given args (and optional extra env vars,
   *  merged over the current process env); returns a process handle. */
  spawn(exePath: string, args: string[], env?: Record<string, string>): SidecarProcess;
  /** HTTP GET used for health polling; resolves ok=true on a 2xx response. */
  probe(url: string): Promise<boolean>;
  /** Terminate a process tree by pid (taskkill /T /F on Windows, signals on POSIX). */
  killTree(pid: number): Promise<void>;
  readLock(): LockRecord | null;
  writeLock(record: LockRecord): void;
  clearLock(): void;
  /** Monotonic-ish clock in ms (Date.now in prod; controllable in tests). */
  now(): number;
  sleep(ms: number): Promise<void>;
  log(message: string): void;
}

export interface StartOptions {
  exePath: string;
  args?: string[];
  /** Extra env vars merged over the current process env for the spawned
   *  backend — e.g. STL_SECRET_KEY (STUDIO-147). */
  env?: Record<string, string>;
  port: number;
  timeoutMs?: number;
  intervalMs?: number;
}

export interface StartResult {
  proc: SidecarProcess;
  port: number;
}

/**
 * Poll `url` until it returns a healthy response or the deadline passes.
 * Returns true on the first healthy probe, false on timeout.
 */
export async function pollHealth(
  url: string,
  deps: Pick<SidecarDeps, "probe" | "now" | "sleep">,
  timeoutMs: number = HEALTH_POLL_TIMEOUT_MS,
  intervalMs: number = HEALTH_POLL_INTERVAL_MS,
): Promise<boolean> {
  const deadline = deps.now() + timeoutMs;
  // Always make at least one attempt even if timeoutMs is 0.
  do {
    if (await deps.probe(url)) {
      return true;
    }
    if (deps.now() + intervalMs >= deadline) {
      break;
    }
    await deps.sleep(intervalMs);
  } while (deps.now() < deadline);
  return false;
}

/**
 * Kill a backend left running by a crashed prior launch, if any.
 *
 * Guards against PID reuse: a stale lockfile PID may since have been recycled by
 * an unrelated process. We only terminate when the recorded port is *actually
 * serving our health endpoint* — proving it's our backend — then clear the lock.
 * A stale record whose port no longer answers is simply discarded, never killed.
 */
export async function reapStale(deps: SidecarDeps): Promise<void> {
  const lock = deps.readLock();
  if (lock === null) {
    return;
  }
  const ours = await deps.probe(healthUrl(lock.port));
  if (ours) {
    deps.log(
      `reaping orphaned backend from a prior run (pid ${lock.pid}, port ${lock.port})`,
    );
    try {
      await deps.killTree(lock.pid);
    } catch (err) {
      deps.log(`failed to kill stale sidecar pid ${lock.pid}: ${String(err)}`);
    }
  } else {
    deps.log(
      `discarding stale lockfile (port ${lock.port} not ours / not serving)`,
    );
  }
  deps.clearLock();
}

export class SidecarStartError extends Error {}

/**
 * Reap any orphan, spawn the backend, record the lockfile, and wait for health.
 * Throws `SidecarStartError` if the backend never becomes healthy in time — the
 * caller surfaces this as a startup error dialog.
 */
export async function startSidecar(
  deps: SidecarDeps,
  opts: StartOptions,
): Promise<StartResult> {
  await reapStale(deps);

  const args = opts.args ?? [];
  deps.log(`spawning backend: ${opts.exePath} ${args.join(" ")}`);
  const proc = deps.spawn(opts.exePath, args, opts.env);

  proc.on("error", (err) => deps.log(`sidecar process error: ${err.message}`));
  proc.on("exit", (code) => deps.log(`sidecar exited with code ${code}`));

  if (proc.pid !== undefined) {
    deps.writeLock({ pid: proc.pid, port: opts.port });
  }

  const healthy = await pollHealth(
    healthUrl(opts.port),
    deps,
    opts.timeoutMs,
    opts.intervalMs,
  );
  if (!healthy) {
    // Best-effort cleanup so a wedged backend doesn't linger after we give up.
    if (proc.pid !== undefined) {
      await deps.killTree(proc.pid).catch(() => undefined);
    }
    deps.clearLock();
    throw new SidecarStartError(
      `backend did not become healthy within ${opts.timeoutMs ?? HEALTH_POLL_TIMEOUT_MS}ms`,
    );
  }

  deps.log(`backend healthy on port ${opts.port}`);
  return { proc, port: opts.port };
}

/**
 * Terminate the running sidecar and clear its lockfile. Safe to call more than
 * once (e.g. window-all-closed then before-quit) — a missing pid is a no-op.
 */
export async function stopSidecar(
  deps: SidecarDeps,
  proc: SidecarProcess | null,
): Promise<void> {
  const pid = proc?.pid;
  if (pid === undefined) {
    deps.clearLock();
    return;
  }
  deps.log(`stopping backend (pid ${pid})`);
  try {
    await deps.killTree(pid);
  } catch (err) {
    deps.log(`failed to stop sidecar pid ${pid}: ${String(err)}`);
  } finally {
    deps.clearLock();
  }
}

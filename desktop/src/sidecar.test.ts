import { describe, expect, it, vi } from "vitest";

import { healthUrl } from "./config";
import {
  SidecarStartError,
  pollHealth,
  reapStale,
  startSidecar,
  stopSidecar,
} from "./sidecar";
import type { LockRecord, SidecarDeps, SidecarProcess } from "./sidecar";

interface Calls {
  spawn: Array<{ exe: string; args: string[] }>;
  killTree: number[];
  writeLock: LockRecord[];
  clearLock: number;
}

function fakeProc(pid: number | undefined): SidecarProcess {
  return { pid, on: vi.fn() };
}

function makeDeps(overrides: Partial<SidecarDeps> = {}): {
  deps: SidecarDeps;
  calls: Calls;
} {
  const calls: Calls = { spawn: [], killTree: [], writeLock: [], clearLock: 0 };
  let clock = 0;
  const deps: SidecarDeps = {
    spawn: (exe, args) => {
      calls.spawn.push({ exe, args });
      return fakeProc(4242);
    },
    probe: async () => false,
    killTree: async (pid) => {
      calls.killTree.push(pid);
    },
    readLock: () => null,
    writeLock: (r) => {
      calls.writeLock.push(r);
    },
    clearLock: () => {
      calls.clearLock += 1;
    },
    now: () => clock,
    // Advancing the clock inside sleep lets the timeout logic terminate without
    // real timers.
    sleep: async (ms) => {
      clock += ms;
    },
    log: () => undefined,
    ...overrides,
  };
  return { deps, calls };
}

describe("pollHealth", () => {
  it("resolves true on the first healthy probe", async () => {
    const probe = vi.fn().mockResolvedValue(true);
    const { deps } = makeDeps({ probe });
    await expect(pollHealth("http://x/health", deps, 1000, 250)).resolves.toBe(true);
    expect(probe).toHaveBeenCalledTimes(1);
  });

  it("retries until healthy", async () => {
    const probe = vi
      .fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(false)
      .mockResolvedValue(true);
    const { deps } = makeDeps({ probe });
    await expect(pollHealth("http://x/health", deps, 5000, 250)).resolves.toBe(true);
    expect(probe).toHaveBeenCalledTimes(3);
  });

  it("returns false on timeout and does not loop forever", async () => {
    const probe = vi.fn().mockResolvedValue(false);
    const { deps } = makeDeps({ probe });
    await expect(pollHealth("http://x/health", deps, 1000, 250)).resolves.toBe(false);
  });
});

describe("reapStale", () => {
  it("does nothing when there is no lockfile", async () => {
    const { deps, calls } = makeDeps({ readLock: () => null });
    await reapStale(deps);
    expect(calls.killTree).toEqual([]);
    expect(calls.clearLock).toBe(0);
  });

  it("kills and clears when the recorded port is serving our health endpoint", async () => {
    const lock: LockRecord = { pid: 999, port: 8484 };
    const probe = vi.fn().mockResolvedValue(true);
    const { deps, calls } = makeDeps({ readLock: () => lock, probe });
    await reapStale(deps);
    expect(probe).toHaveBeenCalledWith(healthUrl(8484));
    expect(calls.killTree).toEqual([999]);
    expect(calls.clearLock).toBe(1);
  });

  it("discards a stale lock without killing when the port is not ours (PID reuse guard)", async () => {
    const lock: LockRecord = { pid: 999, port: 8484 };
    const probe = vi.fn().mockResolvedValue(false);
    const { deps, calls } = makeDeps({ readLock: () => lock, probe });
    await reapStale(deps);
    expect(calls.killTree).toEqual([]);
    expect(calls.clearLock).toBe(1);
  });
});

describe("startSidecar", () => {
  it("spawns, records the lock, and returns when healthy", async () => {
    const probe = vi.fn().mockResolvedValue(true);
    const { deps, calls } = makeDeps({ probe });
    const result = await startSidecar(deps, {
      exePath: "/backend.exe",
      args: [],
      port: 8484,
    });
    expect(result.port).toBe(8484);
    expect(calls.spawn).toHaveLength(1);
    expect(calls.writeLock).toEqual([{ pid: 4242, port: 8484 }]);
    expect(calls.killTree).toEqual([]);
  });

  it("kills, clears the lock, and throws when health never comes up", async () => {
    const probe = vi.fn().mockResolvedValue(false);
    const { deps, calls } = makeDeps({ probe });
    await expect(
      startSidecar(deps, { exePath: "/backend.exe", args: [], port: 8484, timeoutMs: 500 }),
    ).rejects.toBeInstanceOf(SidecarStartError);
    expect(calls.killTree).toEqual([4242]);
    expect(calls.clearLock).toBeGreaterThanOrEqual(1);
  });

  it("reaps an orphan before spawning a fresh backend", async () => {
    const lock: LockRecord = { pid: 111, port: 8484 };
    // First probe (reap check) true = orphan is ours; subsequent probes (health)
    // true so start succeeds.
    const probe = vi.fn().mockResolvedValue(true);
    const { deps, calls } = makeDeps({ readLock: () => lock, probe });
    await startSidecar(deps, { exePath: "/backend.exe", args: [], port: 8484 });
    expect(calls.killTree).toContain(111);
    expect(calls.spawn).toHaveLength(1);
  });
});

describe("stopSidecar", () => {
  it("kills the pid and clears the lock", async () => {
    const { deps, calls } = makeDeps();
    await stopSidecar(deps, fakeProc(7777));
    expect(calls.killTree).toEqual([7777]);
    expect(calls.clearLock).toBe(1);
  });

  it("clears the lock without killing when there is no pid", async () => {
    const { deps, calls } = makeDeps();
    await stopSidecar(deps, fakeProc(undefined));
    expect(calls.killTree).toEqual([]);
    expect(calls.clearLock).toBe(1);
  });

  it("clears the lock when proc is null", async () => {
    const { deps, calls } = makeDeps();
    await stopSidecar(deps, null);
    expect(calls.killTree).toEqual([]);
    expect(calls.clearLock).toBe(1);
  });
});

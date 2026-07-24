import { createServer } from "node:net";
import { createServer as createHttpServer, type Server as HttpServer } from "node:http";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { findFreePort, killTreeWindows, runtimeDeps } from "./runtime";

describe("killTreeWindows (STUDIO-340)", () => {
  it("resolves once taskkill's callback fires, without logging a timeout", async () => {
    const log = vi.fn();
    const execFileFn = vi.fn((_file, _args, _options, callback: (error: Error | null) => void) => {
      callback(null);
    });

    await killTreeWindows(123, execFileFn, 5_000, log);

    expect(execFileFn).toHaveBeenCalledWith(
      "taskkill",
      ["/pid", "123", "/T", "/F"],
      { timeout: 5_000 },
      expect.any(Function),
    );
    expect(log).not.toHaveBeenCalled();
  });

  it("still settles and logs if execFile's own timeout reports an error", async () => {
    const log = vi.fn();
    const execFileFn = vi.fn((_file, _args, _options, callback: (error: Error | null) => void) => {
      callback(new Error("taskkill ETIMEDOUT"));
    });

    await killTreeWindows(123, execFileFn, 5_000, log);

    expect(log).toHaveBeenCalledWith(expect.stringContaining("ETIMEDOUT"));
  });

  it("still settles via the backstop timer if execFile never calls back at all", async () => {
    vi.useFakeTimers();
    try {
      const log = vi.fn();
      // Simulates a wedged native call that ignores its own timeout option —
      // the exact failure mode a hard lock (Task Manager only) came from.
      const execFileFn = vi.fn(() => undefined);

      const settled = killTreeWindows(123, execFileFn, 5_000, log);
      let resolved = false;
      void settled.then(() => {
        resolved = true;
      });

      await vi.advanceTimersByTimeAsync(4_999);
      expect(resolved).toBe(false);

      await vi.advanceTimersByTimeAsync(1);
      expect(resolved).toBe(true);
      expect(log).toHaveBeenCalledWith(expect.stringContaining("did not confirm within 5000ms"));
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("findFreePort", () => {
  it("returns a usable TCP port that can actually be bound", async () => {
    const port = await findFreePort();
    expect(port).toBeGreaterThan(0);
    expect(port).toBeLessThan(65536);

    // The returned port is free right now: binding it should succeed.
    await new Promise<void>((resolve, reject) => {
      const srv = createServer();
      srv.once("error", reject);
      srv.listen(port, "127.0.0.1", () => srv.close(() => resolve()));
    });
  });
});

describe("runtimeDeps", () => {
  let dir: string;

  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true });
  });

  function deps() {
    dir = mkdtempSync(join(tmpdir(), "stl-studio-runtime-test-"));
    const logs: Array<{ level: string; values: unknown[] }> = [];
    const d = runtimeDeps(dir, "sidecar.lock.json", (level, values) => logs.push({ level, values }));
    return { deps: d, logs };
  }

  it("now() returns a real timestamp close to Date.now()", () => {
    const { deps: d } = deps();
    expect(Math.abs(d.now() - Date.now())).toBeLessThan(1000);
  });

  it("sleep() resolves after roughly the requested delay", async () => {
    const { deps: d } = deps();
    const start = Date.now();
    await d.sleep(20);
    expect(Date.now() - start).toBeGreaterThanOrEqual(15);
  });

  it("readLock() returns null when no lockfile exists", () => {
    const { deps: d } = deps();
    expect(d.readLock()).toBeNull();
  });

  it("writeLock()/readLock() round-trip a valid record", () => {
    const { deps: d } = deps();
    d.writeLock({ pid: 4242, port: 8080 });
    expect(d.readLock()).toEqual({ pid: 4242, port: 8080 });
  });

  it("readLock() returns null for a corrupt lockfile", () => {
    const { deps: d } = deps();
    d.writeLock({ pid: 4242, port: 8080 });
    // Overwrite with something that parses but doesn't match the shape.
    d.writeLock({ pid: "not-a-number", port: 8080 } as never);
    expect(d.readLock()).toBeNull();
  });

  it("clearLock() removes the lockfile and is safe to call again", () => {
    const { deps: d } = deps();
    d.writeLock({ pid: 4242, port: 8080 });
    d.clearLock();
    expect(d.readLock()).toBeNull();
    expect(() => d.clearLock()).not.toThrow();
  });

  it("probe() resolves true for a 2xx response and false on connection failure", async () => {
    const { deps: d } = deps();
    const port = await findFreePort();
    const server: HttpServer = createHttpServer((_req, res) => {
      res.writeHead(200);
      res.end("ok");
    });
    await new Promise<void>((resolve) => server.listen(port, "127.0.0.1", resolve));
    try {
      await expect(d.probe(`http://127.0.0.1:${port}/`)).resolves.toBe(true);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
    // Nothing listening on this now-closed port.
    await expect(d.probe(`http://127.0.0.1:${port}/`)).resolves.toBe(false);
  });

  it("spawn() launches a real child process and pipes its stdout through the logger", async () => {
    const { deps: d, logs } = deps();
    const proc = d.spawn(process.execPath, ["-e", "console.log('hello from child')"]);
    expect(proc.pid).toBeGreaterThan(0);

    await new Promise<void>((resolve) => proc.on("exit", () => resolve()));
    expect(logs.some((l) => l.level === "BACKEND" && String(l.values[0]).includes("hello from child"))).toBe(
      true,
    );
  });

  it(
    "killTree() terminates a running spawned process",
    // On POSIX, killTree() unconditionally waits out SHUTDOWN_GRACE_MS
    // (5s) before resolving — it sends SIGTERM then only checks/escalates
    // to SIGKILL once the grace timer fires, it doesn't resolve early on
    // exit. That alone can exceed vitest's default 5s test timeout on a
    // slower CI runner, so give this one headroom.
    async () => {
      const { deps: d } = deps();
      const proc = d.spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"]);
      const pid = proc.pid;
      expect(pid).toBeGreaterThan(0);

      const exited = new Promise<void>((resolve) => proc.on("exit", () => resolve()));
      await d.killTree(pid as number);
      await exited;
    },
    10_000,
  );
});

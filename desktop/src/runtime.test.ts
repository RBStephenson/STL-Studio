import { createServer } from "node:net";
import { createServer as createHttpServer, type Server as HttpServer } from "node:http";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { findFreePort, runtimeDeps } from "./runtime";

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

  it("killTree() terminates a running spawned process", async () => {
    const { deps: d } = deps();
    const proc = d.spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"]);
    const pid = proc.pid;
    expect(pid).toBeGreaterThan(0);

    const exited = new Promise<void>((resolve) => proc.on("exit", () => resolve()));
    await d.killTree(pid as number);
    await exited;
  });
});

import { createServer } from "node:net";

import { describe, expect, it } from "vitest";

import { findFreePort } from "./runtime";

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

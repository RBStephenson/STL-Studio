import { describe, it, expect, vi, afterEach } from "vitest";
import { downscaleForUpload } from "./imageUpload";

const G = globalThis as unknown as { createImageBitmap?: unknown };

describe("downscaleForUpload", () => {
  afterEach(() => { delete G.createImageBitmap; });

  it("returns the original when createImageBitmap is unavailable (e.g. jsdom)", async () => {
    const f = new File(["x"], "a.png", { type: "image/png" });
    expect(await downscaleForUpload(f)).toBe(f);
  });

  it("returns the original when the image is already under the max dimension", async () => {
    G.createImageBitmap = vi.fn(async () => ({ width: 800, height: 600, close: vi.fn() }));
    const f = new File(["x"], "a.png", { type: "image/png" });
    expect(await downscaleForUpload(f, { maxDim: 1600 })).toBe(f);
  });

  it("returns the original if decoding throws", async () => {
    G.createImageBitmap = vi.fn(async () => { throw new Error("bad"); });
    const f = new File(["x"], "a.png", { type: "image/png" });
    expect(await downscaleForUpload(f)).toBe(f);
  });
});

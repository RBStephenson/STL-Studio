import { describe, expect, it } from "vitest";
import { withStorageRecoverySignal } from "./useStorageRecoverySignal";

describe("withStorageRecoverySignal", () => {
  it("cache-busts local image requests only after recovery", () => {
    const url = "/api/files/image?path=C%3A%5Clibrary%5Ca.png";
    expect(withStorageRecoverySignal(url, 0)).toBe(url);
    expect(withStorageRecoverySignal(url, 1)).toBe(`${url}&storage_recovery=1`);
  });

  it("never modifies remote images", () => {
    expect(withStorageRecoverySignal("https://cdn.example/a.png", 2)).toBe("https://cdn.example/a.png");
  });
});

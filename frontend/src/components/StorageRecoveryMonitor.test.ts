import { describe, expect, it } from "vitest";
import { storageRecoveryTransition } from "./StorageRecoveryMonitor";

describe("storageRecoveryTransition", () => {
  it("announces initial warm-up once", () => {
    expect(storageRecoveryTransition(undefined, false)?.message).toMatch(/loading previews/i);
    expect(storageRecoveryTransition(false, false)).toBeNull();
  });

  it("announces loss and recovery transitions", () => {
    expect(storageRecoveryTransition(true, false)?.message).toMatch(/catalog is safe/i);
    expect(storageRecoveryTransition(false, true)).toEqual({
      message: "External storage is available again.",
      type: "success",
      recovered: true,
    });
  });

  it("stays quiet while storage remains available", () => {
    expect(storageRecoveryTransition(undefined, true)).toBeNull();
    expect(storageRecoveryTransition(true, true)).toBeNull();
  });
});

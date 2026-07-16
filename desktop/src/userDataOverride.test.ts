import { describe, expect, it, vi } from "vitest";

import { applyUserDataOverride } from "./userDataOverride";

describe("applyUserDataOverride", () => {
  it("leaves normal launches unchanged", () => {
    const setPath = vi.fn();
    expect(applyUserDataOverride({ setPath }, undefined)).toBeNull();
    expect(setPath).not.toHaveBeenCalled();
  });

  it("sets an absolute automation profile", () => {
    const setPath = vi.fn();
    const path = process.platform === "win32" ? "C:\\ci\\profile" : "/ci/profile";
    expect(applyUserDataOverride({ setPath }, path)).toBe(path);
    expect(setPath).toHaveBeenCalledWith("userData", path);
  });

  it("rejects relative profile paths", () => {
    expect(() => applyUserDataOverride({ setPath: vi.fn() }, "relative/profile")).toThrow(
      "must be an absolute path",
    );
  });
});

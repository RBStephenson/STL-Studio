import { describe, it, expect, beforeEach } from "vitest";

// Regression test for test-setup.ts's Node 26 localStorage/sessionStorage
// workaround: Node 26+ pre-defines both globals as inert getter stubs before
// vitest's jsdom environment runs, and jsdom's own "define only if missing"
// setup then leaves them in place — silently returning undefined instead of
// a working Storage, for any code (e.g. useSidebarCollapsed) that reads or
// writes them. This must pass on every Node version the project supports,
// not just whichever one happens to be running locally.
describe("test environment: Web Storage", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("localStorage is a working Storage, not undefined", () => {
    expect(localStorage).toBeDefined();
    localStorage.setItem("k", "v");
    expect(localStorage.getItem("k")).toBe("v");
    localStorage.removeItem("k");
    expect(localStorage.getItem("k")).toBeNull();
  });

  it("sessionStorage is a working Storage, not undefined", () => {
    expect(sessionStorage).toBeDefined();
    sessionStorage.setItem("k", "v");
    expect(sessionStorage.getItem("k")).toBe("v");
  });

  it("localStorage and sessionStorage are independent stores", () => {
    localStorage.setItem("shared-key", "local");
    sessionStorage.setItem("shared-key", "session");
    expect(localStorage.getItem("shared-key")).toBe("local");
    expect(sessionStorage.getItem("shared-key")).toBe("session");
  });
});

import { describe, expect, it, vi } from "vitest";

import { classifyNavigation, routeNavigation } from "./externalNavigation";

describe("classifyNavigation", () => {
  it.each([
    "http://127.0.0.1:5173/library",
    "http://localhost:8484/settings",
    "https://127.0.0.1:9000/",
  ])("treats the sidecar origin %s as internal on any port", (url) => {
    expect(classifyNavigation(url)).toBe("internal");
  });

  it("treats bundled file:// pages as internal", () => {
    expect(classifyNavigation("file:///C:/app/splash.html")).toBe("internal");
  });

  it.each([
    "https://www.patreon.com/BrentStephenson",
    "https://github.com/RBStephenson/STL-Studio/wiki",
    "https://www.buymeacoffee.com/brent_the_programmer",
  ])("sends the Help page's real outbound link %s to the browser", (url) => {
    expect(classifyNavigation(url)).toBe("external");
  });

  it.each([
    // shell.openExternal hands these to the OS handler; on Windows that is
    // local code execution, so they must never reach it.
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "ms-msdt:/id PCWDiagnostic",
    "smb://attacker/share",
    "vbscript:msgbox(1)",
  ])("denies the dangerous scheme %s", (url) => {
    expect(classifyNavigation(url)).toBe("deny");
  });

  it("denies remote plain http, which the app never links to", () => {
    expect(classifyNavigation("http://example.com/x")).toBe("deny");
  });

  it("denies unparseable input rather than defaulting to allow", () => {
    expect(classifyNavigation("not a url")).toBe("deny");
    expect(classifyNavigation("")).toBe("deny");
  });

  it("is not fooled by a loopback-looking host on a remote domain", () => {
    expect(classifyNavigation("https://127.0.0.1.evil.com/")).toBe("external");
    expect(classifyNavigation("https://localhost.evil.com/")).toBe("external");
  });
});

describe("routeNavigation", () => {
  function host() {
    return { openExternal: vi.fn().mockResolvedValue(undefined), log: vi.fn() };
  }

  it("allows the window to load internal targets without touching the shell", () => {
    const h = host();
    expect(routeNavigation("http://127.0.0.1:5555/library", h)).toBe(true);
    expect(h.openExternal).not.toHaveBeenCalled();
  });

  it("hands external links to the browser and keeps them out of the window", () => {
    const h = host();
    expect(routeNavigation("https://www.patreon.com/x", h)).toBe(false);
    expect(h.openExternal).toHaveBeenCalledWith("https://www.patreon.com/x");
  });

  it("blocks denied schemes and logs them", () => {
    const h = host();
    expect(routeNavigation("javascript:alert(1)", h)).toBe(false);
    expect(h.openExternal).not.toHaveBeenCalled();
    expect(h.log).toHaveBeenCalledWith(expect.stringContaining("blocked navigation"));
  });

  it("does not reject when the shell fails to open the link", async () => {
    const h = host();
    h.openExternal.mockRejectedValue(new Error("no handler"));
    expect(routeNavigation("https://example.com/", h)).toBe(false);
    await vi.waitFor(() =>
      expect(h.log).toHaveBeenCalledWith(expect.stringContaining("could not open")),
    );
  });
});

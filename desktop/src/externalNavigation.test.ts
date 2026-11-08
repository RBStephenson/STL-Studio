import { describe, expect, it, vi } from "vitest";

import { classifyNavigation, decideWindowOpen, routeNavigation } from "./externalNavigation";

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

describe("decideWindowOpen (STUDIO-463)", () => {
  function host() {
    return { openExternal: vi.fn().mockResolvedValue(undefined), log: vi.fn() };
  }

  it.each([
    "http://127.0.0.1:5555/models/42",
    "http://localhost:8484/models/42",
    "http://[::1]:8484/models/42",
  ])("opens the app's own page %s in a new app window", (url) => {
    const h = host();
    expect(decideWindowOpen(url, h)).toBe("allow");
    expect(h.openExternal).not.toHaveBeenCalled();
    expect(h.log).not.toHaveBeenCalled();
  });

  it("refuses a new window for a file: target even though it may load in place", () => {
    const h = host();
    expect(classifyNavigation("file:///C:/Windows/win.ini")).toBe("internal");
    expect(decideWindowOpen("file:///C:/Windows/win.ini", h)).toBe("deny");
    expect(h.openExternal).not.toHaveBeenCalled();
    expect(h.log).toHaveBeenCalledWith(expect.stringContaining("blocked new window"));
  });

  it("sends an external https target to the browser instead of a window", () => {
    const h = host();
    expect(decideWindowOpen("https://www.patreon.com/x", h)).toBe("deny");
    expect(h.openExternal).toHaveBeenCalledWith("https://www.patreon.com/x");
  });

  it.each(["ms-msdt:/id PCWDiagnostic", "http://example.com/x", "javascript:alert(1)", "not a url"])(
    "denies %s without touching the shell",
    (url) => {
      const h = host();
      expect(decideWindowOpen(url, h)).toBe("deny");
      expect(h.openExternal).not.toHaveBeenCalled();
      expect(h.log).toHaveBeenCalledWith(expect.stringContaining("blocked navigation"));
    },
  );
});

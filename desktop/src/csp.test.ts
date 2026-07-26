import { describe, expect, it, vi } from "vitest";

import {
  CSP_DIRECTIVES,
  applyCspHeaders,
  buildCspHeader,
  registerCspHandler,
  type HeadersReceivedListener,
} from "./csp";

function directive(name: string): string | undefined {
  return CSP_DIRECTIVES.find((d) => d.startsWith(`${name} `) || d === name);
}

describe("buildCspHeader", () => {
  it("joins directives into a single header value", () => {
    expect(buildCspHeader()).toBe(CSP_DIRECTIVES.join("; "));
  });

  it("blocks inline script, the sink an XSS in guide HTML would need", () => {
    expect(directive("script-src")).toBe("script-src 'self'");
  });

  it("allows remote https images so scraped storefront thumbnails still render", () => {
    expect(directive("img-src")).toContain("https:");
  });

  it("denies plugin and framing vectors outright", () => {
    expect(directive("object-src")).toBe("object-src 'none'");
    expect(directive("frame-ancestors")).toBe("frame-ancestors 'none'");
  });
});

describe("applyCspHeaders", () => {
  it("adds the policy when the response carries no headers", () => {
    expect(applyCspHeaders(undefined)).toEqual({ "Content-Security-Policy": [buildCspHeader()] });
  });

  it("preserves unrelated headers", () => {
    const result = applyCspHeaders({ "content-type": ["text/html"], "x-request-id": ["abc"] });
    expect(result["content-type"]).toEqual(["text/html"]);
    expect(result["x-request-id"]).toEqual(["abc"]);
  });

  it("replaces an inbound policy instead of stacking a second one", () => {
    // Two policies intersect rather than override, so a backend header left in
    // place could silently tighten ours and break rendering.
    const result = applyCspHeaders({ "Content-Security-Policy": ["default-src 'none'"] });
    expect(result["Content-Security-Policy"]).toEqual([buildCspHeader()]);
    expect(Object.keys(result)).toHaveLength(1);
  });

  it.each([
    "content-security-policy",
    "CONTENT-SECURITY-POLICY",
    "Content-Security-Policy-Report-Only",
  ])("drops an inbound %s regardless of casing", (name) => {
    const result = applyCspHeaders({ [name]: ["default-src 'none'"] });
    expect(Object.keys(result)).toEqual(["Content-Security-Policy"]);
    expect(result["Content-Security-Policy"]).toEqual([buildCspHeader()]);
  });
});

describe("registerCspHandler", () => {
  it("rewrites headers through the session callback", () => {
    let listener: HeadersReceivedListener | undefined;
    const onHeadersReceived = vi.fn((fn: HeadersReceivedListener) => {
      listener = fn;
    });

    registerCspHandler({ webRequest: { onHeadersReceived } });
    expect(onHeadersReceived).toHaveBeenCalledOnce();

    const callback = vi.fn();
    listener?.({ responseHeaders: { "content-type": ["text/html"] } }, callback);

    expect(callback).toHaveBeenCalledWith({
      responseHeaders: {
        "content-type": ["text/html"],
        "Content-Security-Policy": [buildCspHeader()],
      },
    });
  });
});

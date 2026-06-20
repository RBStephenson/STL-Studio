import { describe, it, expect } from "vitest";
import { sanitize, sanitizeUrl, sanitizeCss } from "./sanitizeHtml";

describe("sanitize", () => {
  it.each([
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(1)">x</a>',
    '<div onclick="x()">y</div>',
    '<iframe src="http://evil"></iframe>',
    "<svg/onload=alert(1)>",
  ])("strips active content: %s", (payload) => {
    const out = sanitize(payload).toLowerCase();
    expect(out).not.toContain("<script");
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("onclick");
    expect(out).not.toContain("onload");
    expect(out).not.toContain("javascript:");
    expect(out).not.toContain("<iframe");
  });

  it("preserves safe formatting and links", () => {
    expect(sanitize("<strong>b</strong> <em>i</em>")).toContain("<strong>b</strong>");
    expect(sanitize('<a href="https://e.com">l</a>')).toContain('href="https://e.com"');
  });

  it("keeps class hooks for raw blocks", () => {
    expect(sanitize('<div class="tier-card">x</div>')).toContain('class="tier-card"');
  });

  it("handles empty", () => {
    expect(sanitize(null)).toBe("");
    expect(sanitize(undefined)).toBe("");
  });
});

describe("sanitizeUrl", () => {
  it.each(["javascript:alert(1)", "data:text/html,x", "vbscript:x", "//evil.com"])(
    "rejects unsafe: %s",
    (u) => expect(sanitizeUrl(u)).toBeUndefined(),
  );

  it.each(["https://e.com", "http://e.com", "mailto:a@b.com", "/rel", "#a"])(
    "allows safe: %s",
    (u) => expect(sanitizeUrl(u)).toBe(u),
  );

  it("handles empty", () => {
    expect(sanitizeUrl(null)).toBeUndefined();
    expect(sanitizeUrl("")).toBeUndefined();
  });
});

describe("sanitizeCss", () => {
  it.each([
    "</style><script>alert(1)</script>",
    "@import url('http://evil/x.css');",
    "a{x:expression(alert(1))}",
    ".x{background:url(javascript:alert(1))}",
  ])("neutralizes vectors: %s", (css) => {
    const out = sanitizeCss(css).toLowerCase();
    expect(out).not.toContain("<");
    expect(out).not.toContain("@import");
    expect(out).not.toContain("expression(");
    expect(out).not.toContain("javascript:");
  });

  it("preserves plain css", () => {
    const css = ".guide-reader{color:#fff;background:#101010}";
    expect(sanitizeCss(css)).toBe(css);
  });
});

// Render-time sanitization for guide content (#440).
//
// Guide HTML is sanitized on the backend at import time, but the reader
// sanitizes again as defense-in-depth and to cover guides stored before the
// backend fix landed. All `dangerouslySetInnerHTML` sinks in GuideReader must
// route their value through `sanitize()`.
import DOMPurify from "dompurify";

// Mirror the backend allowlist (app/painting/services/sanitize.py).
const ALLOWED_TAGS = [
  "a", "abbr", "b", "br", "code", "em", "i", "kbd", "mark", "s", "small",
  "span", "strong", "sub", "sup", "u",
  "blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "ol",
  "p", "pre", "ul",
  "table", "tbody", "td", "th", "thead", "tr",
];

const ALLOWED_ATTR = ["class", "href", "title", "target", "colspan", "rowspan"];

export function sanitize(html: string | null | undefined): string {
  if (!html) return "";
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    // Block javascript:/data: etc.; DOMPurify's default URI policy already
    // strips dangerous schemes, and inline event handlers are removed.
    FORBID_TAGS: ["style", "script", "iframe", "object", "embed"],
    FORBID_ATTR: ["style"],
  });
}

const SAFE_URL = /^(https?:|mailto:|\/|#)/i;

// Allow only http(s)/mailto/relative/fragment links (e.g. creator-credit href).
export function sanitizeUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  // eslint-disable-next-line no-control-regex -- stripping control chars is the point
  const trimmed = url.replace(/[\x00-\x20]/g, "");
  if (trimmed.startsWith("//")) return undefined; // protocol-relative
  return SAFE_URL.test(trimmed) ? trimmed : undefined;
}

// Neutralize a guide's head_style CSS before injecting it as a <style> tag.
// Mirrors backend sanitize_css; the backend already cleans this on import, so
// this only hardens guides imported before the fix.
export function sanitizeCss(css: string | null | undefined): string {
  if (!css) return "";
  let out = css.replace(/[<>]/g, "");
  out = out.replace(/@import[^;]*;?/gi, "");
  out = out.replace(/expression\s*\([^)]*\)/gi, "");
  out = out.replace(/(javascript|vbscript)\s*:/gi, "");
  out = out.replace(
    /url\s*\(\s*['"]?\s*(?:javascript|vbscript|data)\s*:[^)]*\)/gi,
    "",
  );
  return out.trim();
}

/**
 * Content-Security-Policy enforcement at the Electron session layer (STUDIO-258).
 *
 * The app window loads the sidecar's origin (`loadURL(backendUrl)`), and the
 * FastAPI backend sends no CSP header of its own — so without this the live app
 * runs with no policy at all. Enforcing here rather than in the backend means the
 * policy holds regardless of what the sidecar responds with, and covers the
 * file:// pages (splash, offline fallback) in the same pass.
 *
 * The policy is deliberately not maximally strict; each relaxation below is
 * required by real rendering paths, and tightening one silently breaks a feature
 * (CSP violations are console-only).
 */

export const CSP_DIRECTIVES: readonly string[] = [
  "default-src 'self'",
  // No inline scripts in the Vite build, so this can stay strict — it is the
  // directive that actually contains an XSS via the sanitized guide-HTML sinks.
  "script-src 'self'",
  // React inline `style={{}}` and three/drei both emit inline styles.
  "style-src 'self' 'unsafe-inline'",
  // Scraped storefront thumbnails render straight from arbitrary CDNs
  // (FindOnWeb, MetadataEditor, StorefrontEnrich), so remote https is required.
  "img-src 'self' data: blob: https:",
  "media-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  // No worker-src: the bundle constructs no workers, so default-src governs.
  // Add `worker-src 'self' blob:` if a loader (three.js draco/ktx2) ever needs one.
  "object-src 'none'",
  "frame-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
];

export function buildCspHeader(): string {
  return CSP_DIRECTIVES.join("; ");
}

/** Matches Electron's own header shape — a bare string value is not assignable
 *  to `HeadersReceivedResponse`, so keep this as arrays. */
export type ResponseHeaders = Record<string, string[]>;

export interface HeadersReceivedDetails {
  responseHeaders?: ResponseHeaders;
}

export interface HeadersReceivedResponse {
  responseHeaders: ResponseHeaders;
}

export type HeadersReceivedListener = (
  details: HeadersReceivedDetails,
  callback: (response: HeadersReceivedResponse) => void,
) => void;

export interface CspSession {
  webRequest: {
    onHeadersReceived(listener: HeadersReceivedListener): void;
  };
}

const CSP_HEADER_NAME = "Content-Security-Policy";

/** Header names are case-insensitive on the wire, so any casing of an inbound
 *  policy has to be dropped — otherwise ours would be *added* alongside it, and
 *  browsers intersect multiple policies rather than letting the last one win. */
function isCspHeader(name: string): boolean {
  const lowered = name.toLowerCase();
  return lowered === "content-security-policy" || lowered === "content-security-policy-report-only";
}

/** Replace (never merge) any inbound CSP with ours. */
export function applyCspHeaders(headers: ResponseHeaders | undefined): ResponseHeaders {
  const next: ResponseHeaders = {};
  for (const [name, value] of Object.entries(headers ?? {})) {
    if (!isCspHeader(name)) next[name] = value;
  }
  next[CSP_HEADER_NAME] = [buildCspHeader()];
  return next;
}

export function registerCspHandler(session: CspSession): void {
  session.webRequest.onHeadersReceived((details, callback) => {
    callback({ responseHeaders: applyCspHeaders(details.responseHeaders) });
  });
}

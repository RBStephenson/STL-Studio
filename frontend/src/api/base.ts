// Shared HTTP plumbing for the api/* domain modules (#STUDIO-62). The domain
// slices in models.ts / painting.ts / etc. import `request` + `BASE` from here;
// only `ApiError` and the two stamp option types are re-exported from the
// public barrel (client.ts) — the rest is internal to the api layer.

export const BASE = "/api";

// Error carrying the HTTP status so callers can distinguish a 404 (resource
// gone) from a 5xx or a network failure. Still an Error, so existing handlers
// that only read `.message` keep working.
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const d = (await res.json()).detail;
      // Some endpoints return a structured detail ({message, ...}); surface the
      // message rather than "[object Object]".
      detail = typeof d === "string" ? d : d?.message;
    } catch { /* ignore */ }
    throw new ApiError(res.status, detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

// Per-export reward-stamping options for PDF endpoints (#490/#511). Omitted
// fields fall back to the server defaults (footer on, watermark off).
export interface StampOptions {
  footer?: boolean;
  tier?: string;
  watermark?: boolean;
}

export interface SeriesExportOptions extends StampOptions {
  cover?: boolean;
}

export function stampQuery(opts: SeriesExportOptions): string {
  const params = new URLSearchParams();
  if (opts.cover !== undefined) params.set("cover", String(opts.cover));
  if (opts.footer !== undefined) params.set("footer", String(opts.footer));
  if (opts.tier) params.set("tier", opts.tier);
  if (opts.watermark !== undefined) params.set("watermark", String(opts.watermark));
  const q = params.toString();
  return q ? `?${q}` : "";
}

// Trigger a browser download of `blob` named `filename` (STUDIO-94). Shared by
// every blob-download call site so they can't drift back out of sync: create
// the object URL, click a temp anchor, then revoke on the next tick rather
// than synchronously — some browsers cancel/corrupt the download if the URL
// is revoked before the download stack has consumed it.
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

// Fetch a PDF blob and trigger a browser download. Blob endpoints can't go
// through request(); this surfaces the 503 "Chromium not installed" / 404 detail
// like the other download helpers. The server's Content-Disposition filename
// wins when present (e.g. the series-bundle slug), else `fallbackName`.
export async function downloadPdf(url: string, fallbackName: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new ApiError(res.status, detail);
  }
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const name = match ? match[1] : fallbackName;
  triggerBlobDownload(await res.blob(), name);
}

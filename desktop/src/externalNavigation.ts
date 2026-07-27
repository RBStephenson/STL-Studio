/**
 * Navigation policy for renderer-initiated links (STUDIO-259).
 *
 * Without this, `window.open` / `target="_blank"` in the app UI opens the remote
 * page in a chromeless Electron window — no address bar, so the user cannot see
 * where they are. The Help page ships several such links (Patreon, Buy Me a
 * Coffee, PaintRack, the project wiki), so this is a live path, not a
 * hypothetical one.
 *
 * It also matters for STUDIO-258: the CSP handler applies the app's policy to
 * every response in the default session, so an external page opened in-app
 * renders broken. Sending those links to the system browser takes them out of
 * the Electron session entirely.
 *
 * Everything here is pure — main.ts binds the verdict to shell.openExternal.
 */

/** Hosts the sidecar can bind. The port is OS-assigned at startup, so the
 *  origin cannot be compared literally — host + scheme is the stable part. */
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

export type NavigationVerdict =
  /** Our own UI or bundled HTML — let it load in the window. */
  | "internal"
  /** Hand to the system browser via shell.openExternal. */
  | "external"
  /** Block outright. */
  | "deny";

/**
 * Classify a navigation or window-open target.
 *
 * `https:` is the only scheme handed to the OS. `shell.openExternal` delegates
 * to the platform handler, which on Windows will happily launch a registered
 * protocol handler — so passing through arbitrary schemes (`file:`, `ms-msdt:`,
 * custom app protocols) turns a link in scraped content into local code
 * execution. Denying by default is the point of this function.
 */
export function classifyNavigation(url: string): NavigationVerdict {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return "deny";
  }

  if (parsed.protocol === "file:") return "internal";

  if (parsed.protocol === "http:" || parsed.protocol === "https:") {
    if (LOOPBACK_HOSTS.has(parsed.hostname)) return "internal";
    // Remote plain http is denied rather than opened: the app links only to
    // https, so an http target means content we did not author.
    return parsed.protocol === "https:" ? "external" : "deny";
  }

  return "deny";
}

export interface NavigationHost {
  openExternal(url: string): Promise<void> | void;
  log(message: string): void;
}

/** Route a renderer-initiated target. Returns whether the window may load it. */
export function routeNavigation(url: string, host: NavigationHost): boolean {
  const verdict = classifyNavigation(url);
  if (verdict === "internal") return true;
  if (verdict === "external") {
    void Promise.resolve(host.openExternal(url)).catch((error: unknown) => {
      host.log(`[navigation] could not open ${url} externally: ${String(error)}`);
    });
    return false;
  }
  host.log(`[navigation] blocked navigation to ${url}`);
  return false;
}

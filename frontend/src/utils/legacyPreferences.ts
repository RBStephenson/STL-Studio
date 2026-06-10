import { AppSettings, FilterPreset } from "../api/client";

// Pre-#32 localStorage keys, migrated once into the server-side settings
// store and then removed.
const NSFW_KEY = "showNSFW";
const PRESETS_KEY = "stl_filter_presets";

function readLegacyPresets(): FilterPreset[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(PRESETS_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (p): p is FilterPreset =>
        p != null && typeof p.name === "string" && typeof p.qs === "string"
    );
  } catch {
    return [];
  }
}

/** Build the settings patch for any legacy localStorage preferences that
 *  should move to the server. A value is migrated only when it differs from
 *  the server's current state, so stale local copies never overwrite
 *  preferences another browser already persisted. */
export function collectLegacyPreferences(server: AppSettings): Partial<AppSettings> {
  const patch: Partial<AppSettings> = {};
  try {
    if (localStorage.getItem(NSFW_KEY) === "true" && !server.show_nsfw) {
      patch.show_nsfw = true;
    }
    const presets = readLegacyPresets();
    if (presets.length > 0 && server.filter_presets.length === 0) {
      patch.filter_presets = presets;
    }
  } catch {
    // localStorage unavailable — nothing to migrate.
  }
  return patch;
}

/** Remove the legacy keys so the migration runs at most once per browser. */
export function clearLegacyPreferences() {
  try {
    localStorage.removeItem(NSFW_KEY);
    localStorage.removeItem(PRESETS_KEY);
  } catch {
    // ignore
  }
}

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api, AppSettings, FilterPreset } from "../api/client";
import { collectLegacyPreferences, clearLegacyPreferences } from "../utils/legacyPreferences";
import { useToast } from "./ToastContext";

// Mirrors the backend DEFAULTS in routers/settings.py — used until the
// server responds, so gated UI stays hidden during the initial fetch.
const DEFAULTS: AppSettings = {
  painting_guides_enabled: false,
  show_nsfw: false,
  library_page_size: 48,
  filter_presets: [],
  recent_days: 7,
  library_sort: "name",
  scan_ignore_patterns: [],
  scan_tag_rules: [],
  scan_parts_names: [],
  guide_theme_defaults: {},
  ai_model: "",
  ai_effort: "low",
  part_categories_enabled: false,
  horizontal_parts_layout: false,
  gallery_enabled: true,
  gallery_auto_rotate: true,
  gallery_rotation_seconds: 10,
  ai_organize_enabled: false,
  ai_organize_url: "",
  ai_organize_model: "",
  ai_guides_enabled: false,
  ai_guides_api: null,
  ai_organize_api: null,
  log_level: "INFO",
  reorganize_template: "",
  reorganize_slugify: true,
  reorganize_enabled: false,
  collections_uniform_size: true,
};

interface AppSettingsContextValue {
  settings: AppSettings;
  // True once the initial load has settled, success or failure (STUDIO-96) —
  // lets a consumer distinguish "still loading defaults" from "server confirmed".
  loaded: boolean;
  // True if the initial load failed — `settings` is the hardcoded fallback,
  // not server-confirmed, so gated behavior (NSFW visibility, page size, AI
  // settings) may silently differ from what the user actually configured.
  loadError: boolean;
  update: (patch: Partial<AppSettings>) => Promise<void>;
  // Atomic single-preset writes (#287): the server mutates the stored list, so
  // these can't clobber unrelated presets the way a whole-list PATCH could.
  upsertPreset: (preset: FilterPreset) => Promise<void>;
  deletePreset: (name: string) => Promise<void>;
}

const AppSettingsContext = createContext<AppSettingsContextValue>({
  settings: DEFAULTS,
  loaded: false,
  loadError: false,
  update: async () => {},
  upsertPreset: async () => {},
  deletePreset: async () => {},
});

export function AppSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(DEFAULTS);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    api.settings
      .get()
      .then(async (server) => {
        // One-time migration of preferences that used to live in
        // localStorage (#32). Only pushed when they differ from the
        // server defaults, so a migrated browser can't clobber values
        // another browser already saved.
        const patch = collectLegacyPreferences(server);
        if (Object.keys(patch).length > 0) {
          const updated = await api.settings.update(patch);
          clearLegacyPreferences();
          setSettings(updated);
        } else {
          clearLegacyPreferences();
          setSettings(server);
        }
        setLoaded(true);
      })
      .catch(() => {
        setLoadError(true);
        setLoaded(true);
        toast(
          "Couldn't load settings from the server — using defaults, which may not match what you've configured.",
          "error",
        );
      });
  }, [toast]);

  const update = async (patch: Partial<AppSettings>) => {
    setSettings(await api.settings.update(patch));
  };

  const upsertPreset = async (preset: FilterPreset) => {
    setSettings(await api.settings.upsertPreset(preset));
  };

  const deletePreset = async (name: string) => {
    setSettings(await api.settings.deletePreset(name));
  };

  return (
    <AppSettingsContext.Provider value={{ settings, loaded, loadError, update, upsertPreset, deletePreset }}>
      {children}
    </AppSettingsContext.Provider>
  );
}

export const useAppSettings = () => useContext(AppSettingsContext);

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api, AppSettings, FilterPreset } from "../api/client";
import { collectLegacyPreferences, clearLegacyPreferences } from "../utils/legacyPreferences";

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
};

interface AppSettingsContextValue {
  settings: AppSettings;
  update: (patch: Partial<AppSettings>) => Promise<void>;
  // Atomic single-preset writes (#287): the server mutates the stored list, so
  // these can't clobber unrelated presets the way a whole-list PATCH could.
  upsertPreset: (preset: FilterPreset) => Promise<void>;
  deletePreset: (name: string) => Promise<void>;
}

const AppSettingsContext = createContext<AppSettingsContextValue>({
  settings: DEFAULTS,
  update: async () => {},
  upsertPreset: async () => {},
  deletePreset: async () => {},
});

export function AppSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(DEFAULTS);

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
      })
      .catch(() => {});
  }, []);

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
    <AppSettingsContext.Provider value={{ settings, update, upsertPreset, deletePreset }}>
      {children}
    </AppSettingsContext.Provider>
  );
}

export const useAppSettings = () => useContext(AppSettingsContext);

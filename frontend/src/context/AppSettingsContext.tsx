import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api, AppSettings } from "../api/client";
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
};

interface AppSettingsContextValue {
  settings: AppSettings;
  update: (patch: Partial<AppSettings>) => Promise<void>;
}

const AppSettingsContext = createContext<AppSettingsContextValue>({
  settings: DEFAULTS,
  update: async () => {},
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

  return (
    <AppSettingsContext.Provider value={{ settings, update }}>
      {children}
    </AppSettingsContext.Provider>
  );
}

export const useAppSettings = () => useContext(AppSettingsContext);

import { useAppSettings } from "./AppSettingsContext";

// The NSFW preference lives in the server-side app_settings store (#32).
// This hook keeps the original useNSFW interface so consumers don't care
// where the value is persisted. The old localStorage value is migrated
// once by AppSettingsProvider.
export function useNSFW() {
  const { settings, update } = useAppSettings();
  return {
    showNSFW: settings.show_nsfw,
    toggle: () => {
      void update({ show_nsfw: !settings.show_nsfw });
    },
  };
}

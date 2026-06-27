import { useAppSettings } from "../../context/AppSettingsContext";
import FlashBanner from "./FlashBanner";
import { useSettingsFlash } from "./useSettingsFlash";

export default function PreferencesTab() {
  const { settings, update } = useAppSettings();
  const { success, error, flash } = useSettingsFlash();

  const setPageSize = async (n: number) => {
    try {
      await update({ library_page_size: n });
    } catch (e: any) {
      flash(e?.message || "Could not update setting", "err");
    }
  };

  const setRecentDays = async (n: number) => {
    try {
      await update({ recent_days: n });
    } catch (e: any) {
      flash(e?.message || "Could not update setting", "err");
    }
  };

  return (
    <div>
      <FlashBanner success={success} error={error} />
      <p className="text-xs text-gray-600 mb-6">
        Preferences are stored server-side and follow you across browsers and devices.
        The NSFW toggle in the navbar and your saved Library filter presets are persisted the same way.
      </p>
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 self-start">
          <span className="text-sm text-gray-200">Library page size</span>
          <div className="flex rounded overflow-hidden border border-gray-700">
            {[24, 48, 96].map((n) => (
              <button
                key={n}
                onClick={() => setPageSize(n)}
                className={`px-3 py-1 text-xs transition-colors ${
                  settings.library_page_size === n
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:text-gray-200"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 self-start">
          <span className="text-sm text-gray-200">"New" badge window</span>
          <div className="flex rounded overflow-hidden border border-gray-700">
            {[3, 7, 14, 30].map((n) => (
              <button
                key={n}
                onClick={() => setRecentDays(n)}
                className={`px-3 py-1 text-xs transition-colors ${
                  settings.recent_days === n
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:text-gray-200"
                }`}
              >
                {n}d
              </button>
            ))}
          </div>
          <span className="text-xs text-gray-600">drives the Library's "recently added" filter</span>
        </div>
      </div>
    </div>
  );
}

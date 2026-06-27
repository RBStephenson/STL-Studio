import { Paintbrush } from "lucide-react";
import { useAppSettings } from "../../context/AppSettingsContext";
import ThemeEditor from "../../components/guide/ThemeEditor";
import { GuideTheme } from "../../api/client";
import FlashBanner from "./FlashBanner";
import { useSettingsFlash } from "./useSettingsFlash";

export default function PaintingTab() {
  const { settings, update } = useAppSettings();
  const { success, error, flash } = useSettingsFlash();

  const togglePaintingGuides = async () => {
    const next = !settings.painting_guides_enabled;
    try {
      await update({ painting_guides_enabled: next });
      flash(next ? "Painting Guides enabled" : "Painting Guides disabled", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not update setting", "err");
    }
  };

  const saveThemeDefaults = async (theme: GuideTheme) => {
    try {
      await update({ guide_theme_defaults: theme });
    } catch (e: any) {
      flash(e?.message || "Could not save theme defaults", "err");
    }
  };

  return (
    <div>
      <FlashBanner success={success} error={error} />

      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Paintbrush size={14} /> Painting Guides
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Author step-by-step painting guides for your models. Enabling this adds{" "}
          <strong className="text-gray-500">Guides</strong> to the navigation. The{" "}
          <strong className="text-gray-500">Paint Shelf</strong> is always available.
        </p>
        <label className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 cursor-pointer select-none self-start">
          <input
            type="checkbox"
            checked={settings.painting_guides_enabled}
            onChange={togglePaintingGuides}
            className="h-4 w-4 accent-indigo-500"
          />
          <span className="text-sm text-gray-200">Enable Painting Guides</span>
        </label>
      </section>

      {settings.painting_guides_enabled && (
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1">
            Default Guide Theme
          </h2>
          <p className="text-xs text-gray-600 mb-3">
            New guides inherit these colors. Each guide can override them in its editor.
          </p>
          <ThemeEditor
            value={settings.guide_theme_defaults}
            onChange={saveThemeDefaults}
          />
        </section>
      )}
    </div>
  );
}

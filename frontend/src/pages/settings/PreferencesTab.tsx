import { FolderOpen, Images, RotateCw, Tag, LayoutPanelTop, ScrollText } from "lucide-react";
import { useAppSettings } from "../../context/AppSettingsContext";
import { LogLevel } from "../../api/client";
import FlashBanner from "./FlashBanner";
import { useSettingsFlash } from "./useSettingsFlash";
import { errMsg } from "../../utils/err";

const LOG_LEVELS: LogLevel[] = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

export default function PreferencesTab() {
  const { settings, update } = useAppSettings();
  const { success, error, flash } = useSettingsFlash();

  const setPageSize = async (n: number) => {
    try {
      await update({ library_page_size: n });
    } catch (e) {
      flash(errMsg(e) || "Could not update setting", "err");
    }
  };

  const setRecentDays = async (n: number) => {
    try {
      await update({ recent_days: n });
    } catch (e) {
      flash(errMsg(e) || "Could not update setting", "err");
    }
  };

  const setLogLevel = async (level: LogLevel) => {
    try {
      await update({ log_level: level });
    } catch (e) {
      flash(errMsg(e) || "Could not update setting", "err");
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
      {/* Part Categories */}
      <section className="mt-8 pt-6 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <Tag size={14} /> Part Categories
        </h2>
        <label className="flex items-start gap-3 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={settings.part_categories_enabled}
            onChange={() => update({ part_categories_enabled: !settings.part_categories_enabled })}
            className="mt-0.5 accent-indigo-500"
          />
          <div>
            <p className="text-sm text-gray-300">Enable part categories</p>
            <p className="text-xs text-gray-500 mt-0.5">
              Adds a Category field to each file in the model detail view. Files group into
              collapsible sections and the 3D viewer organises its part picker by category.
              Useful for complex multi-part kits.
            </p>
          </div>
        </label>
      </section>

      {/* Image Gallery */}
      <section className="mt-8 pt-6 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <Images size={14} /> Image Gallery
        </h2>
        <div className="flex flex-col gap-4">
          <label className="flex items-start gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={settings.gallery_enabled}
              onChange={() => update({ gallery_enabled: !settings.gallery_enabled })}
              className="mt-0.5 accent-indigo-500"
            />
            <div>
              <p className="text-sm text-gray-300">Enable image gallery</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Shows scanned image galleries on model detail pages. Turn this off to use only
                the selected thumbnail image.
              </p>
            </div>
          </label>

          <label className="flex items-start gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={settings.gallery_auto_rotate}
              disabled={!settings.gallery_enabled}
              onChange={() => update({ gallery_auto_rotate: !settings.gallery_auto_rotate })}
              className="mt-0.5 accent-indigo-500 disabled:opacity-40"
            />
            <div>
              <p className="text-sm text-gray-300">Auto-rotate gallery images</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Automatically advances multi-image galleries in the model detail view.
              </p>
            </div>
          </label>

          <div className={`flex items-center gap-3 self-start ${
            settings.gallery_enabled && settings.gallery_auto_rotate ? "" : "opacity-50"
          }`}>
            <span className="text-sm text-gray-300 flex items-center gap-1.5">
              <RotateCw size={14} /> Rotation interval
            </span>
            <div className="flex rounded overflow-hidden border border-gray-700">
              {[5, 10, 20, 30].map((n) => (
                <button
                  key={n}
                  disabled={!settings.gallery_enabled || !settings.gallery_auto_rotate}
                  onClick={() => update({ gallery_rotation_seconds: n })}
                  className={`px-3 py-1 text-xs transition-colors disabled:cursor-not-allowed ${
                    settings.gallery_rotation_seconds === n
                      ? "bg-indigo-600 text-white"
                      : "bg-gray-800 text-gray-400 hover:text-gray-200 disabled:hover:text-gray-400"
                  }`}
                >
                  {n}s
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Horizontal Parts Layout */}
      <section className="mt-8 pt-6 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <LayoutPanelTop size={14} /> Parts Display
        </h2>
        <label className="flex items-start gap-3 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={settings.horizontal_parts_layout}
            onChange={() => update({ horizontal_parts_layout: !settings.horizontal_parts_layout })}
            className="mt-0.5 accent-indigo-500"
          />
          <div>
            <p className="text-sm text-gray-300">Horizontal parts layout</p>
            <p className="text-xs text-gray-500 mt-0.5">
              Displays the STL file list as a full-width table below the model images and info,
              with an editable Name column. Collections and Location move below the two-column area.
            </p>
          </div>
        </label>
      </section>

      {/* Collections */}
      <section className="mt-8 pt-6 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <FolderOpen size={14} /> Collections
        </h2>
        <label className="flex items-start gap-3 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={settings.collections_uniform_size}
            onChange={() => update({ collections_uniform_size: !settings.collections_uniform_size })}
            className="mt-0.5 accent-indigo-500"
          />
          <div>
            <p className="text-sm text-gray-300">Uniform collection card size</p>
            <p className="text-xs text-gray-500 mt-0.5">
              Gives every collection the same box size, whether or not it has a cover image, instead
              of a compact box for collections with none. Collections with a cover image always use
              the larger size.
            </p>
          </div>
        </label>
      </section>

      {/* Logging */}
      <section className="mt-8 pt-6 border-t border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <ScrollText size={14} /> Logging
        </h2>
        <div className="flex items-center gap-3 self-start">
          <span className="text-sm text-gray-300">Server log level</span>
          <div className="flex rounded overflow-hidden border border-gray-700">
            {LOG_LEVELS.map((level) => (
              <button
                key={level}
                onClick={() => setLogLevel(level)}
                className={`px-3 py-1 text-xs transition-colors ${
                  settings.log_level === level
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:text-gray-200"
                }`}
              >
                {level}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-gray-500 mt-2">
          Controls how much the backend logs to its output (visible via{" "}
          <code className="text-gray-400">docker compose logs -f backend</code>). Takes effect
          immediately — no restart needed. Use <span className="text-gray-400">DEBUG</span> to see
          full AI request/response detail; leave at <span className="text-gray-400">INFO</span> for
          normal operation.
        </p>
      </section>
    </div>
  );
}

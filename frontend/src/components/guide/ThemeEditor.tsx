import { GuideTheme } from "../../api/client";

interface Props {
  value: GuideTheme | null;
  onChange: (theme: GuideTheme) => void;
}

// Reader defaults (mirror guide-reader.css) — shown as the color-input value
// when a field is unset, so the picker starts from the real default (#515).
const DEFAULTS: Record<ColorField, string> = {
  bg: "#1a1a1a",
  surface: "#222222",
  surface2: "#2a2a2a",
  surface3: "#333333",
  border: "#3a3a3a",
  text: "#e8e8e8",
  text_muted: "#aaaaaa",
  text_dim: "#777777",
  accent: "#c0a060",
};

type ColorField =
  | "bg" | "surface" | "surface2" | "surface3" | "border"
  | "text" | "text_muted" | "text_dim" | "accent";

const COLOR_FIELDS: { field: ColorField; label: string }[] = [
  { field: "bg", label: "Background" },
  { field: "surface", label: "Surface" },
  { field: "surface2", label: "Surface 2" },
  { field: "surface3", label: "Surface 3" },
  { field: "border", label: "Border" },
  { field: "text", label: "Text" },
  { field: "text_muted", label: "Text muted" },
  { field: "text_dim", label: "Text dim" },
  { field: "accent", label: "Accent" },
];

const HEX = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/**
 * Color-picker editor over the GuideTheme fields (#515). Used for both a guide's
 * per-guide theme and the app-level default theme. All fields are optional — a
 * blank field falls back to the corpus default at render time.
 */
export default function ThemeEditor({ value, onChange }: Props) {
  const theme = value ?? {};

  const set = (field: keyof GuideTheme, v: string | null) =>
    onChange({ ...theme, [field]: v });

  const previewVars: Record<string, string> = {};
  for (const { field } of COLOR_FIELDS) {
    previewVars["--" + field.replace("_", "-")] = theme[field] || DEFAULTS[field];
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {COLOR_FIELDS.map(({ field, label }) => {
          const current = theme[field] ?? "";
          return (
            <div key={field}>
              <label className="block text-xs text-gray-400 mb-1">{label}</label>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  aria-label={`${label} color`}
                  value={theme[field] || DEFAULTS[field]}
                  onChange={(e) => set(field, e.target.value)}
                  className="h-8 w-8 rounded border border-gray-700 bg-transparent cursor-pointer"
                />
                <input
                  type="text"
                  aria-label={`${label} hex`}
                  value={current}
                  placeholder={DEFAULTS[field]}
                  onChange={(e) => set(field, e.target.value || null)}
                  className={
                    "w-full bg-gray-800 border rounded px-2 py-1 text-xs " +
                    (current && !HEX.test(current)
                      ? "border-rose-600"
                      : "border-gray-700")
                  }
                />
              </div>
            </div>
          );
        })}
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-1">
          Hero gradient (CSS)
        </label>
        <input
          type="text"
          aria-label="Hero gradient"
          value={theme.hero_gradient ?? ""}
          placeholder="linear-gradient(135deg, var(--surface2), var(--bg))"
          onChange={(e) => set("hero_gradient", e.target.value || null)}
          className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs"
        />
      </div>

      {/* Live preview — a mini hero driven by the theme vars. */}
      <div
        data-testid="theme-preview"
        style={{
          ...previewVars,
          background: theme.hero_gradient || "var(--surface2)",
          color: previewVars["--text"],
          border: `1px solid ${previewVars["--border"]}`,
        }}
        className="rounded p-4 text-center"
      >
        <div style={{ color: previewVars["--accent"] }} className="text-xs uppercase tracking-wide mb-1">
          Category
        </div>
        <div className="text-lg font-bold">
          Sample <span style={{ color: previewVars["--accent"] }}>Title</span>
        </div>
        <div style={{ color: previewVars["--text-muted"] }} className="text-xs mt-1">
          Subtitle preview text
        </div>
      </div>
    </div>
  );
}

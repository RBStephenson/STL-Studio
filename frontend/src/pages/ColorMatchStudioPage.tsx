import { useState } from "react";
import { Pipette, Loader2, ImagePlus, Eye, Droplet } from "lucide-react";
import {
  api, ApiError, ColorBand, ColorMatchCandidate, ColorMatchResult,
} from "../api/client";
import { useToast } from "../context/ToastContext";
import { ColorChip } from "./PaintShelfPage";
import HelpLink from "../components/HelpLink";

const ACCEPT = "image/png,image/jpeg,image/webp,image/gif";
const MAX_BYTES = 10 * 1024 * 1024; // mirror the backend cap
const ALLOWED_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

// ΔE2000 confidence bands (spec §8.6). Wording matches the backend contract.
const BAND_LABEL: Record<ColorBand, string> = {
  very_close: "very close",
  close: "close — confirm",
  family: "in the family",
  loose: "loose",
};
const BAND_CLASS: Record<ColorBand, string> = {
  very_close: "bg-emerald-950/60 text-emerald-300 border-emerald-800",
  close: "bg-lime-950/60 text-lime-300 border-lime-800",
  family: "bg-amber-950/60 text-amber-300 border-amber-800",
  loose: "bg-gray-800 text-gray-400 border-gray-700",
};

function BandPill({ band }: { band: ColorBand }) {
  return (
    <span className={`text-[10px] uppercase tracking-wide border rounded px-1.5 py-0.5 ${BAND_CLASS[band]}`}>
      {BAND_LABEL[band]}
    </span>
  );
}

/** One suggested paint. `metric` picks which distance to show (ΔE for hue, ΔL* for value). */
function CandidateRow({
  c, metric, grayscale,
}: { c: ColorMatchCandidate; metric: "delta_e" | "delta_l"; grayscale: boolean }) {
  const value = metric === "delta_e" ? c.delta_e : c.delta_l;
  const label = metric === "delta_e" ? "ΔE" : "ΔL*";
  return (
    <li className="flex items-center gap-2 py-1">
      <span style={grayscale ? { filter: "grayscale(1)" } : undefined}>
        <ColorChip hex={c.hex} size={18} />
      </span>
      <span className="text-sm text-gray-200 truncate">{c.name}</span>
      <span className="text-xs text-gray-500">{c.code}</span>
      <span className="text-xs text-gray-600 truncate hidden sm:inline">
        {c.brand} · {c.line}
      </span>
      <span className="ml-auto flex items-center gap-2">
        {value !== null && (
          <span className="text-xs text-gray-400 tabular-nums">{label} {value.toFixed(1)}</span>
        )}
        <BandPill band={c.band} />
      </span>
    </li>
  );
}

function CandidateList({
  title, items, metric, grayscale, hint,
}: {
  title: string;
  items: ColorMatchCandidate[];
  metric: "delta_e" | "delta_l";
  grayscale: boolean;
  hint?: string;
}) {
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400">{title}</h4>
        {hint && <span className="text-[11px] text-gray-600">{hint}</span>}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-gray-600 py-1">No owned paints to suggest.</p>
      ) : (
        <ul className="divide-y divide-gray-800/60">
          {items.map((c) => (
            <CandidateRow key={c.paint_id} c={c} metric={metric} grayscale={grayscale} />
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Color-match studio (#561, spec §8.6). Upload a reference image, sample it into
 * a k-means palette, and surface owned-paint suggestions per region — value
 * first, hue second, inks/glazes labelled separately. Suggest-and-confirm-by-eye
 * only: nothing is ever auto-assigned to a guide.
 */
export default function ColorMatchStudioPage() {
  const { toast } = useToast();
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult] = useState<ColorMatchResult | null>(null);
  const [valueMode, setValueMode] = useState(true);

  const run = async (file: File) => {
    if (!ALLOWED_TYPES.has(file.type)) {
      toast("Use a PNG, JPEG, WebP, or GIF image.", "error");
      return;
    }
    if (file.size > MAX_BYTES) {
      toast("Image is too large — the limit is 10 MB.", "error");
      return;
    }
    setBusy(true);
    setPreview(URL.createObjectURL(file));
    try {
      const res = await api.painting.colorMatch(file);
      setResult(res);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Color match failed — try again.";
      toast(msg, "error");
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (busy) return;
    const file = e.dataTransfer.files?.[0];
    if (file) run(file);
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <header className="flex items-center gap-2">
        <Pipette className="text-indigo-400" />
        <h1 className="text-xl font-semibold text-gray-100">Color-match studio</h1>
        <HelpLink section="color-match" />
      </header>

      <p className="text-sm text-gray-400">
        Drop a reference photo and we&apos;ll sample its main colors, then suggest paints
        from your shelf — value first, hue second.
      </p>

      <div className="grid gap-6 md:grid-cols-[260px_1fr]">
        {/* Upload + preview */}
        <div className="space-y-3">
          <label
            data-testid="colormatch-dropzone"
            onDragOver={(e) => { e.preventDefault(); if (!busy) setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center gap-2 border border-dashed rounded-lg px-6 py-8 text-center transition-colors ${
              busy ? "opacity-60 border-gray-700" : "cursor-pointer"
            } ${dragOver ? "border-indigo-500 bg-indigo-950/30" : "border-gray-700 hover:border-indigo-600"}`}
          >
            {busy
              ? <Loader2 size={22} className="animate-spin text-indigo-400" />
              : <ImagePlus size={22} className="text-indigo-400" />}
            <span className="text-sm text-gray-300">{busy ? "Matching…" : "Choose or drop an image"}</span>
            <span className="text-xs text-gray-600">PNG, JPEG, WebP, or GIF — up to 10 MB</span>
            <input
              type="file"
              accept={ACCEPT}
              className="hidden"
              data-testid="colormatch-input"
              disabled={busy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) run(f); e.target.value = ""; }}
            />
          </label>

          {preview && (
            <img
              src={preview}
              alt="Reference"
              style={valueMode ? { filter: "grayscale(1)" } : undefined}
              className="w-full rounded-lg border border-gray-700 object-contain"
            />
          )}

          {result && (
            <div className="space-y-1">
              <button
                type="button"
                onClick={() => setValueMode((v) => !v)}
                aria-pressed={valueMode}
                title="Desaturate everything — the reference, region swatches, and paint chips — so the whole view reads as values. Turn off to compare hues in full color."
                className={`inline-flex items-center gap-1.5 text-xs rounded px-2.5 py-1.5 border ${
                  valueMode
                    ? "border-indigo-600 text-indigo-300 bg-indigo-950/30"
                    : "border-gray-700 text-gray-300 hover:border-indigo-600"
                }`}
              >
                <Eye size={13} /> Value mode {valueMode ? "on" : "off"}
              </button>
              <p className="text-[11px] text-gray-600 leading-snug">
                Greys everything out so you can read values; turn off to compare hues in color.
              </p>
            </div>
          )}
        </div>

        {/* Results */}
        <div className="space-y-4">
          {!result && !busy && (
            <p className="text-sm text-gray-600">No image yet — your matches will appear here.</p>
          )}

          {result && (
            <>
              <p className="text-xs text-amber-300/90 bg-amber-950/30 border border-amber-900/50 rounded px-3 py-2">
                {result.caveat}
              </p>

              {result.regions.map((r, i) => (
                <section
                  key={i}
                  data-testid="colormatch-region"
                  className="rounded-lg border border-gray-800 bg-gray-900/40 p-4 space-y-4"
                >
                  <header className="flex items-center gap-3">
                    <span
                      data-testid="region-swatch"
                      className="inline-block rounded border border-gray-600"
                      style={{
                        width: 32, height: 32, backgroundColor: r.hex,
                        filter: valueMode ? "grayscale(1)" : undefined,
                      }}
                      title={r.hex}
                    />
                    <div>
                      <div className="text-sm text-gray-200">Region {i + 1}</div>
                      <div className="text-xs text-gray-500">
                        {Math.round(r.weight * 100)}% of image · value L* {r.value_l.toFixed(0)}
                      </div>
                    </div>
                  </header>

                  {/* Value-first ordering per spec §8.6. Value mode desaturates
                      every swatch (preview, region, and paint chips) so the whole
                      view reads as values. */}
                  <CandidateList
                    title="Value match"
                    hint="ranked by L* — includes metallics"
                    items={r.value_candidates}
                    metric="delta_l"
                    grayscale={valueMode}
                  />
                  <CandidateList
                    title="Hue match"
                    hint="opaque paints, ΔE2000"
                    items={r.hue_candidates}
                    metric="delta_e"
                    grayscale={valueMode}
                  />
                  {r.glaze_options.length > 0 && (
                    <div className="pt-1">
                      <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
                        <Droplet size={12} /> Glaze / shade options — transparent, color depends on what&apos;s beneath
                      </div>
                      <CandidateList
                        title="Glazes & washes"
                        items={r.glaze_options}
                        metric="delta_e"
                        grayscale={valueMode}
                      />
                    </div>
                  )}
                </section>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

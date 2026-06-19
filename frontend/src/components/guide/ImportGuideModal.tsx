import { useState } from "react";
import { Link } from "react-router-dom";
import { X, Upload, FileText, CheckCircle, Plus, SkipForward, Loader2 } from "lucide-react";
import { api, Guide, GuideImportReport, PaintOverrideInput, UnresolvedPaint } from "../../api/client";
import PaintPicker, { PickedPaint } from "./PaintPicker";

/**
 * Import a legacy guide HTML file (#277, #417).
 *
 * Flow: choose/drop file → dry-run preview. If every swatch paint resolves, the
 * guide is committed immediately. Otherwise the user resolves each unresolved
 * paint — map it to a shelf paint, force-add it to the shelf, or skip (drop) it
 * — then commits with those overrides. Lands as a draft for review.
 */
export function slugFromFilename(name: string): string {
  return name
    .replace(/\.html?$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// A per-paint resolution decision. `map`/`forced` both carry a paint_id for the
// override; `skip` drops the paint (the legacy behaviour).
type Decision =
  | { type: "map"; paint: PickedPaint }
  | { type: "forced"; paint: PickedPaint }
  | { type: "skip" };

// First occurrence of each unresolved name (the resolver keys on name, so one
// decision applies to every occurrence).
function uniqueByName(unresolved: UnresolvedPaint[]): UnresolvedPaint[] {
  const seen = new Set<string>();
  const out: UnresolvedPaint[] = [];
  for (const u of unresolved) {
    if (!seen.has(u.name)) {
      seen.add(u.name);
      out.push(u);
    }
  }
  return out;
}

export default function ImportGuideModal({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult] = useState<{ guide: Guide; report: GuideImportReport } | null>(null);

  // Resolution stage (#417): the dry-run report + the file to re-import on commit.
  const [preview, setPreview] = useState<
    { html: string; slug: string; report: GuideImportReport } | null
  >(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [forcing, setForcing] = useState<string | null>(null);

  const isHtmlFile = (file: File) =>
    /\.html?$/i.test(file.name) || file.type === "text/html";

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (busy) return;
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (!isHtmlFile(file)) {
      setError("Drop an HTML file (.html or .htm).");
      return;
    }
    handleFile(file);
  };

  const importErrorMessage = (e: unknown) => {
    const msg = (e as Error)?.message || "Import failed.";
    return msg.includes("409")
      ? "A guide with this slug already exists. Rename the file or delete the existing guide first."
      : msg;
  };

  const handleFile = async (file: File) => {
    setError(null);
    setBusy(true);
    try {
      const html = await file.text();
      const slug = slugFromFilename(file.name);
      if (!slug) {
        setError("Could not derive a slug from the filename. Rename the file and try again.");
        return;
      }
      // Preview first so unresolved paints can be resolved before committing.
      const { report } = await api.painting.guides.import_(html, slug, { dryRun: true });
      if (report.unresolved_paints.length === 0) {
        const res = await api.painting.guides.import_(html, slug);
        setResult(res as { guide: Guide; report: GuideImportReport });
      } else {
        setPreview({ html, slug, report });
      }
    } catch (e) {
      setError(importErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const forceAdd = async (u: UnresolvedPaint) => {
    setForcing(u.name);
    try {
      const paint = await api.painting.paints.forceAdd(u.name, u.hex);
      setDecisions((d) => ({
        ...d,
        [u.name]: { type: "forced", paint: { id: paint.id, name: paint.name, code: paint.code, hex: paint.hex } },
      }));
    } catch {
      setError(`Couldn't add "${u.name}" to the shelf — try again.`);
    } finally {
      setForcing(null);
    }
  };

  const commitImport = async () => {
    if (!preview) return;
    const paintOverrides: PaintOverrideInput[] = Object.entries(decisions)
      .filter(([, d]) => d.type !== "skip")
      .map(([name, d]) => ({ name, paint_id: (d as { paint: PickedPaint }).paint.id }));
    setBusy(true);
    setError(null);
    try {
      const res = await api.painting.guides.import_(preview.html, preview.slug, { paintOverrides });
      setResult(res as { guide: Guide; report: GuideImportReport });
      setPreview(null);
    } catch (e) {
      setError(importErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const report = result?.report;
  const unresolved = preview ? uniqueByName(preview.report.unresolved_paints) : [];
  const mappedCount = Object.values(decisions).filter((d) => d.type !== "skip").length;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
      data-testid="import-guide-modal"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Import guide"
        className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg shadow-2xl max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b border-gray-800">
          <h2 className="text-lg font-semibold text-white">Import guide</h2>
          <button onClick={onClose} aria-label="Close" className="text-gray-500 hover:text-gray-300">
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4">
          {/* ── Upload step ── */}
          {!result && !preview && (
            <>
              <p className="text-sm text-gray-400 mb-4">
                Upload a guide HTML file. It lands as a <span className="text-amber-400">draft</span>{" "}
                for review — never auto-published. Swatch paints are matched against your Paint Shelf;
                any that don't match, you'll resolve before importing.
              </p>
              <label
                data-testid="guide-dropzone"
                onDragOver={(e) => { e.preventDefault(); if (!busy) setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                className={`flex flex-col items-center gap-2 border border-dashed rounded-lg px-6 py-8 text-center transition-colors ${
                  busy ? "opacity-60 border-gray-700" : "cursor-pointer"
                } ${dragOver ? "border-indigo-500 bg-indigo-950/30" : "border-gray-700 hover:border-indigo-600"}`}
              >
                <Upload size={22} className="text-indigo-400" />
                <span className="text-sm text-gray-300">
                  {busy ? "Reading…" : "Choose or drop an HTML file"}
                </span>
                <input
                  type="file"
                  accept=".html,.htm,text/html"
                  className="hidden"
                  data-testid="guide-file-input"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleFile(f);
                    e.target.value = "";
                  }}
                />
              </label>
              {error && (
                <p role="alert" className="mt-3 text-sm text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded px-3 py-2">
                  {error}
                </p>
              )}
            </>
          )}

          {/* ── Resolution step (#417) ── */}
          {!result && preview && (
            <div data-testid="resolve-paints">
              <p className="text-sm text-gray-400 mb-3">
                <span className="text-rose-400">{unresolved.length}</span> swatch paint(s) aren't on
                your Paint Shelf. Map each to a paint, add it to the shelf, or skip it (it'll be
                dropped from the guide).
              </p>

              <ul className="space-y-2 max-h-72 overflow-y-auto mb-4">
                {unresolved.map((u) => {
                  const decision = decisions[u.name];
                  return (
                    <li key={u.name} className="border border-gray-800 rounded-lg p-2.5">
                      <div className="flex items-center gap-2 mb-2">
                        <span
                          className="w-3.5 h-3.5 rounded-full border border-gray-600 shrink-0"
                          style={u.hex ? { background: u.hex } : undefined}
                        />
                        <span className="text-sm text-gray-200">{u.name}</span>
                        {u.brand && <span className="text-xs text-gray-600">· {u.brand}</span>}
                      </div>

                      {decision && decision.type !== "skip" ? (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-emerald-400 flex items-center gap-1">
                            <CheckCircle size={12} />
                            {decision.type === "forced" ? "Added to shelf" : "Mapped"} →{" "}
                            {decision.paint.name} {decision.paint.code}
                          </span>
                          <button
                            onClick={() => setDecisions((d) => { const n = { ...d }; delete n[u.name]; return n; })}
                            className="text-gray-500 hover:text-gray-300"
                          >
                            Change
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <div className="flex-1">
                            <PaintPicker
                              value={null}
                              onChange={(p) => p && setDecisions((d) => ({ ...d, [u.name]: { type: "map", paint: p } }))}
                            />
                          </div>
                          <button
                            onClick={() => forceAdd(u)}
                            disabled={forcing === u.name}
                            title="Add this paint to your shelf"
                            className="flex items-center gap-1 text-xs px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 disabled:opacity-50 shrink-0"
                          >
                            {forcing === u.name ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                            Add
                          </button>
                          <button
                            onClick={() => setDecisions((d) => ({ ...d, [u.name]: { type: "skip" } }))}
                            title="Skip — drop this paint from the guide"
                            className={`flex items-center gap-1 text-xs px-2 py-1.5 rounded border shrink-0 ${
                              decision?.type === "skip"
                                ? "bg-rose-950/40 border-rose-800 text-rose-300"
                                : "bg-gray-800 hover:bg-gray-700 border-gray-700 text-gray-400"
                            }`}
                          >
                            <SkipForward size={12} />
                            Skip
                          </button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>

              {error && (
                <p role="alert" className="mb-3 text-sm text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded px-3 py-2">
                  {error}
                </p>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  onClick={() => { setPreview(null); setDecisions({}); setError(null); }}
                  className="text-sm bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 px-3 py-1.5 rounded"
                >
                  Back
                </button>
                <button
                  onClick={commitImport}
                  disabled={busy}
                  data-testid="commit-import"
                  className="flex items-center gap-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded disabled:opacity-50"
                >
                  {busy && <Loader2 size={13} className="animate-spin" />}
                  Import ({mappedCount} resolved)
                </button>
              </div>
            </div>
          )}

          {/* ── Result step ── */}
          {result && report && (
            <div data-testid="import-report">
              <div className="flex items-center gap-2 text-emerald-300 mb-3">
                <CheckCircle size={18} />
                <span className="text-sm font-medium">Imported “{result.guide.title}” as a draft.</span>
              </div>

              <ul className="text-sm text-gray-300 space-y-1 mb-3">
                <li>
                  <span className="text-emerald-400">{report.resolved_paints}</span> swatch paint(s) matched.
                </li>
                {report.unresolved_paints.length > 0 && (
                  <li>
                    <span className="text-rose-400">{report.unresolved_paints.length}</span> dropped — skipped or unresolved.
                  </li>
                )}
              </ul>

              {report.unresolved_paints.length > 0 && (
                <details className="mb-3" open data-testid="unresolved-paints">
                  <summary className="cursor-pointer text-xs uppercase tracking-wide text-rose-300">
                    Dropped swatches ({report.unresolved_paints.length})
                  </summary>
                  <ul className="mt-2 text-xs text-gray-400 space-y-1 max-h-40 overflow-y-auto">
                    {report.unresolved_paints.slice(0, 200).map((p, i) => (
                      <li key={i} className="flex items-center gap-1.5">
                        <FileText size={12} className="shrink-0 text-gray-600" />
                        <span className="text-gray-300">{p.name}</span>
                        {p.brand && <span className="text-gray-600">· {p.brand}</span>}
                        {p.step && <span className="text-gray-600">— {p.step}</span>}
                      </li>
                    ))}
                    {report.unresolved_paints.length > 200 && (
                      <li className="text-gray-600">…and {report.unresolved_paints.length - 200} more</li>
                    )}
                  </ul>
                </details>
              )}

              {report.unmapped_nodes.length > 0 && (
                <details className="mb-3" data-testid="unmapped-nodes">
                  <summary className="cursor-pointer text-xs uppercase tracking-wide text-amber-300">
                    Unmapped content ({report.unmapped_nodes.length})
                  </summary>
                  <ul className="mt-2 text-xs text-gray-500 font-mono space-y-0.5 max-h-40 overflow-y-auto">
                    {report.unmapped_nodes.slice(0, 200).map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                </details>
              )}

              {report.notes.length > 0 && (
                <ul className="mb-3 text-xs text-gray-500 list-disc list-inside space-y-0.5">
                  {report.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Link
                  to={`/painting/guides/${result.guide.id}`}
                  onClick={onImported}
                  className="text-sm bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded transition-colors"
                >
                  View draft
                </Link>
                <button
                  onClick={onImported}
                  className="text-sm bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 px-3 py-1.5 rounded transition-colors"
                >
                  Done
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

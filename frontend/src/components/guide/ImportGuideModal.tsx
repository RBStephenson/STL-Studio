import { useState } from "react";
import { Link } from "react-router-dom";
import { X, Upload, FileText, CheckCircle } from "lucide-react";
import { api, Guide, GuideImportReport } from "../../api/client";

/**
 * Import a legacy guide HTML file (#277).
 *
 * The backend lands the draft in one shot and returns an import report, so this
 * is upload → import → show report (+ a link to the new draft). Unresolved
 * swatch paints are dropped and listed; the user can fix them on the Paint Shelf
 * and re-import, or delete the draft from the reader if unhappy.
 */
export function slugFromFilename(name: string): string {
  return name
    .replace(/\.html?$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
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
      const res = await api.painting.guides.import_(html, slug);
      setResult(res);
    } catch (e) {
      const msg = (e as Error)?.message || "Import failed.";
      setError(
        msg.includes("409")
          ? "A guide with this slug already exists. Rename the file or delete the existing guide first."
          : msg,
      );
    } finally {
      setBusy(false);
    }
  };

  const report = result?.report;

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
          {!result && (
            <>
              <p className="text-sm text-gray-400 mb-4">
                Upload a guide HTML file. It lands as a <span className="text-amber-400">draft</span>{" "}
                for review — never auto-published. Swatch paints are matched against your Paint Shelf;
                any that don't match are dropped and listed below.
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
                  {busy ? "Importing…" : "Choose or drop an HTML file"}
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
                    <span className="text-rose-400">{report.unresolved_paints.length}</span> dropped — not on your Paint Shelf.
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

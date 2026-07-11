import { lazy, Suspense, useState, useMemo } from "react";
import { X, Copy, Check, Wrench, Download, Box } from "lucide-react";
import { STLFile, api } from "../api/client";
import HelpLink from "./HelpLink";

const STLViewer = lazy(() => import("./STLViewer"));

interface Props {
  modelName: string;
  files: STLFile[];
  onClose: () => void;
}

function cleanName(filename: string): string {
  return filename.replace(/\.(stl|3mf|obj)$/i, "").replace(/[_-]+/g, " ").trim();
}

// Word for a linked variant, chosen by keyword match against its name —
// mirrors the backend's link_sups keyword set (sup/supported/hollowed).
const _VARIANT_KEYWORD_RE = /\b(?:sup|supported|hollow|hollowed)\b/i;
const _HOLLOW_RE = /\bhollow(?:ed)?\b/i;

function variantWord(f: STLFile): "Hollowed" | "Supported" | "Other" {
  const text = `${f.part_name ?? ""} ${f.filename}`;
  if (_HOLLOW_RE.test(text)) return "Hollowed";
  if (_VARIANT_KEYWORD_RE.test(text)) return "Supported";
  return "Other";
}

function variantLabel(f: STLFile) {
  const word = variantWord(f);
  return word === "Other" ? "Linked version" : `${word} version`;
}

export default function KitBuilder({ modelName, files, onClose }: Props) {
  // Selection is a flat set of file ids — was one-per-part-type, which
  // forced a part and its own linked variants (base/Supported/Hollowed) to
  // fight over the same slot. Any file can be picked independently of any
  // other, in or out of a variant cluster.
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [copied, setCopied] = useState(false);
  const [downloading, setDownloading] = useState(false);
  // previewFile: locked by click; hoveredFile: overrides while hovering
  const [previewFile, setPreviewFile] = useState<STLFile | null>(null);
  const [hoveredFile, setHoveredFile] = useState<STLFile | null>(null);
  const displayedFile = hoveredFile ?? previewFile;

  // Group files by part_type; null → "Uncategorized"
  const groups = useMemo(() => {
    const map = new Map<string, STLFile[]>();
    for (const f of files) {
      const key = f.part_type ?? "__none__";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(f);
    }
    // Sort: categorized groups first (alphabetical), then Uncategorized
    const sorted = new Map<string, STLFile[]>();
    [...map.keys()]
      .filter((k) => k !== "__none__")
      .sort()
      .forEach((k) => sorted.set(k, map.get(k)!));
    if (map.has("__none__")) sorted.set("__none__", map.get("__none__")!);
    return sorted;
  }, [files]);

  // Linked variants (sup_of_id) grouped under their base file's id, so each
  // base renders as one extended box with a labeled row per variant instead
  // of every version showing as its own separate pill. A sup whose base
  // doesn't actually exist in this file list (data inconsistency) falls
  // back to rendering as its own standalone entry rather than silently
  // disappearing.
  const allFileIds = useMemo(() => new Set(files.map((f) => f.id)), [files]);
  const supsByBaseId = useMemo(() => {
    const map = new Map<number, STLFile[]>();
    for (const f of files) {
      if (f.sup_of_id != null && allFileIds.has(f.sup_of_id)) {
        if (!map.has(f.sup_of_id)) map.set(f.sup_of_id, []);
        map.get(f.sup_of_id)!.push(f);
      }
    }
    return map;
  }, [files, allFileIds]);
  const isOrphanedSup = (f: STLFile) => f.sup_of_id != null && !allFileIds.has(f.sup_of_id);

  const toggle = (file: STLFile) => {
    setPreviewFile(file);
    setSelection((prev) => {
      const next = new Set(prev);
      next.has(file.id) ? next.delete(file.id) : next.add(file.id);
      return next;
    });
  };

  const selectedFiles = useMemo(
    () => files.filter((f) => selection.has(f.id)),
    [selection, files]
  );

  const copyToClipboard = async () => {
    const text = selectedFiles.map((f) => f.filename).join("\n");
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadZip = async () => {
    if (!selectedFiles.length) return;
    setDownloading(true);
    try {
      const date = new Date().toISOString().slice(0, 10);
      await api.downloadZip(selectedFiles.map((f) => f.id), `${modelName} ${date}`);
    } finally {
      setDownloading(false);
    }
  };

  const categorizedCount = [...groups.keys()].filter((k) => k !== "__none__").length;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-panel-inset/95 backdrop-blur-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border-subtle shrink-0">
        <div className="flex items-center gap-2">
          <Wrench size={18} className="text-indigo-400" />
          <h2 className="text-lg font-semibold text-white">Kit Builder</h2>
          <HelpLink section="kit-builder" label="How the Kit Builder works" />
          <span className="text-text-secondary-alt text-sm">— {modelName}</span>
        </div>
        <button onClick={onClose} className="text-text-secondary-alt hover:text-white transition-colors">
          <X size={20} />
        </button>
      </div>

      {/* Body — left: scrollable part selector · right: sticky 3D viewer */}
      <div className="flex flex-1 overflow-hidden">

        {/* Part selector */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6 border-r border-border-subtle">
          {[...groups.entries()].map(([key, groupFiles]) => {
            const label = key === "__none__" ? "Uncategorized" : key.replace(/\b\w/g, (c) => c.toUpperCase());
            return (
              <div key={key}>
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-text-primary-alt2 uppercase tracking-wider">{label}</h3>
                  <span className="text-xs text-text-muted">{groupFiles.length} file{groupFiles.length !== 1 ? "s" : ""}</span>
                </div>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] items-start gap-2">
                  {/* Only primaries (not a sup, or an orphaned sup with no real
                      base) get their own entry — a normal sup renders nested
                      inside its base's box instead. */}
                  {groupFiles
                    .filter((f) => f.sup_of_id == null || isOrphanedSup(f))
                    .map((f) => {
                    const variants = supsByBaseId.get(f.id) ?? [];
                    const isBaseSelected = selection.has(f.id);
                    const isBaseHovered = hoveredFile?.id === f.id;
                    const isAnySelected = isBaseSelected || variants.some((v) => selection.has(v.id));

                    if (variants.length === 0) {
                      return (
                        <button
                          key={f.id}
                          onClick={() => toggle(f)}
                          onMouseEnter={() => setHoveredFile(f)}
                          onMouseLeave={() => setHoveredFile(null)}
                          title={f.filename}
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm transition-all ${
                            isBaseSelected
                              ? "bg-accent-end border-accent-start text-white"
                              : isBaseHovered
                              ? "bg-panel-secondary border-indigo-400/50 text-text-primary-alt"
                              : "bg-panel border-border text-text-secondary hover:border-border-divider hover:text-text-primary-alt"
                          }`}
                        >
                          <Check size={12} strokeWidth={3} className={`shrink-0 ${isBaseSelected ? "" : "opacity-0"}`} />
                          {cleanName(f.filename)}
                        </button>
                      );
                    }

                    // Has linked variants — one box, stacked vertically: the
                    // base is the top row (normal weight, matches a plain
                    // pill), each variant is a smaller indented row below it.
                    // Every row is independently toggleable, not exclusive.
                    return (
                      <div
                        key={f.id}
                        className={`flex flex-col rounded-lg border text-sm transition-all overflow-hidden ${
                          isAnySelected ? "border-accent-start" : "border-border"
                        }`}
                      >
                        <button
                          onClick={() => toggle(f)}
                          onMouseEnter={() => setHoveredFile(f)}
                          onMouseLeave={() => setHoveredFile(null)}
                          title={f.filename}
                          className={`flex items-center gap-1.5 px-3 py-1.5 text-left transition-all ${
                            isBaseSelected
                              ? "bg-accent-end text-white"
                              : isBaseHovered
                              ? "bg-panel-secondary text-text-primary-alt"
                              : "bg-panel text-text-secondary hover:text-text-primary-alt"
                          }`}
                        >
                          <Check size={12} strokeWidth={3} className={`shrink-0 ${isBaseSelected ? "" : "opacity-0"}`} />
                          {cleanName(f.filename)}
                        </button>
                        {variants.map((v) => {
                          const isVariantSelected = selection.has(v.id);
                          const isVariantHovered = hoveredFile?.id === v.id;
                          return (
                            <button
                              key={v.id}
                              onClick={() => toggle(v)}
                              onMouseEnter={() => setHoveredFile(v)}
                              onMouseLeave={() => setHoveredFile(null)}
                              title={`${variantLabel(v)} — ${v.filename}`}
                              className={`flex items-center gap-1 pl-5 pr-3 py-1 text-left text-xs border-t whitespace-nowrap transition-all ${
                                isVariantSelected
                                  ? "bg-accent-end border-accent-start/60 text-white"
                                  : isVariantHovered
                                  ? "bg-panel-secondary border-border-divider text-text-primary-alt"
                                  : "bg-panel border-border text-text-muted hover:text-text-primary-alt"
                              }`}
                            >
                              <span className="text-text-muted-alt shrink-0">↳</span>
                              <Check size={10} strokeWidth={3} className={`shrink-0 ${isVariantSelected ? "" : "opacity-0"}`} />
                              {variantWord(v)}
                            </button>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {files.length === 0 && (
            <p className="text-text-muted text-sm py-8 text-center">No STL files found for this model.</p>
          )}
        </div>

        {/* 3D preview — always visible, never scrolls */}
        <div className="w-[42%] flex flex-col shrink-0">
          {displayedFile ? (
            <Suspense fallback={
              <div className="flex-1 flex items-center justify-center text-text-secondary-alt text-sm">
                Loading viewer…
              </div>
            }>
              <STLViewer
                key={displayedFile.id}
                files={[displayedFile]}
                getUrl={api.stlUrl}
                hidePicker
              />
            </Suspense>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center gap-3 text-text-muted">
              <Box size={40} strokeWidth={1} />
              <p className="text-sm">Click a part to preview it here</p>
            </div>
          )}
        </div>
      </div>

      {/* Build summary — sticky footer */}
      <div className="shrink-0 border-t border-border-subtle bg-panel px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <p className="text-xs text-text-secondary-alt mb-1">
              {selectedFiles.length} selected
              {categorizedCount > 0 && ` · ${categorizedCount} part type${categorizedCount !== 1 ? "s" : ""}`}
            </p>
            {selectedFiles.length > 0 ? (
              <p className="text-sm text-text-primary-alt2 truncate">
                {selectedFiles.map((f) => f.filename).join(" · ")}
              </p>
            ) : (
              <p className="text-sm text-text-muted italic">
                Click parts above to build your selection
              </p>
            )}
          </div>
          <div className="flex gap-2 shrink-0">
            {selectedFiles.length > 0 && (
              <button
                onClick={() => setSelection(new Set())}
                className="px-3 py-1.5 rounded bg-panel-secondary border border-border text-sm text-text-secondary hover:text-white transition-colors"
              >
                Clear
              </button>
            )}
            <button
              onClick={copyToClipboard}
              disabled={selectedFiles.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-panel-secondary border border-border hover:border-border-divider disabled:opacity-40 disabled:cursor-not-allowed text-text-primary-alt2 text-sm transition-colors"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied ? "Copied!" : "Copy list"}
            </button>
            <button
              onClick={downloadZip}
              disabled={selectedFiles.length === 0 || downloading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-accent-end hover:bg-accent-start disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm transition-colors"
            >
              <Download size={14} />
              {downloading ? "Zipping…" : "Download zip"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

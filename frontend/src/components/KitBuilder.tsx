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

export default function KitBuilder({ modelName, files, onClose }: Props) {
  // selection: partType → fileId (one per group)
  const [selection, setSelection] = useState<Record<string, number>>({});
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

  const toggle = (partType: string, file: STLFile) => {
    setPreviewFile(file);
    setSelection((prev) =>
      prev[partType] === file.id
        ? Object.fromEntries(Object.entries(prev).filter(([k]) => k !== partType))
        : { ...prev, [partType]: file.id }
    );
  };

  const selectedFiles = useMemo(() => {
    const idSet = new Set(Object.values(selection));
    return files.filter((f) => idSet.has(f.id));
  }, [selection, files]);

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
    <div className="fixed inset-0 z-50 flex flex-col bg-gray-950/95 backdrop-blur-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-2">
          <Wrench size={18} className="text-indigo-400" />
          <h2 className="text-lg font-semibold text-white">Kit Builder</h2>
          <HelpLink section="kit-builder" label="How the Kit Builder works" />
          <span className="text-gray-500 text-sm">— {modelName}</span>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors">
          <X size={20} />
        </button>
      </div>

      {/* Body — left: scrollable part selector · right: sticky 3D viewer */}
      <div className="flex flex-1 overflow-hidden">

        {/* Part selector */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6 border-r border-gray-800">
          {[...groups.entries()].map(([key, groupFiles]) => {
            const label = key === "__none__" ? "Uncategorized" : key.replace(/\b\w/g, (c) => c.toUpperCase());
            return (
              <div key={key}>
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">{label}</h3>
                  <span className="text-xs text-gray-600">{groupFiles.length} file{groupFiles.length !== 1 ? "s" : ""}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {groupFiles.map((f) => {
                    const isSelected = selection[key] === f.id;
                    const isHovered = hoveredFile?.id === f.id;
                    return (
                      <button
                        key={f.id}
                        onClick={() => toggle(key, f)}
                        onMouseEnter={() => setHoveredFile(f)}
                        onMouseLeave={() => setHoveredFile(null)}
                        title={f.filename}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm transition-all ${
                          isSelected
                            ? "bg-indigo-600 border-indigo-500 text-white"
                            : isHovered
                            ? "bg-gray-800 border-indigo-400/50 text-gray-200"
                            : "bg-gray-900 border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200"
                        }`}
                      >
                        {isSelected && <Check size={12} strokeWidth={3} />}
                        {cleanName(f.filename)}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {files.length === 0 && (
            <p className="text-gray-600 text-sm py-8 text-center">No STL files found for this model.</p>
          )}
        </div>

        {/* 3D preview — always visible, never scrolls */}
        <div className="w-[42%] flex flex-col shrink-0">
          {displayedFile ? (
            <Suspense fallback={
              <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
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
            <div className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-600">
              <Box size={40} strokeWidth={1} />
              <p className="text-sm">Click a part to preview it here</p>
            </div>
          )}
        </div>
      </div>

      {/* Build summary — sticky footer */}
      <div className="shrink-0 border-t border-gray-800 bg-gray-900 px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <p className="text-xs text-gray-500 mb-1">
              {selectedFiles.length} selected
              {categorizedCount > 0 && ` · ${categorizedCount} part type${categorizedCount !== 1 ? "s" : ""}`}
            </p>
            {selectedFiles.length > 0 ? (
              <p className="text-sm text-gray-300 truncate">
                {selectedFiles.map((f) => f.filename).join(" · ")}
              </p>
            ) : (
              <p className="text-sm text-gray-600 italic">
                Click parts above to build your selection
              </p>
            )}
          </div>
          <div className="flex gap-2 shrink-0">
            {selectedFiles.length > 0 && (
              <button
                onClick={() => setSelection({})}
                className="px-3 py-1.5 rounded bg-gray-800 border border-gray-700 text-sm text-gray-400 hover:text-white transition-colors"
              >
                Clear
              </button>
            )}
            <button
              onClick={copyToClipboard}
              disabled={selectedFiles.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-800 border border-gray-700 hover:border-gray-500 disabled:opacity-40 disabled:cursor-not-allowed text-gray-300 text-sm transition-colors"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied ? "Copied!" : "Copy list"}
            </button>
            <button
              onClick={downloadZip}
              disabled={selectedFiles.length === 0 || downloading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm transition-colors"
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

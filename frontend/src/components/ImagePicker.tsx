import { useState, useEffect } from "react";
import { X, Check, ImageOff, Loader2, Link2, Trash2 } from "lucide-react";

interface ImageEntry {
  path: string;
  filename: string;
  url: string;
}

interface Props {
  modelId: number;
  currentPath: string | null;
  currentUrl: string | null;
  onApplied: () => void;
  onClose: () => void;
}

export default function ImagePicker({ modelId, currentPath, currentUrl, onApplied, onClose }: Props) {
  const [images, setImages] = useState<ImageEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(currentPath);
  const [urlInput, setUrlInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<"local" | "url">("local");

  useEffect(() => {
    fetch(`/api/files/model-images/${modelId}`)
      .then((r) => r.json())
      .then((data) => { setImages(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [modelId]);

  const apply = async (clear = false) => {
    setSaving(true);
    try {
      const body = clear
        ? { thumbnail_path: null, thumbnail_url: null }
        : tab === "url"
          ? { thumbnail_url: urlInput.trim(), thumbnail_path: null }
          : { thumbnail_path: selected, thumbnail_url: null };

      await fetch(`/api/models/${modelId}/thumbnail`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      onApplied();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h2 className="font-semibold text-gray-100">Set Thumbnail</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-800">
          {(["local", "url"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-5 py-2.5 text-sm transition-colors border-b-2 -mb-px ${
                tab === t
                  ? "border-indigo-500 text-indigo-400"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}
            >
              {t === "local" ? "From Folder" : "From URL"}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {tab === "url" ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-gray-500">Paste an image URL to use as the thumbnail.</p>
              <div className="flex gap-2">
                <Link2 size={16} className="text-gray-500 shrink-0 mt-2.5" />
                <input
                  type="url"
                  placeholder="https://…"
                  value={urlInput}
                  onChange={(e) => setUrlInput(e.target.value)}
                  className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
                />
              </div>
              {urlInput && (
                <img
                  src={urlInput}
                  alt="preview"
                  className="w-48 h-48 object-cover rounded-lg border border-gray-700"
                  onError={(e) => (e.currentTarget.style.display = "none")}
                />
              )}
            </div>
          ) : loading ? (
            <div className="flex items-center justify-center h-40 text-gray-600 gap-2">
              <Loader2 size={16} className="animate-spin" />
              <span className="text-sm">Loading images…</span>
            </div>
          ) : images.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-gray-600 gap-2">
              <ImageOff size={32} />
              <p className="text-sm">No images found in this model's folder</p>
            </div>
          ) : (
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
              {images.map((img) => (
                <button
                  key={img.path}
                  onClick={() => setSelected(img.path)}
                  className={`relative aspect-square rounded-lg overflow-hidden border-2 transition-colors ${
                    selected === img.path
                      ? "border-indigo-500 ring-2 ring-indigo-500/30"
                      : "border-gray-700 hover:border-gray-500"
                  }`}
                  title={img.filename}
                >
                  <img
                    src={`/api/files/image?path=${encodeURIComponent(img.path)}`}
                    alt={img.filename}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                  {selected === img.path && (
                    <div className="absolute inset-0 bg-indigo-600/20 flex items-center justify-center">
                      <Check size={20} className="text-white drop-shadow" />
                    </div>
                  )}
                  <p className="absolute bottom-0 inset-x-0 bg-black/60 text-xs text-gray-300 px-1 py-0.5 truncate">
                    {img.filename}
                  </p>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-4 border-t border-gray-800">
          <button
            onClick={() => apply(true)}
            disabled={saving || (!currentPath && !currentUrl)}
            title="Remove the current thumbnail"
            className="flex items-center gap-1.5 px-3 py-2 rounded bg-gray-800 hover:bg-red-900/50 hover:text-red-400 disabled:opacity-30 text-sm text-gray-500 transition-colors"
          >
            <Trash2 size={13} />
            Clear
          </button>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded bg-gray-800 hover:bg-gray-700 text-sm text-gray-300">
              Cancel
            </button>
            <button
              onClick={() => apply(false)}
              disabled={saving || (tab === "local" ? !selected : !urlInput.trim())}
              className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm flex items-center gap-1.5 transition-colors"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              Set as Thumbnail
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

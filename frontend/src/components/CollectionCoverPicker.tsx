import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { X, Link as LinkIcon, Upload, Images, Loader2, Trash2 } from "lucide-react";
import { api, Collection, Model } from "../api/client";

type Tab = "url" | "upload" | "model";

interface Props {
  collection: Collection;
  onClose: () => void;
  onUpdate: (updated: Collection) => void;
}

export default function CollectionCoverPicker({ collection, onClose, onUpdate }: Props) {
  const [tab, setTab] = useState<Tab>("url");
  const [urlInput, setUrlInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<Model[] | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Load collection models when "Pick from model" tab is opened.
  useEffect(() => {
    if (tab !== "model" || models !== null) return;
    api.collections.getModels(collection.id)
      .then(setModels)
      .catch(() => setModels([]));
  }, [tab, collection.id, models]);

  const setErr = (msg: string) => setError(msg);
  const go = async (fn: () => Promise<Collection>) => {
    setError(null);
    setBusy(true);
    try {
      const updated = await fn();
      onUpdate(updated);
      onClose();
    } catch (e: any) {
      setErr(e?.message ?? "Something went wrong — try again.");
    } finally {
      setBusy(false);
    }
  };

  const submitUrl = () => {
    if (!urlInput.trim()) return;
    go(() => api.collections.setCoverFromUrl(collection.id, urlInput.trim()));
  };

  const submitFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    go(() => api.collections.uploadCover(collection.id, file));
  };

  const submitModel = (modelId: number) => {
    go(() => api.collections.setCoverFromModel(collection.id, modelId));
  };

  const clearCover = () => {
    go(() => api.collections.clearCover(collection.id));
  };

  const modal = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg shadow-2xl flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 shrink-0">
          <h2 className="text-base font-semibold text-gray-100">Set cover image</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-gray-800 text-gray-500 hover:text-gray-300"
          >
            <X size={16} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-800 shrink-0">
          {([ ["url", LinkIcon, "URL"], ["upload", Upload, "Upload"], ["model", Images, "From model"] ] as const).map(
            ([key, Icon, label]) => (
              <button
                key={key}
                onClick={() => { setTab(key); setError(null); }}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-sm border-b-2 transition-colors ${
                  tab === key
                    ? "border-indigo-500 text-indigo-400"
                    : "border-transparent text-gray-500 hover:text-gray-300"
                }`}
              >
                <Icon size={14} />
                {label}
              </button>
            )
          )}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {tab === "url" && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-gray-500">
                Paste a direct image URL. The image is downloaded server-side, so URLs that block hot-linking still work.
              </p>
              <input
                autoFocus
                type="url"
                placeholder="https://example.com/image.jpg"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitUrl()}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-indigo-500"
              />
              <button
                onClick={submitUrl}
                disabled={busy || !urlInput.trim()}
                className="flex items-center justify-center gap-2 px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm transition-colors"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <LinkIcon size={14} />}
                Set cover
              </button>
            </div>
          )}

          {tab === "upload" && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-gray-500">
                Upload a PNG, JPEG, WebP, or GIF from your computer (max 15 MB).
              </p>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                className="hidden"
                onChange={submitFile}
              />
              <button
                onClick={() => fileRef.current?.click()}
                disabled={busy}
                className="flex items-center justify-center gap-2 px-4 py-8 rounded border-2 border-dashed border-gray-700 hover:border-indigo-500 text-gray-400 hover:text-gray-200 disabled:opacity-50 transition-colors"
              >
                {busy ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                <span className="text-sm">{busy ? "Uploading…" : "Click to choose a file"}</span>
              </button>
            </div>
          )}

          {tab === "model" && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-gray-500">
                Click a model's thumbnail to use it as the collection cover.
              </p>
              {models === null ? (
                <div className="flex justify-center py-8 text-gray-600">
                  <Loader2 size={20} className="animate-spin" />
                </div>
              ) : models.length === 0 ? (
                <p className="text-center py-8 text-xs text-gray-600">No models in this collection yet.</p>
              ) : (
                <div className="grid grid-cols-3 gap-2">
                  {models.map((m) => {
                    const gallery = m.image_paths ?? [];
                    const resolve = (p: string) => (/^https?:\/\//i.test(p) ? p : api.fileUrl(p));
                    const src = m.thumbnail_path
                      ? api.fileUrl(m.thumbnail_path, m.updated_at)
                      : m.thumbnail_url
                      ? m.thumbnail_url
                      : m.primary_image_path
                      ? resolve(m.primary_image_path)
                      : gallery.length > 0
                      ? resolve(gallery[0])
                      : null;
                    const hasLocalImage = !!(m.thumbnail_path || m.primary_image_path || gallery.length > 0);
                    return (
                      <button
                        key={m.id}
                        onClick={() => !busy && submitModel(m.id)}
                        disabled={busy || !hasLocalImage}
                        title={hasLocalImage ? m.name : "No local image available"}
                        className="relative aspect-square rounded overflow-hidden border border-gray-800 hover:border-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors group"
                      >
                        {src ? (
                          <img
                            src={src}
                            alt={m.name}
                            className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                          />
                        ) : (
                          <div className="w-full h-full bg-gray-800 flex items-center justify-center text-gray-600 text-xs">
                            No image
                          </div>
                        )}
                        <div className="absolute inset-x-0 bottom-0 bg-black/60 px-1.5 py-1 text-[10px] text-gray-300 truncate opacity-0 group-hover:opacity-100 transition-opacity">
                          {m.name}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {error && (
            <p className="mt-3 text-xs text-red-400">{error}</p>
          )}
        </div>

        {/* Footer — clear button if cover is set */}
        {collection.cover_image_path && (
          <div className="px-5 py-3 border-t border-gray-800 shrink-0 flex justify-end">
            <button
              onClick={clearCover}
              disabled={busy}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs text-red-400 hover:text-red-300 hover:bg-red-950/40 disabled:opacity-50 transition-colors"
            >
              <Trash2 size={12} />
              Remove cover
            </button>
          </div>
        )}
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}

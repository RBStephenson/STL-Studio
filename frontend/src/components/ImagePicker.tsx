import { useState, useEffect, useCallback, useRef } from "react";
import { X, Check, ImageOff, Loader2, Link2, Upload, Trash2, FolderOpen, ArrowUp, Folder, HardDrive, Image, RefreshCw } from "lucide-react";
import { errMsg } from "../utils/err";

interface ImageEntry {
  path: string;
  filename: string;
  url: string;
}

interface BrowseEntry {
  name: string;
  path: string;
  is_dir: boolean;
  url: string | null;
}

interface BrowseListing {
  path: string;
  parent: string | null;
  is_drive_list: boolean;
  entries: BrowseEntry[];
}

interface Props {
  modelId: number;
  currentPath: string | null;
  currentUrl: string | null;
  onApplied: () => void;
  onClose: () => void;
  // Stable across variants of one group (e.g. `${creatorId}:${character}`).
  // Variants share the character folder, so the image list is identical — caching
  // by this key lets reopening the modal on a sibling reuse the list instantly
  // instead of re-walking the folder (#303). Omit to always fetch fresh.
  cacheKey?: string;
}

// Module-scope so it survives the modal unmount/remount that happens every time
// the picker closes and reopens (state in the component itself would be lost).
// Lives for the SPA session; the Refresh button is the escape hatch when images
// are added on disk.
const imageListCache = new Map<string, ImageEntry[]>();

function clearCachedImageList(cacheKey?: string) {
  if (cacheKey) imageListCache.delete(cacheKey);
}

export default function ImagePicker({ modelId, currentPath, currentUrl, onApplied, onClose, cacheKey }: Props) {
  const [images, setImages] = useState<ImageEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(currentPath);
  const [urlInput, setUrlInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<"local" | "url" | "upload">("local");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [browsing, setBrowsing] = useState(false);
  const [browseListing, setBrowseListing] = useState<BrowseListing | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  // Set when the server couldn't download the image and fell back to storing the
  // bare URL (#285) — the thumbnail IS saved, but may not render if the host
  // blocks embedding. We keep the modal open to tell the user rather than
  // silently close.
  const [savedAsLink, setSavedAsLink] = useState<string | null>(null);

  const browseDir = useCallback((path?: string) => {
    setBrowseLoading(true);
    setBrowseError(null);
    const url = `/api/files/browse-images${path ? `?path=${encodeURIComponent(path)}` : ""}`;
    fetch(url)
      .then((r) => { if (!r.ok) throw new Error("Cannot open folder"); return r.json(); })
      .then(setBrowseListing)
      .catch((e) => setBrowseError(errMsg(e) ?? null))
      .finally(() => setBrowseLoading(false));
  }, []);

  const [refreshing, setRefreshing] = useState(false);

  // `refresh` forces the server to re-walk the folder, bypassing its cached
  // manifest — used when a newly-added image hasn't shown up yet.
  const loadImages = useCallback((refresh = false) => {
    // Cache hit: reuse the sibling-shared list immediately, no fetch. Refresh
    // always bypasses to re-walk the folder (and refreshes the cached entry).
    if (!refresh && cacheKey && imageListCache.has(cacheKey)) {
      setImages(imageListCache.get(cacheKey)!);
      setLoading(false);
      return;
    }
    if (refresh) setRefreshing(true);
    else setLoading(true);
    fetch(`/api/files/model-images/${modelId}${refresh ? "?refresh=true" : ""}`)
      .then((r) => r.json())
      .then((data) => {
        setImages(data);
        if (cacheKey) imageListCache.set(cacheKey, data);
      })
      .catch(() => { /* leave the existing list in place on failure */ })
      .finally(() => { setLoading(false); setRefreshing(false); });
  }, [modelId, cacheKey]);

  useEffect(() => { loadImages(); }, [loadImages]);

  const apply = async (clear = false) => {
    setSaving(true);
    setApplyError(null);
    setSavedAsLink(null);
    try {
      if (!clear && tab === "url") {
        // The server downloads the image and stores it locally — remote CDNs
        // block hot-linking, so a successful download is the reliable path.
        const r = await fetch(`/api/models/${modelId}/thumbnail/from-url`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: urlInput.trim() }),
        });
        const data = await r.json().catch(() => null);
        if (!r.ok) {
          throw new Error(data?.detail ?? "Could not fetch that image");
        }
        if (data?.downloaded === false) {
          // Saved, but the server couldn't download it — keep the modal open and
          // tell the user it may not render. The thumbnail (the bare URL) is set.
          setSavedAsLink(
            data.detail
              ? `Saved as a direct link — the server couldn't download it (${data.detail}). It may not display if the site blocks embedding.`
              : "Saved as a direct link — it may not display if the site blocks embedding.",
          );
          clearCachedImageList(cacheKey);
          return;
        }
      } else {
        const body = clear
          ? { thumbnail_path: null, thumbnail_url: null }
          : { thumbnail_path: selected, thumbnail_url: null };
        const r = await fetch(`/api/models/${modelId}/thumbnail`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error("Could not update the thumbnail");
      }
      clearCachedImageList(cacheKey);
      onApplied();
    } catch (e) {
      setApplyError(errMsg(e) ?? null);
    } finally {
      setSaving(false);
    }
  };

  // Uploads immediately on file selection — same one-step pattern as
  // CollectionCoverPicker's Upload tab, and the same endpoint the 3D viewer's
  // "capture" button posts to (store_thumbnail, the same path-confinement
  // helper store_collection_cover uses).
  const submitUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await fetch(`/api/models/${modelId}/thumbnail/upload`, { method: "POST", body: form });
      if (!r.ok) {
        const data = await r.json().catch(() => null);
        throw new Error(data?.detail ?? "Could not upload image");
      }
      clearCachedImageList(cacheKey);
      onApplied();
    } catch (err) {
      setUploadError(errMsg(err) ?? "Could not upload image");
    } finally {
      setUploading(false);
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
          {(["local", "url", "upload"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-5 py-2.5 text-sm transition-colors border-b-2 -mb-px ${
                tab === t
                  ? "border-indigo-500 text-indigo-400"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}
            >
              {t === "local" ? "From Folder" : t === "url" ? "From URL" : "Upload"}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {tab === "upload" ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-gray-500">
                Upload a PNG, JPEG, WebP, or GIF from your computer (max 15 MB). It's set as the
                thumbnail immediately.
              </p>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                className="hidden"
                onChange={submitUpload}
              />
              <button
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                className="flex items-center justify-center gap-2 px-4 py-8 rounded border-2 border-dashed border-gray-700 hover:border-indigo-500 text-gray-400 hover:text-gray-200 disabled:opacity-50 transition-colors"
              >
                {uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                <span className="text-sm">{uploading ? "Uploading…" : "Click to choose a file"}</span>
              </button>
              {uploadError && (
                <p className="text-sm text-red-400 bg-red-950/40 border border-red-800 rounded px-3 py-2">
                  {uploadError}
                </p>
              )}
            </div>
          ) : tab === "url" ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-gray-500">
                Paste an image URL to use as the thumbnail. The image is downloaded
                and saved when you click Set as Thumbnail — it's fine if the preview
                below doesn't load (many sites block previews).
              </p>
              <div className="flex gap-2">
                <Link2 size={16} className="text-gray-500 shrink-0 mt-2.5" />
                <input
                  type="url"
                  placeholder="https://…"
                  value={urlInput}
                  onChange={(e) => { setUrlInput(e.target.value); setSavedAsLink(null); }}
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
              {savedAsLink && (
                <p role="status" className="text-sm text-amber-300 bg-amber-950/40 border border-amber-800 rounded px-3 py-2">
                  {savedAsLink}
                </p>
              )}
            </div>
          ) : browsing ? (
            /* ── File browser ── */
            <div className="flex flex-col gap-2">
              {/* Toolbar */}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => browseDir(browseListing?.parent ?? undefined)}
                  disabled={browseLoading || browseListing?.parent == null}
                  title="Up one level"
                  className="p-1.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-400 disabled:opacity-30"
                >
                  <ArrowUp size={14} />
                </button>
                <span className="text-xs text-gray-400 font-mono truncate flex-1">
                  {browseListing?.is_drive_list ? "This PC" : browseListing?.path ?? "…"}
                </span>
                <button
                  onClick={() => setBrowsing(false)}
                  className="text-xs text-gray-500 hover:text-gray-300 px-2 py-1 rounded bg-gray-800 hover:bg-gray-700"
                >
                  ← Scan results
                </button>
              </div>

              {/* Listing */}
              {browseLoading ? (
                <div className="flex items-center justify-center h-40 text-gray-600 gap-2">
                  <Loader2 size={16} className="animate-spin" />
                  <span className="text-sm">Loading…</span>
                </div>
              ) : browseError ? (
                <div className="flex flex-col items-center justify-center h-40 text-gray-500 gap-2 text-center px-4">
                  <ImageOff size={24} />
                  <p className="text-sm">{browseError}</p>
                </div>
              ) : browseListing?.entries.length === 0 ? (
                <div className="flex items-center justify-center h-40 text-gray-600 text-sm">
                  Nothing here
                </div>
              ) : (
                <div className="flex flex-col gap-0.5">
                  {browseListing?.entries.map((entry) => (
                    entry.is_dir ? (
                      <button
                        key={entry.path}
                        onClick={() => browseDir(entry.path)}
                        className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-gray-800 text-left text-sm text-gray-200 transition-colors"
                      >
                        {browseListing.is_drive_list
                          ? <HardDrive size={14} className="text-indigo-400 shrink-0" />
                          : <Folder size={14} className="text-indigo-400 shrink-0" />
                        }
                        <span className="truncate font-mono">{entry.name}</span>
                      </button>
                    ) : (
                      <button
                        key={entry.path}
                        onClick={() => { setSelected(entry.path); setBrowsing(false); }}
                        className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-left text-sm transition-colors ${
                          selected === entry.path
                            ? "bg-indigo-950/50 border border-indigo-500/50 text-indigo-300"
                            : "hover:bg-gray-800 text-gray-200"
                        }`}
                      >
                        <Image size={14} className="text-gray-500 shrink-0" />
                        <span className="truncate font-mono">{entry.name}</span>
                        {selected === entry.path && <Check size={13} className="text-indigo-400 ml-auto shrink-0" />}
                      </button>
                    )
                  ))}
                </div>
              )}
            </div>
          ) : loading ? (
            <div className="flex items-center justify-center h-40 text-gray-600 gap-2">
              <Loader2 size={16} className="animate-spin" />
              <span className="text-sm">Loading images…</span>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {images.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-32 text-gray-600 gap-2">
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
              <div className="flex items-center gap-2">
                <button
                  onClick={() => { setBrowsing(true); browseDir(); }}
                  className="flex items-center gap-2 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 transition-colors"
                >
                  <FolderOpen size={13} />
                  Browse for image…
                </button>
                <button
                  onClick={() => loadImages(true)}
                  disabled={refreshing}
                  title="Re-scan this model's folder for images"
                  className="flex items-center gap-2 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 disabled:opacity-50 transition-colors"
                >
                  <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
                  Refresh
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        {applyError && (
          <p className="mx-5 mb-0 mt-3 text-sm text-red-400 bg-red-950/40 border border-red-800 rounded px-3 py-2">
            {applyError}
          </p>
        )}
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
            {tab === "upload" ? null : savedAsLink ? (
              <button
                onClick={onApplied}
                className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-sm flex items-center gap-1.5 transition-colors"
              >
                <Check size={14} />
                Done
              </button>
            ) : (
              <button
                onClick={() => apply(false)}
                disabled={saving || (tab === "local" ? !selected : !urlInput.trim())}
                className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm flex items-center gap-1.5 transition-colors"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                Set as Thumbnail
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

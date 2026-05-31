import { useState, useEffect, useCallback } from "react";
import { useParams, Link, useLocation } from "react-router-dom";
import { ArrowLeft, ExternalLink, Package, Star, Download, Tag, FileBox, Globe, Images, Box, ImagePlus, Pencil, Plus, Wrench, FolderDown, Folder, Copy, Check, Printer } from "lucide-react";
import { api, ModelDetail as ModelDetailType } from "../api/client";
import FindOnWeb from "../components/FindOnWeb";
import STLViewer from "../components/STLViewer";
import ImagePicker from "../components/ImagePicker";
import MetadataEditor from "../components/MetadataEditor";
import KitBuilder from "../components/KitBuilder";
import { useNSFW } from "../context/NSFWContext";

const PART_TYPE_SUGGESTIONS = [
  "head", "torso", "body",
  "right arm", "left arm", "arms",
  "right leg", "left leg", "legs",
  "hands", "feet", "base",
  "weapon", "shield", "cloak", "cape",
  "hair", "wings", "tail", "accessories",
];

type ViewMode = "images" | "3d";

export default function ModelDetail() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const backTo = (location.state as any)?.from ?? "/";
  const { showNSFW } = useNSFW();
  const [model, setModel] = useState<ModelDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeImage, setActiveImage] = useState<string | null>(null);
  const [showFindOnWeb, setShowFindOnWeb] = useState(false);
  const [showImagePicker, setShowImagePicker] = useState(false);
  const [editing, setEditing] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("images");
  const [nsfw, setNsfw] = useState(false);
  const [favorite, setFavorite] = useState(false);
  const [queued, setQueued] = useState(false);
  const [printedAt, setPrintedAt] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [partTypes, setPartTypes] = useState<Record<number, string>>({});
  const [showKitBuilder, setShowKitBuilder] = useState(false);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [copiedPath, setCopiedPath] = useState(false);
  const [openFolderError, setOpenFolderError] = useState<string | null>(null);

  // sync local state from loaded model
  useEffect(() => {
    if (model) {
      setNsfw(model.nsfw);
      setFavorite(model.is_favorite);
      setQueued(model.in_queue);
      setPrintedAt(model.printed_at);
      setTags(model.tags ?? []);
      const pts: Record<number, string> = {};
      model.stl_files.forEach((f) => { if (f.part_type) pts[f.id] = f.part_type; });
      setPartTypes(pts);
    }
  }, [model]);

  const downloadAllFiles = async () => {
    if (!model || downloadingAll) return;
    setDownloadingAll(true);
    try {
      const date = new Date().toISOString().slice(0, 10);
      const name = model.title || model.name;
      await api.downloadZip(model.stl_files.map((f) => f.id), `${name} ${date}`);
    } finally {
      setDownloadingAll(false);
    }
  };

  const copyPath = () => {
    const path = model?.native_folder_path || model?.folder_path || "";
    navigator.clipboard.writeText(path).then(() => {
      setCopiedPath(true);
      setTimeout(() => setCopiedPath(false), 2000);
    });
  };

  const openFolder = async () => {
    if (!model) return;
    setOpenFolderError(null);
    try {
      await api.files.openFolder(model.folder_path);
    } catch {
      setOpenFolderError("Cannot open folder — only available in standalone mode.");
      setTimeout(() => setOpenFolderError(null), 4000);
    }
  };

  const savePartType = async (fileId: number, value: string) => {
    const pt = value.trim().toLowerCase() || "";
    setPartTypes((prev) => ({ ...prev, [fileId]: pt }));
    await api.models.updateSTLFile(fileId, { part_type: pt || null });
  };

  const addTag = async (tag: string) => {
    if (tags.includes(tag)) return;
    const next = [...tags, tag];
    setTags(next);
    await api.models.update(Number(id), { tags: next });
  };

  const toggleNSFW = async () => {
    const next = !nsfw;
    setNsfw(next);
    await api.models.setNSFW(Number(id), next);
  };

  const toggleFavorite = async () => {
    const next = !favorite;
    setFavorite(next);
    await api.models.setFavorite(Number(id), next);
  };

  const toggleQueue = async () => {
    const next = !queued;
    setQueued(next);
    await api.models.setQueue(Number(id), next);
  };

  const togglePrinted = async () => {
    const next = !printedAt;
    setPrintedAt(next ? new Date().toISOString() : null);
    if (next) setQueued(false);  // marking printed clears the queue
    await api.models.setPrinted(Number(id), next);
  };

  const load = useCallback(() => {
    if (!id) return;
    api.models.get(Number(id)).then((m) => {
      setModel(m);
      const thumb = m.thumbnail_path
        ? api.fileUrl(m.thumbnail_path)
        : m.thumbnail_url ?? null;
      setActiveImage(thumb);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="p-8 text-gray-500 animate-pulse">Loading…</div>;
  if (!model) return <div className="p-8 text-gray-500">Model not found.</div>;

  const allImages = [
    model.thumbnail_path ? api.fileUrl(model.thumbnail_path) : model.thumbnail_url,
    ...model.image_paths.map(api.fileUrl),
  ].filter(Boolean) as string[];

  const hasSTLs = model.stl_files.some((f) =>
    f.filename.toLowerCase().endsWith(".stl")
  );

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <Link to={backTo} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300 mb-6 w-fit">
        <ArrowLeft size={14} /> Back to Library
      </Link>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

        {/* Left column — Images / 3D viewer */}
        <div className="flex flex-col gap-3">

          {/* View mode toggle */}
          {hasSTLs && (
            <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-lg p-1 self-start">
              <button
                onClick={() => setViewMode("images")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === "images"
                    ? "bg-gray-700 text-gray-100"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                <Images size={14} /> Images
              </button>
              <button
                onClick={() => setViewMode("3d")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
                  viewMode === "3d"
                    ? "bg-indigo-600 text-white"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                <Box size={14} /> 3D View
              </button>
            </div>
          )}

          {/* Image view */}
          {viewMode === "images" && (
            <>
              <div className="aspect-square bg-gray-900 rounded-xl overflow-hidden border border-gray-800 relative group">
                {activeImage ? (
                  <img
                    src={activeImage}
                    alt={model.title ?? model.name}
                    className={`w-full h-full object-contain transition-all ${
                      nsfw && !showNSFW ? "blur-2xl" : ""
                    }`}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-gray-700">
                    <Package size={64} />
                  </div>
                )}

                {/* NSFW detail overlay */}
                {nsfw && !showNSFW && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                    <span className="bg-black/70 text-red-400 text-sm font-bold px-3 py-1.5 rounded border border-red-800 tracking-widest">
                      NSFW
                    </span>
                    <p className="text-xs text-gray-500">Enable NSFW in the navbar to view</p>
                  </div>
                )}

                <button
                  onClick={() => setShowImagePicker(true)}
                  className="absolute bottom-3 right-3 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-black/60 hover:bg-black/80 text-gray-300 hover:text-white text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <ImagePlus size={13} /> Change image
                </button>
              </div>
              {allImages.length > 1 && (
                <div className="flex gap-2 flex-wrap">
                  {allImages.map((img, i) => (
                    <button
                      key={i}
                      onClick={() => setActiveImage(img)}
                      className={`w-16 h-16 rounded-lg overflow-hidden border-2 transition-colors ${
                        activeImage === img
                          ? "border-indigo-500"
                          : "border-gray-800 hover:border-gray-600"
                      }`}
                    >
                      <img src={img} alt="" className="w-full h-full object-cover" />
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {/* 3D view */}
          {viewMode === "3d" && (
            <STLViewer
              files={model.stl_files}
              getUrl={api.stlUrl}
            />
          )}
        </div>

        {/* Right column — Info */}
        <div className="flex flex-col gap-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              {model.character && (
                <p className="text-sm text-indigo-400 mb-1">{model.character}</p>
              )}
              <h1 className="text-2xl font-bold text-gray-100">{model.title || model.name}</h1>
              {model.creator && (
                <p className="text-gray-400 mt-1">by {model.creator.name}</p>
              )}
            </div>
            <div className="flex gap-2 shrink-0">
              <button
                onClick={toggleFavorite}
                title={favorite ? "Remove from favorites" : "Add to favorites"}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded border text-sm transition-colors ${
                  favorite
                    ? "bg-yellow-950/60 border-yellow-800 text-yellow-400 hover:bg-yellow-900/60"
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200"
                }`}
              >
                <Star size={14} fill={favorite ? "currentColor" : "none"} />
                Favorite
              </button>
              <button
                onClick={toggleQueue}
                title={queued ? "Remove from print queue" : "Add to print queue"}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded border text-sm transition-colors ${
                  queued
                    ? "bg-sky-950/60 border-sky-800 text-sky-400 hover:bg-sky-900/60"
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200"
                }`}
              >
                <Printer size={14} />
                {queued ? "Queued" : "Queue"}
              </button>
              <button
                onClick={togglePrinted}
                title={printedAt ? "Un-mark as printed" : "Mark as printed"}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded border text-sm transition-colors ${
                  printedAt
                    ? "bg-emerald-950/60 border-emerald-800 text-emerald-400 hover:bg-emerald-900/60"
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200"
                }`}
              >
                <Check size={14} />
                {printedAt ? "Printed" : "Mark printed"}
              </button>
              <button
                onClick={toggleNSFW}
                title={nsfw ? "Mark as SFW" : "Mark as NSFW"}
                className={`px-3 py-1.5 rounded border text-sm transition-colors ${
                  nsfw
                    ? "bg-red-950/60 border-red-800 text-red-400 hover:bg-red-900/60"
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200"
                }`}
              >
                {nsfw ? "NSFW ✓" : "NSFW"}
              </button>
              <button
                onClick={() => setEditing(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-indigo-500 text-sm text-gray-300 transition-colors"
              >
                <Pencil size={14} />
                Edit
              </button>
              <button
                onClick={() => setShowFindOnWeb(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-indigo-500 text-sm text-gray-300 transition-colors"
              >
                <Globe size={14} />
                Find on Web
              </button>
            </div>
          </div>

          {/* ---- Edit mode ---- */}
          {editing && (
            <MetadataEditor
              model={model}
              onSaved={() => { setEditing(false); load(); }}
              onCancel={() => setEditing(false)}
            />
          )}

          {/* ---- Display mode ---- */}
          {!editing && (<>

          {/* Stats row */}
          <div className="flex items-center gap-4 text-sm text-gray-400">
            {model.rating != null && (
              <span className="flex items-center gap-1 text-yellow-400">
                <Star size={14} fill="currentColor" />
                {model.rating.toLocaleString()}
              </span>
            )}
            {model.download_count != null && (
              <span className="flex items-center gap-1">
                <Download size={14} />
                {model.download_count.toLocaleString()}
              </span>
            )}
            {model.source_site && (
              <span className="capitalize bg-gray-800 px-2 py-0.5 rounded text-xs">
                {model.source_site}
              </span>
            )}
            {model.license && (
              <span className="bg-gray-800 px-2 py-0.5 rounded text-xs">{model.license}</span>
            )}
          </div>

          {model.source_url && (
            <a
              href={model.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-sm text-indigo-400 hover:text-indigo-300 w-fit"
            >
              <ExternalLink size={14} />
              View on {model.source_site ?? "source"}
            </a>
          )}

          {model.description && (
            <p className="text-sm text-gray-400 leading-relaxed whitespace-pre-line line-clamp-6">
              {model.description}
            </p>
          )}

          {/* User tags */}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {tags.map((tag) => (
                <Link
                  key={tag}
                  to={`/?tag=${encodeURIComponent(tag)}`}
                  className="flex items-center gap-1 text-xs bg-gray-800 text-gray-400 hover:bg-indigo-950 hover:text-indigo-300 hover:border-indigo-700 border border-transparent px-2 py-1 rounded-full transition-colors"
                >
                  <Tag size={10} />
                  {tag}
                </Link>
              ))}
            </div>
          )}

          {/* Auto-detected tags — click to promote to user tags, shift-click to filter */}
          {(model.auto_tags ?? []).length > 0 && (
            <div className="flex flex-col gap-1.5">
              <p className="text-xs text-gray-600">Auto-detected · click + to add as tag · click label to browse</p>
              <div className="flex flex-wrap gap-1.5">
                {model.auto_tags.map((tag) => {
                  const already = tags.includes(tag);
                  return (
                    <div key={tag} className="flex items-center rounded-full border overflow-hidden border-gray-700">
                      <button
                        onClick={() => addTag(tag)}
                        disabled={already}
                        title={already ? "Already a tag" : "Add as user tag"}
                        className={`flex items-center px-1.5 py-0.5 text-xs border-r border-gray-700 transition-colors ${
                          already
                            ? "bg-indigo-900/30 text-indigo-500 cursor-default"
                            : "bg-gray-800/60 text-gray-500 hover:bg-indigo-950 hover:text-indigo-400"
                        }`}
                      >
                        {already ? <Tag size={9} /> : <Plus size={9} />}
                      </button>
                      <Link
                        to={`/?tag=${encodeURIComponent(tag)}`}
                        className="flex items-center px-2 py-0.5 text-xs bg-gray-800/60 text-gray-500 hover:bg-indigo-950 hover:text-indigo-300 transition-colors"
                      >
                        {tag}
                      </Link>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* STL Files list */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
                <FileBox size={14} />
                Files ({model.stl_files.length})
              </h3>
              {model.stl_files.length > 0 && (
                <div className="flex gap-2">
                  <button
                    onClick={downloadAllFiles}
                    disabled={downloadingAll}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-500 disabled:opacity-40 text-xs text-gray-400 hover:text-gray-200 transition-colors"
                  >
                    <FolderDown size={12} />
                    {downloadingAll ? "Zipping…" : "Download all"}
                  </button>
                  <button
                    onClick={() => setShowKitBuilder(true)}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-indigo-950 border border-gray-700 hover:border-indigo-600 text-xs text-gray-400 hover:text-indigo-300 transition-colors"
                  >
                    <Wrench size={12} />
                    Kit Builder
                  </button>
                </div>
              )}
            </div>
            <datalist id="part-type-list">
              {PART_TYPE_SUGGESTIONS.map((s) => <option key={s} value={s} />)}
            </datalist>
            <div className="flex flex-col gap-1 max-h-64 overflow-y-auto">
              {model.stl_files.map((f) => {
                const pt = partTypes[f.id] ?? "";
                return (
                  <div
                    key={f.id}
                    className="flex items-center gap-2 text-xs bg-gray-900 border border-gray-800 px-3 py-1.5 rounded"
                  >
                    <span className="text-gray-300 truncate flex-1 min-w-0">{f.filename}</span>
                    <input
                      list="part-type-list"
                      value={pt}
                      placeholder="Label…"
                      onChange={(e) => setPartTypes((prev) => ({ ...prev, [f.id]: e.target.value }))}
                      onBlur={(e) => savePartType(f.id, e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                      className="w-28 shrink-0 bg-gray-800 border border-gray-700 focus:border-indigo-500 rounded px-2 py-0.5 text-xs text-gray-300 placeholder-gray-600 focus:outline-none"
                    />
                    {f.size_bytes && (
                      <a
                        href={api.stlUrl(f.path)}
                        download={f.filename}
                        onClick={(e) => e.stopPropagation()}
                        className="text-gray-600 hover:text-gray-400 shrink-0 transition-colors"
                      >
                        {(f.size_bytes / 1024 / 1024).toFixed(1)} MB
                      </a>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* File location */}
          <div className="mt-auto">
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5 mb-2">
              <Folder size={14} />
              Location
            </h3>
            <div className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2">
              <p className="text-xs text-gray-400 break-all font-mono leading-relaxed">
                {model.native_folder_path || model.folder_path}
              </p>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={copyPath}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 transition-colors"
                >
                  {copiedPath ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
                  {copiedPath ? "Copied!" : "Copy path"}
                </button>
                <button
                  onClick={openFolder}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 transition-colors"
                >
                  <FolderDown size={11} />
                  Open folder
                </button>
              </div>
              {openFolderError && (
                <p className="text-xs text-amber-400 mt-1.5">{openFolderError}</p>
              )}
            </div>
          </div>

          </>)} {/* end display mode */}
        </div>
      </div>

      {showImagePicker && (
        <ImagePicker
          modelId={model.id}
          currentPath={model.thumbnail_path}
          currentUrl={model.thumbnail_url ?? null}
          onApplied={() => { setShowImagePicker(false); load(); }}
          onClose={() => setShowImagePicker(false)}
        />
      )}

      {showFindOnWeb && (
        <FindOnWeb
          modelId={model.id}
          modelName={model.title || model.name}
          onApplied={() => { setShowFindOnWeb(false); load(); }}
          onClose={() => setShowFindOnWeb(false)}
        />
      )}

      {showKitBuilder && (
        <KitBuilder
          modelName={model.title || model.name}
          files={model.stl_files.map((f) => ({ ...f, part_type: partTypes[f.id] || f.part_type }))}
          onClose={() => setShowKitBuilder(false)}
        />
      )}
    </div>
  );
}

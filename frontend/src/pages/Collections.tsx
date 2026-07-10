import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { FolderOpen, Plus, Trash2, Pencil, Check, X, ImagePlus } from "lucide-react";
import { api, Collection } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
import CollectionCoverPicker from "../components/CollectionCoverPicker";
import CreateCollectionModal from "../components/CreateCollectionModal";
import { errMsg } from "../utils/err";
import ErrorState from "../components/ErrorState";

function CollectionCard({
  col,
  onDelete,
  onRename,
  onCoverUpdate,
}: {
  col: Collection;
  onDelete: (e: React.MouseEvent, col: Collection) => void;
  onRename: (col: Collection, newName: string, description: string) => Promise<void>;
  onCoverUpdate: (updated: Collection) => void;
}) {
  const { settings } = useAppSettings();
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(col.name);
  const [draftDesc, setDraftDesc] = useState(col.description ?? "");
  const [pickerOpen, setPickerOpen] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  const coverUrl = col.cover_image_path
    ? api.fileUrl(col.cover_image_path)
    : null;
  // A cover image always gets the bigger box; without one, the uniform-size
  // preference decides whether it matches or stays compact.
  const bigBox = !!coverUrl || settings.collections_uniform_size;

  const startRename = (e: React.MouseEvent) => {
    e.preventDefault();
    setDraftName(col.name);
    setDraftDesc(col.description ?? "");
    setRenaming(true);
    setTimeout(() => nameRef.current?.select(), 0);
  };

  const commit = async () => {
    const trimmed = draftName.trim();
    if (!trimmed) { setRenaming(false); return; }
    await onRename(col, trimmed, draftDesc.trim());
    setRenaming(false);
  };

  const cancel = () => {
    setDraftName(col.name);
    setDraftDesc(col.description ?? "");
    setRenaming(false);
  };

  return (
    <>
      <div className="relative group/card">
        {renaming ? (
          <div className="bg-panel border border-accent-start rounded-lg p-4 flex flex-col gap-2">
            <input
              ref={nameRef}
              autoFocus
              type="text"
              placeholder="Name"
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") cancel(); }}
              className="w-full bg-panel-secondary border border-border rounded px-2 py-1 text-sm text-text-primary focus:outline-none focus:border-accent-start"
            />
            <textarea
              rows={5}
              placeholder="Description (optional)"
              value={draftDesc}
              onChange={(e) => setDraftDesc(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Escape") cancel(); }}
              className="w-full resize-none bg-panel-secondary border border-border rounded px-2 py-1 text-sm text-text-primary-alt2 placeholder:text-text-muted focus:outline-none focus:border-accent-start"
            />
            <div className="flex gap-1.5">
              <button
                onClick={commit}
                className="flex items-center gap-1 px-2 py-1 rounded bg-accent-end hover:bg-accent-start text-xs text-white"
              >
                <Check size={11} /> Save
              </button>
              <button
                onClick={cancel}
                className="flex items-center gap-1 px-2 py-1 rounded bg-panel-secondary hover:bg-panel-secondary text-xs text-text-secondary"
              >
                <X size={11} /> Cancel
              </button>
            </div>
          </div>
        ) : (
          <Link
            to={`/collections/${col.id}`}
            className={`relative bg-panel border border-border-subtle rounded-lg overflow-hidden flex flex-col hover:border-accent-start transition-colors block ${
              bigBox ? "aspect-[4/3]" : ""
            }`}
          >
            {/* Cover image or placeholder. With the uniform-size preference off,
                a collection with no cover keeps a compact box instead of matching
                the full aspect-[4/3] height cover art uses. */}
            {coverUrl ? (
              <img
                src={coverUrl}
                alt={col.name}
                className="absolute inset-0 w-full h-full object-cover"
              />
            ) : bigBox ? (
              <div className="absolute inset-0 flex items-center justify-center text-text-muted-alt">
                <FolderOpen size={32} />
              </div>
            ) : (
              <div className="h-12 flex items-center justify-center text-text-muted-alt">
                <FolderOpen size={24} />
              </div>
            )}

            {/* Solid footer — always opaque so text is legible over any cover image */}
            <div className={`${bigBox ? "absolute inset-x-0 bottom-0" : ""} px-3 py-2.5 bg-panel border-t border-border-subtle`}>
              <p className="font-medium text-text-primary text-sm leading-snug truncate">{col.name}</p>
              {col.description && (
                <p
                  className="text-xs text-text-secondary truncate"
                  title={col.description}
                >
                  {col.description}
                </p>
              )}
              <p className="text-xs text-text-secondary-alt mt-0.5">{col.model_count} model{col.model_count !== 1 ? "s" : ""}</p>
            </div>
          </Link>
        )}

        {!renaming && (
          <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover/card:opacity-100 transition-all">
            <button
              onClick={(e) => { e.preventDefault(); setPickerOpen(true); }}
              title="Set cover image"
              className="p-1.5 rounded bg-panel-secondary/90 hover:bg-panel-secondary text-text-secondary hover:text-text-primary-alt border border-transparent hover:border-border-divider"
            >
              <ImagePlus size={13} />
            </button>
            <button
              onClick={startRename}
              title="Rename collection"
              className="p-1.5 rounded bg-panel-secondary/90 hover:bg-panel-secondary text-text-muted hover:text-text-primary-alt2 border border-transparent hover:border-border-divider"
            >
              <Pencil size={13} />
            </button>
            <button
              onClick={(e) => onDelete(e, col)}
              title="Delete collection"
              className="p-1.5 rounded bg-panel-secondary/90 hover:bg-red-950 text-text-muted hover:text-red-400 border border-transparent hover:border-red-800"
            >
              <Trash2 size={13} />
            </button>
          </div>
        )}
      </div>

      {pickerOpen && (
        <CollectionCoverPicker
          collection={col}
          onClose={() => setPickerOpen(false)}
          onUpdate={(updated) => { onCoverUpdate(updated); setPickerOpen(false); }}
        />
      )}
    </>
  );
}

export default function Collections() {
  const { toast } = useToast();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setLoadError(null);
    api.collections.list()
      .then(setCollections)
      .catch((e) => setLoadError(errMsg(e) || "Could not load collections."))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const addCreated = (col: Collection) => {
    setCollections((prev) => [...prev, { ...col, model_count: 0 }]);
  };

  const renameCollection = async (col: Collection, newName: string, description: string) => {
    try {
      const updated = await api.collections.update(col.id, { name: newName, description: description || null });
      setCollections((prev) => prev.map((c) =>
        c.id === col.id ? { ...c, name: updated.name, description: updated.description } : c
      ));
    } catch (e) {
      const detail = errMsg(e) ?? "";
      toast(detail.includes("409") ? "That name is already taken." : "Couldn't save — try again.", "error");
    }
  };

  const deleteCollection = async (e: React.MouseEvent, col: Collection) => {
    e.preventDefault();
    if (!window.confirm(`Delete "${col.name}"? This cannot be undone.`)) return;
    try {
      await api.collections.delete(col.id);
      setCollections((prev) => prev.filter((c) => c.id !== col.id));
      toast(`"${col.name}" deleted.`, "success");
    } catch {
      toast("Couldn't delete collection — try again.", "error");
    }
  };

  const updateCover = (updated: Collection) => {
    setCollections((prev) => prev.map((c) => c.id === updated.id ? { ...c, cover_image_path: updated.cover_image_path } : c));
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <FolderOpen size={20} className="text-indigo-400" />
          <h1 className="text-2xl font-bold text-text-primary">Collections</h1>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-accent-end hover:bg-accent-start text-sm transition-colors"
        >
          <Plus size={14} />
          New Collection
        </button>
      </div>

      {creating && (
        <CreateCollectionModal
          onClose={() => setCreating(false)}
          onCreated={addCreated}
          onCoverUpdate={updateCover}
        />
      )}

      {loading ? (
        <div className="flex justify-center py-24 text-text-secondary-alt text-sm">Loading…</div>
      ) : loadError ? (
        <ErrorState title="Couldn't load collections" message={loadError} onRetry={load} />
      ) : collections.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-text-muted">
          <FolderOpen size={48} />
          <p className="mt-3">No collections yet</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
          {collections.map((col) => (
            <CollectionCard
              key={col.id}
              col={col}
              onDelete={deleteCollection}
              onRename={renameCollection}
              onCoverUpdate={updateCover}
            />
          ))}
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { FolderOpen, Plus, Trash2, Pencil, Check, X, ImagePlus } from "lucide-react";
import { api, Collection } from "../api/client";
import { useToast } from "../context/ToastContext";
import CollectionCoverPicker from "../components/CollectionCoverPicker";

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
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(col.name);
  const [draftDesc, setDraftDesc] = useState(col.description ?? "");
  const [pickerOpen, setPickerOpen] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  const coverUrl = col.cover_image_path
    ? api.fileUrl(col.cover_image_path)
    : null;

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
          <div className="bg-gray-900 border border-indigo-500 rounded-lg p-4 flex flex-col gap-2">
            <input
              ref={nameRef}
              autoFocus
              type="text"
              placeholder="Name"
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") cancel(); }}
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-indigo-500"
            />
            <textarea
              rows={5}
              placeholder="Description (optional)"
              value={draftDesc}
              onChange={(e) => setDraftDesc(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Escape") cancel(); }}
              className="w-full resize-none bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:border-indigo-500"
            />
            <div className="flex gap-1.5">
              <button
                onClick={commit}
                className="flex items-center gap-1 px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-xs text-white"
              >
                <Check size={11} /> Save
              </button>
              <button
                onClick={cancel}
                className="flex items-center gap-1 px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-400"
              >
                <X size={11} /> Cancel
              </button>
            </div>
          </div>
        ) : (
          <Link
            to={`/collections/${col.id}`}
            className="relative bg-gray-900 border border-gray-800 rounded-lg overflow-hidden flex flex-col hover:border-indigo-500 transition-colors block aspect-[4/3]"
          >
            {/* Cover image or placeholder */}
            {coverUrl ? (
              <img
                src={coverUrl}
                alt={col.name}
                className="absolute inset-0 w-full h-full object-cover"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-gray-700">
                <FolderOpen size={32} />
              </div>
            )}

            {/* Solid footer — always opaque so text is legible over any cover image */}
            <div className="absolute inset-x-0 bottom-0 px-3 py-2.5 bg-gray-900 border-t border-gray-800">
              <p className="font-medium text-gray-100 text-sm leading-snug truncate">{col.name}</p>
              {col.description && (
                <p
                  className="text-xs text-gray-400 truncate"
                  title={col.description}
                >
                  {col.description}
                </p>
              )}
              <p className="text-xs text-gray-500 mt-0.5">{col.model_count} model{col.model_count !== 1 ? "s" : ""}</p>
            </div>
          </Link>
        )}

        {!renaming && (
          <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover/card:opacity-100 transition-all">
            <button
              onClick={(e) => { e.preventDefault(); setPickerOpen(true); }}
              title="Set cover image"
              className="p-1.5 rounded bg-gray-800/90 hover:bg-gray-700 text-gray-400 hover:text-gray-200 border border-transparent hover:border-gray-600"
            >
              <ImagePlus size={13} />
            </button>
            <button
              onClick={startRename}
              title="Rename collection"
              className="p-1.5 rounded bg-gray-800/90 hover:bg-gray-700 text-gray-600 hover:text-gray-300 border border-transparent hover:border-gray-600"
            >
              <Pencil size={13} />
            </button>
            <button
              onClick={(e) => onDelete(e, col)}
              title="Delete collection"
              className="p-1.5 rounded bg-gray-800/90 hover:bg-red-950 text-gray-600 hover:text-red-400 border border-transparent hover:border-red-800"
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
  const [name, setName] = useState("");

  useEffect(() => { api.collections.list().then(setCollections).catch(() => {}); }, []);

  const create = async () => {
    if (!name.trim()) return;
    const col = await api.collections.create(name.trim());
    setCollections((prev) => [...prev, { ...col, model_count: 0 }]);
    setName("");
    setCreating(false);
  };

  const renameCollection = async (col: Collection, newName: string, description: string) => {
    try {
      const updated = await api.collections.update(col.id, { name: newName, description: description || null });
      setCollections((prev) => prev.map((c) =>
        c.id === col.id ? { ...c, name: updated.name, description: updated.description } : c
      ));
    } catch (e: any) {
      const detail = e?.message ?? "";
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
          <h1 className="text-2xl font-bold text-gray-100">Collections</h1>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-sm transition-colors"
        >
          <Plus size={14} />
          New Collection
        </button>
      </div>

      {creating && (
        <div className="flex gap-2 mb-4 p-3 bg-gray-900 rounded border border-gray-800">
          <input
            autoFocus
            type="text"
            placeholder="Collection name…"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-100 focus:outline-none focus:border-indigo-500"
          />
          <button onClick={create} className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-sm">
            Create
          </button>
          <button onClick={() => setCreating(false)} className="px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-sm text-gray-400">
            Cancel
          </button>
        </div>
      )}

      {collections.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-gray-600">
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

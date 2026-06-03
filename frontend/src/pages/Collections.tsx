import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { FolderOpen, Plus, Trash2, Pencil, Check, X } from "lucide-react";
import { api, Collection } from "../api/client";
import { useToast } from "../context/ToastContext";

function CollectionCard({
  col,
  onDelete,
  onRename,
}: {
  col: Collection;
  onDelete: (e: React.MouseEvent, col: Collection) => void;
  onRename: (col: Collection, newName: string) => Promise<void>;
}) {
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(col.name);
  const inputRef = useRef<HTMLInputElement>(null);

  const startRename = (e: React.MouseEvent) => {
    e.preventDefault();
    setDraft(col.name);
    setRenaming(true);
    setTimeout(() => inputRef.current?.select(), 0);
  };

  const commit = async () => {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === col.name) { setRenaming(false); return; }
    await onRename(col, trimmed);
    setRenaming(false);
  };

  const cancel = () => { setDraft(col.name); setRenaming(false); };

  return (
    <div className="relative group/card">
      {renaming ? (
        <div className="bg-gray-900 border border-indigo-500 rounded-lg p-4 flex flex-col gap-2">
          <input
            ref={inputRef}
            autoFocus
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") cancel(); }}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-indigo-500"
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
          className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-1 hover:border-indigo-500 transition-colors block"
        >
          <p className="font-medium text-gray-100">{col.name}</p>
          {col.description && <p className="text-xs text-gray-500">{col.description}</p>}
          <p className="text-xs text-gray-600 mt-1">{col.model_count} model{col.model_count !== 1 ? "s" : ""}</p>
        </Link>
      )}

      {!renaming && (
        <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover/card:opacity-100 transition-all">
          <button
            onClick={startRename}
            title="Rename collection"
            className="p-1.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-600 hover:text-gray-300 border border-transparent hover:border-gray-600"
          >
            <Pencil size={13} />
          </button>
          <button
            onClick={(e) => onDelete(e, col)}
            title="Delete collection"
            className="p-1.5 rounded bg-gray-800 hover:bg-red-950 text-gray-600 hover:text-red-400 border border-transparent hover:border-red-800"
          >
            <Trash2 size={13} />
          </button>
        </div>
      )}
    </div>
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

  const renameCollection = async (col: Collection, newName: string) => {
    try {
      const updated = await api.collections.update(col.id, { name: newName });
      setCollections((prev) => prev.map((c) => c.id === col.id ? { ...c, name: updated.name } : c));
    } catch (e: any) {
      const detail = e?.message ?? "";
      toast(detail.includes("409") ? "That name is already taken." : "Couldn't rename — try again.", "error");
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
            />
          ))}
        </div>
      )}
    </div>
  );
}

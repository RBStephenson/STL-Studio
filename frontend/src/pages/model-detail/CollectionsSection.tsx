// Collections membership panel for the ModelDetail page.
// Extracted from ModelDetail.tsx (STUDIO-63 P1) — behavior-preserving.

import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { FolderOpen, Plus, Check } from "lucide-react";
import { api, Collection } from "../../api/client";
import { useToast } from "../../context/ToastContext";

export default function CollectionsSection({ modelId, initialIds }: { modelId: number; initialIds: number[] }) {
  const { toast } = useToast();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [memberIds, setMemberIds] = useState<Set<number>>(new Set(initialIds));
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    api.collections.list().then(setCollections).catch(() => {});
  }, []);

  const toggle = async (col: Collection) => {
    const isMember = memberIds.has(col.id);
    setMemberIds((prev) => {
      const next = new Set(prev);
      isMember ? next.delete(col.id) : next.add(col.id);
      return next;
    });
    try {
      if (isMember) {
        await api.collections.removeModel(col.id, modelId);
      } else {
        await api.collections.addModel(col.id, modelId);
      }
    } catch {
      setMemberIds((prev) => {
        const next = new Set(prev);
        isMember ? next.add(col.id) : next.delete(col.id);
        return next;
      });
      toast("Couldn't update collection — try again.", "error");
    }
  };

  const createAndAdd = async () => {
    if (!newName.trim()) return;
    try {
      const col = await api.collections.create(newName.trim());
      await api.collections.addModel(col.id, modelId);
      setCollections((prev) => [...prev, { ...col, model_count: 1 }]);
      setMemberIds((prev) => new Set([...prev, col.id]));
      setNewName("");
      setCreating(false);
    } catch {
      toast("Couldn't create collection — try again.", "error");
    }
  };

  const memberCollections = collections.filter((c) => memberIds.has(c.id));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
          <FolderOpen size={14} />
          Collections
        </h3>
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-xs text-gray-500 hover:text-indigo-400 transition-colors"
        >
          {open ? "Done" : "Manage"}
        </button>
      </div>

      {memberCollections.length === 0 && !open && (
        <p className="text-xs text-gray-600">Not in any collections</p>
      )}

      {memberCollections.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {memberCollections.map((c) => (
            <Link
              key={c.id}
              to={`/collections/${c.id}`}
              className="text-xs bg-indigo-950 border border-indigo-800 text-indigo-300 hover:bg-indigo-900 px-2 py-0.5 rounded-full transition-colors"
            >
              {c.name}
            </Link>
          ))}
        </div>
      )}

      {open && (
        <div className="flex flex-col gap-1 bg-gray-900 border border-gray-800 rounded-lg p-2">
          {collections.map((c) => (
            <button
              key={c.id}
              onClick={() => toggle(c)}
              className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-800 text-sm text-left transition-colors"
            >
              <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                memberIds.has(c.id)
                  ? "bg-indigo-600 border-indigo-500"
                  : "border-gray-600"
              }`}>
                {memberIds.has(c.id) && <Check size={10} className="text-white" strokeWidth={3} />}
              </span>
              <span className="text-gray-200 truncate">{c.name}</span>
              <span className="text-xs text-gray-600 ml-auto">{c.model_count}</span>
            </button>
          ))}
          {collections.length === 0 && (
            <p className="text-xs text-gray-600 px-2 py-1">No collections yet</p>
          )}
          {creating ? (
            <div className="flex gap-1 mt-1 px-1">
              <input
                autoFocus
                type="text"
                placeholder="Collection name…"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && createAndAdd()}
                className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 focus:outline-none focus:border-indigo-500"
              />
              <button onClick={createAndAdd} className="px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-xs">Create</button>
              <button onClick={() => setCreating(false)} className="px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-400">Cancel</button>
            </div>
          ) : (
            <button
              onClick={() => setCreating(true)}
              className="flex items-center gap-1.5 px-2 py-1.5 rounded hover:bg-gray-800 text-xs text-gray-500 hover:text-indigo-400 transition-colors mt-0.5"
            >
              <Plus size={12} /> New collection
            </button>
          )}
        </div>
      )}
    </div>
  );
}

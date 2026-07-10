import { useState, useRef } from "react";
import { createPortal } from "react-dom";
import { X, Loader2 } from "lucide-react";
import { api, Collection } from "../api/client";
import { errMsg } from "../utils/err";
import CollectionCoverPicker from "./CollectionCoverPicker";

interface Props {
  onClose: () => void;
  onCreated: (col: Collection) => void;
  onCoverUpdate: (updated: Collection) => void;
}

export default function CreateCollectionModal({ onClose, onCreated, onCoverUpdate }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Collection | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  // Once the collection exists, hand off to the same cover picker used from
  // Collection Detail — no cover-assignment logic duplicated here. Skipping
  // (its own X / backdrop click) just closes, leaving the collection as-is.
  if (created) {
    return (
      <CollectionCoverPicker
        collection={created}
        onClose={onClose}
        onUpdate={(updated) => { onCoverUpdate(updated); onClose(); }}
      />
    );
  }

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) { nameRef.current?.focus(); return; }
    setBusy(true);
    setError(null);
    try {
      const col = await api.collections.create(trimmed, description.trim() || undefined);
      onCreated(col);
      setCreated(col);
    } catch (e) {
      const detail = errMsg(e) ?? "";
      setError(detail.includes("409") ? "That name is already taken." : "Couldn't create — try again.");
    } finally {
      setBusy(false);
    }
  };

  const modal = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-sm shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h2 className="text-base font-semibold text-gray-100">New Collection</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-gray-800 text-gray-500 hover:text-gray-300"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5 flex flex-col gap-3">
          <input
            ref={nameRef}
            autoFocus
            type="text"
            placeholder="Collection name…"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-indigo-500"
          />
          <textarea
            rows={4}
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full resize-none bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:border-indigo-500"
          />
          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-gray-800">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-sm text-gray-400"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={busy || !name.trim()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm transition-colors"
          >
            {busy && <Loader2 size={13} className="animate-spin" />}
            Create
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}

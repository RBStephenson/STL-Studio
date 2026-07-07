import { useState, useRef } from "react";
import { createPortal } from "react-dom";
import { X, Loader2 } from "lucide-react";
import { api, Creator } from "../api/client";
import { errMsg } from "../utils/err";

interface Props {
  onClose: () => void;
  onCreated: (creator: Creator) => void;
}

export default function CreateCreatorModal({ onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) { nameRef.current?.focus(); return; }
    setBusy(true);
    setError(null);
    try {
      const creator = await api.models.createCreator(trimmed);
      onCreated(creator);
      onClose();
    } catch (e) {
      const detail = errMsg(e) ?? "";
      setError(detail.includes("409") ? "A creator with that name already exists." : "Couldn't add creator — try again.");
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
          <h2 className="text-base font-semibold text-gray-100">Add Creator</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-gray-800 text-gray-500 hover:text-gray-300"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5 flex flex-col gap-3">
          <p className="text-xs text-gray-500">
            Add a creator without waiting for a scan to find one. Its library folder is created automatically.
          </p>
          <input
            ref={nameRef}
            autoFocus
            type="text"
            placeholder="Creator name…"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-indigo-500"
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
            Add
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}

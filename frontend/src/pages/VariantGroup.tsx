import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { ArrowLeft, Layers, MoveRight, X } from "lucide-react";
import { api, Model } from "../api/client";
import ModelCard from "../components/ModelCard";
import { useToast } from "../context/ToastContext";

function GroupAction({ model, creatorId, onRemoved, onMoved }: {
  model: Model;
  creatorId: number;
  onRemoved: (id: number) => void;
  onMoved: (id: number) => void;
}) {
  const { toast } = useToast();
  const [moving, setMoving] = useState(false);
  const [target, setTarget] = useState("");
  const [saving, setSaving] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const openMove = () => {
    setTarget("");
    setMoving(true);
    api.models.characters(creatorId).then(setSuggestions).catch(() => {});
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const saveMove = async () => {
    const trimmed = target.trim();
    if (!trimmed || trimmed === model.character) { setMoving(false); return; }
    setSaving(true);
    try {
      await api.models.setGroupOverride(model.id, trimmed);
      toast(`Moved to "${trimmed}".`, "success");
      onMoved(model.id);
    } catch (e: any) {
      toast(e?.message || "Couldn't move — try again.", "error");
    } finally {
      setSaving(false);
      setMoving(false);
    }
  };

  const remove = async () => {
    try {
      await api.models.setGroupOverride(model.id, null);
      toast("Removed from group.", "success");
      onRemoved(model.id);
    } catch (e: any) {
      toast(e?.message || "Couldn't remove — try again.", "error");
    }
  };

  const listId = `group-move-${model.id}`;

  if (moving) {
    return (
      <div className="flex items-center gap-1 mt-1.5 px-1">
        <input
          ref={inputRef}
          type="text"
          list={listId}
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") saveMove(); if (e.key === "Escape") setMoving(false); }}
          placeholder="Target group…"
          className="flex-1 min-w-0 px-2 py-1 rounded bg-gray-900 border border-gray-700 focus:border-indigo-500 text-xs text-gray-200 outline-none"
        />
        <datalist id={listId}>
          {suggestions.filter((s) => s !== model.character).map((s) => <option key={s} value={s} />)}
        </datalist>
        <button
          onClick={saveMove}
          disabled={saving || !target.trim()}
          className="px-2 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-xs text-white disabled:opacity-40"
        >
          {saving ? "…" : "Move"}
        </button>
        <button
          onClick={() => setMoving(false)}
          className="px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1 mt-1.5 px-1">
      <button
        onClick={openMove}
        title="Move to a different group"
        className="flex items-center gap-1 flex-1 px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 transition-colors"
      >
        <MoveRight size={11} />
        Move to group
      </button>
      <button
        onClick={remove}
        title="Remove from this group"
        className="px-2 py-1 rounded bg-gray-800 hover:bg-red-900/40 border border-gray-700 hover:border-red-600 text-xs text-gray-500 hover:text-red-400 transition-colors"
      >
        <X size={11} />
      </button>
    </div>
  );
}

export default function VariantGroup() {
  const { creatorId, character } = useParams<{ creatorId: string; character: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [variants, setVariants] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);

  const decodedCharacter = character ? decodeURIComponent(character) : "";
  const numCreatorId = Number(creatorId);
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  useEffect(() => {
    if (!numCreatorId || !decodedCharacter) return;
    setLoading(true);
    api.models
      .variants(numCreatorId, decodedCharacter)
      .then((data) => setVariants(data.items))
      .finally(() => setLoading(false));
  }, [numCreatorId, decodedCharacter]);

  const removeVariant = (id: number) => {
    const next = variants.filter((v) => v.id !== id);
    setVariants(next);
    if (next.length === 0) navigate(from);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => navigate(from)}
          className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <div className="h-4 w-px bg-gray-700" />
        <Layers size={16} className="text-indigo-400" />
        <h1 className="text-xl font-semibold text-white">{decodedCharacter}</h1>
        {!loading && (
          <span className="text-sm text-gray-400">
            {variants.length} variant{variants.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center py-24 text-gray-500 text-sm">Loading…</div>
      ) : variants.length === 0 ? (
        <div className="flex justify-center py-24 text-gray-500 text-sm">No variants found.</div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
          {variants.map((model) => (
            <div key={model.id} className="flex flex-col">
              <ModelCard model={model} backTo={from} />
              <GroupAction
                model={model}
                creatorId={numCreatorId}
                onRemoved={removeVariant}
                onMoved={removeVariant}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

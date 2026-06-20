import { useState, useRef, useEffect } from "react";
import { Tag, Trash2, X, Check, Loader2, FolderOpen, EyeOff, AlertCircle, Pencil } from "lucide-react";
import { api, Collection } from "../api/client";
import { useConfirm } from "../context/ConfirmContext";
import { useToast } from "../context/ToastContext";

interface Props {
  selectedIds: number[];
  totalOnPage: number;
  onSelectAll: () => void;
  onClear: () => void;
  onDone: () => void; // called after a successful bulk op so Library can re-fetch
  collections: Collection[];
}

type Mode = "idle" | "add" | "remove" | "collection" | "enrich";
type Status = "idle" | "loading" | "success" | "error";

function parseTags(raw: string): string[] {
  return raw
    .split(",")
    .map(t => t.trim().toLowerCase())
    .filter(Boolean);
}

export default function BulkTagBar({ selectedIds, totalOnPage, onSelectAll, onClear, onDone, collections }: Props) {
  const confirm = useConfirm();
  const { toast } = useToast();
  const [mode, setMode] = useState<Mode>("idle");
  const [tagInput, setTagInput] = useState("");
  const [colSearch, setColSearch] = useState("");
  const [colOpen, setColOpen] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState("");
  const [enrichCreator, setEnrichCreator] = useState("");
  const [enrichCharacter, setEnrichCharacter] = useState("");
  const [enrichTitle, setEnrichTitle] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const colInputRef = useRef<HTMLInputElement>(null);
  const enrichCreatorRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (mode === "collection") { setColOpen(true); colInputRef.current?.focus(); }
    else if (mode === "enrich") enrichCreatorRef.current?.focus();
    else if (mode !== "idle") inputRef.current?.focus();
  }, [mode]);

  const reset = () => {
    setMode("idle");
    setTagInput("");
    setColSearch("");
    setColOpen(false);
    setEnrichCreator("");
    setEnrichCharacter("");
    setEnrichTitle("");
    setStatus("idle");
    setMessage("");
  };

  const apply = async () => {
    const tags = parseTags(tagInput);
    if (tags.length === 0) return;

    setStatus("loading");
    try {
      const res = await api.models.bulkTag(
        selectedIds,
        mode === "add" ? tags : [],
        mode === "remove" ? tags : [],
      );
      setStatus("success");
      setMessage(`Updated ${res.updated} model${res.updated !== 1 ? "s" : ""}`);
      setTagInput("");
      onDone();
      setTimeout(reset, 1800);
    } catch {
      setStatus("error");
      setMessage("Failed — try again");
      setTimeout(() => setStatus("idle"), 2500);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") apply();
    if (e.key === "Escape") reset();
  };

  const addToCollection = async (col: Collection) => {
    setStatus("loading");
    try {
      await api.collections.bulkAddModels(col.id, selectedIds);
      setStatus("success");
      setMessage(`Added to "${col.name}"`);
      setTimeout(reset, 1800);
    } catch {
      setStatus("error");
      setMessage("Failed — try again");
      setTimeout(() => setStatus("idle"), 2500);
    }
  };

  const n = selectedIds.length;
  const plural = n !== 1 ? "s" : "";

  // "Hide" is the bulk equivalent of the per-card exclude: it removes the models
  // from the viewer (files on disk are kept, restorable from the Excluded view).
  const hideSelected = async () => {
    const ok = await confirm({
      title: `Hide ${n} model${plural}?`,
      message: `This removes ${n} model${plural} from the library. Files on disk are kept, and you can restore them from the Excluded view.`,
      confirmLabel: "Hide",
      destructive: true,
    });
    if (!ok) return;
    setStatus("loading");
    try {
      await api.models.bulkExclude(selectedIds, true);
      toast(`Hid ${n} model${plural}.`, "success");
      onDone();
      onClear();  // models left the grid — drop the now-stale selection
    } catch {
      setStatus("idle");
      toast("Couldn't hide the selected models — try again.", "error");
    }
  };

  const markReview = async () => {
    setStatus("loading");
    try {
      const res = await api.models.bulkReview(selectedIds, true);
      toast(`Flagged ${res.updated} model${res.updated !== 1 ? "s" : ""} for review.`, "success");
      onDone();
      onClear();
    } catch {
      setStatus("idle");
      toast("Couldn't flag the selected models — try again.", "error");
    }
  };

  const applyEnrich = async () => {
    const fields: { creator_name?: string; character?: string; title?: string } = {};
    if (enrichCreator.trim()) fields.creator_name = enrichCreator.trim();
    if (enrichCharacter.trim()) fields.character = enrichCharacter.trim();
    if (enrichTitle.trim()) fields.title = enrichTitle.trim();
    if (Object.keys(fields).length === 0) return;

    setStatus("loading");
    try {
      const res = await api.models.bulkEnrich(selectedIds, fields);
      setStatus("success");
      setMessage(`Updated ${res.updated} model${res.updated !== 1 ? "s" : ""}`);
      onDone();
      setTimeout(reset, 1800);
    } catch {
      setStatus("error");
      setMessage("Failed — try again");
      setTimeout(() => setStatus("idle"), 2500);
    }
  };

  const allSelected = selectedIds.length >= totalOnPage;

  return (
    <div className="fixed bottom-0 inset-x-0 z-50 flex justify-center pb-5 pointer-events-none">
      <div className="pointer-events-auto flex flex-wrap items-center gap-3 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl px-4 py-3 min-w-[520px] max-w-4xl">

        {/* Selection count + select-all / clear */}
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-sm font-medium text-white">
            {selectedIds.length} selected
          </span>
          <button
            onClick={allSelected ? onClear : onSelectAll}
            className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
          >
            {allSelected ? "Deselect all" : "Select all on page"}
          </button>
          <button
            onClick={onClear}
            title="Clear selection"
            className="text-gray-600 hover:text-gray-400 transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        <div className="w-px h-5 bg-gray-700 shrink-0" />

        {/* Status feedback */}
        {status === "success" && (
          <span className="flex items-center gap-1.5 text-sm text-green-400">
            <Check size={14} /> {message}
          </span>
        )}
        {status === "error" && (
          <span className="text-sm text-red-400">{message}</span>
        )}

        {/* Tag input area */}
        {status === "idle" && (mode === "add" || mode === "remove") && (
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <span className={`text-xs font-medium shrink-0 ${mode === "add" ? "text-green-400" : "text-red-400"}`}>
              {mode === "add" ? "Add:" : "Remove:"}
            </span>
            <input
              ref={inputRef}
              type="text"
              value={tagInput}
              onChange={e => setTagInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="tag1, tag2, tag3…"
              className="flex-1 min-w-0 bg-gray-800 border border-gray-600 rounded px-2.5 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
            />
            <button
              onClick={apply}
              disabled={!tagInput.trim()}
              className="flex items-center gap-1 px-3 py-1 rounded text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 transition-colors shrink-0"
            >
              Apply
            </button>
            <button onClick={reset} className="text-gray-600 hover:text-gray-400 transition-colors">
              <X size={14} />
            </button>
          </div>
        )}

        {status === "loading" && (
          <span className="flex items-center gap-1.5 text-sm text-gray-400">
            <Loader2 size={14} className="animate-spin" /> Updating…
          </span>
        )}

        {/* Collection picker */}
        {status === "idle" && mode === "collection" && (
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <span className="text-xs font-medium text-indigo-400 shrink-0">Add to:</span>
            <div className="relative flex-1 min-w-0 max-w-xs">
              <input
                ref={colInputRef}
                type="text"
                value={colSearch}
                onChange={e => { setColSearch(e.target.value); setColOpen(true); }}
                onFocus={() => setColOpen(true)}
                onKeyDown={e => { if (e.key === "Escape") reset(); }}
                placeholder={collections.length === 0 ? "No collections yet" : "Search collections…"}
                disabled={collections.length === 0}
                className="w-full bg-gray-800 border border-gray-600 rounded px-2.5 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500 disabled:opacity-40"
              />
              {colOpen && collections.length > 0 && (() => {
                const filtered = collections.filter(c =>
                  c.name.toLowerCase().includes(colSearch.toLowerCase())
                );
                return filtered.length > 0 ? (
                  <ul className="absolute bottom-full mb-1 left-0 right-0 bg-gray-800 border border-gray-600 rounded shadow-xl max-h-48 overflow-y-auto z-10">
                    {filtered.map(col => (
                      <li key={col.id}>
                        <button
                          onMouseDown={e => { e.preventDefault(); addToCollection(col); }}
                          className="w-full text-left px-3 py-1.5 text-sm text-gray-200 hover:bg-indigo-700 hover:text-white transition-colors"
                        >
                          {col.name}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null;
              })()}
            </div>
            <button onClick={reset} className="text-gray-600 hover:text-gray-400 transition-colors shrink-0">
              <X size={14} />
            </button>
          </div>
        )}

        {/* Enrich panel */}
        {status === "idle" && mode === "enrich" && (
          <div className="flex items-center gap-2 flex-1 flex-wrap min-w-0">
            <span className="text-xs font-medium text-indigo-400 shrink-0">Enrich:</span>
            <input
              ref={enrichCreatorRef}
              type="text"
              value={enrichCreator}
              onChange={e => setEnrichCreator(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") applyEnrich(); if (e.key === "Escape") reset(); }}
              placeholder="Creator"
              className="w-32 bg-gray-800 border border-gray-600 rounded px-2.5 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
            />
            <input
              type="text"
              value={enrichCharacter}
              onChange={e => setEnrichCharacter(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") applyEnrich(); if (e.key === "Escape") reset(); }}
              placeholder="Character"
              className="w-32 bg-gray-800 border border-gray-600 rounded px-2.5 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
            />
            <input
              type="text"
              value={enrichTitle}
              onChange={e => setEnrichTitle(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") applyEnrich(); if (e.key === "Escape") reset(); }}
              placeholder="Title"
              className="w-40 bg-gray-800 border border-gray-600 rounded px-2.5 py-1 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
            />
            <button
              onClick={applyEnrich}
              disabled={!enrichCreator.trim() && !enrichCharacter.trim() && !enrichTitle.trim()}
              className="flex items-center gap-1 px-3 py-1 rounded text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 transition-colors shrink-0"
            >
              Apply
            </button>
            <button onClick={reset} className="text-gray-600 hover:text-gray-400 transition-colors shrink-0">
              <X size={14} />
            </button>
          </div>
        )}

        {/* Action buttons */}
        {status === "idle" && mode === "idle" && (
          <div className="flex flex-wrap items-center gap-2 ml-auto">
            <button
              onClick={() => setMode("add")}
              className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            >
              <Tag size={13} />
              Add Tags
            </button>
            <button
              onClick={() => setMode("remove")}
              className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            >
              <Trash2 size={13} />
              Remove Tags
            </button>
            <button
              onClick={() => setMode("collection")}
              className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            >
              <FolderOpen size={13} />
              Add to Collection
            </button>
            <button
              onClick={() => setMode("enrich")}
              className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            >
              <Pencil size={13} />
              Enrich
            </button>
            <button
              onClick={markReview}
              title="Flag the selected models for review"
              className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            >
              <AlertCircle size={13} />
              Mark Review
            </button>
            <button
              onClick={hideSelected}
              title="Hide the selected models from the library (files kept on disk)"
              className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-gray-800 border border-red-900/60 text-red-400 hover:bg-red-950/50 hover:text-red-300 transition-colors"
            >
              <EyeOff size={13} />
              Hide
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

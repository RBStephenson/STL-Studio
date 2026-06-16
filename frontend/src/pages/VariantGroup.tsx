import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { ArrowLeft, Layers, MoveRight, X, Keyboard, Pencil, Check } from "lucide-react";
import { api, Model } from "../api/client";
import ModelCard from "../components/ModelCard";
import ShortcutsOverlay from "../components/ShortcutsOverlay";
import { useToast } from "../context/ToastContext";
import { modelLinkTo } from "../utils/modelLink";
import { measureGridColumns } from "../utils/libraryKeys";
import { useLibraryKeyboard } from "../hooks/useLibraryKeyboard";

// Shared write path for every group op (rename/move/ungroup, single or bulk):
// each reduces to "set GroupOverride for a SET of models". Resolves true on
// success so callers can apply optimistic updates; toasts + returns false on
// failure. Reports any models the backend skipped (unknown ids → `missing`).
type ApplyGroup = (ids: number[], character: string | null) => Promise<boolean>;

function GroupAction({ model, creatorId, applyGroup, onRemoved, onMoved }: {
  model: Model;
  creatorId: number;
  applyGroup: ApplyGroup;
  onRemoved: (id: number) => void;
  onMoved: (id: number) => void;
}) {
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
    const ok = await applyGroup([model.id], trimmed);
    setSaving(false);
    setMoving(false);
    if (ok) onMoved(model.id);
  };

  const remove = async () => {
    if (await applyGroup([model.id], null)) onRemoved(model.id);
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

// Bulk "move selected to group" control: a button that expands into an
// autocomplete input. Module-scope to avoid the define-component-in-render
// remount/focus-loss trap.
function BulkMove({ creatorId, currentGroup, onMove }: {
  creatorId: number;
  currentGroup: string;
  onMove: (target: string) => void | Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const openMove = () => {
    setTarget("");
    setOpen(true);
    api.models.characters(creatorId).then(setSuggestions).catch(() => {});
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const submit = async () => {
    if (!target.trim()) return;
    await onMove(target);
    setOpen(false);
  };

  if (!open) {
    return (
      <button
        onClick={openMove}
        aria-label="Move selected to group"
        className="flex items-center gap-1 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-400 hover:text-gray-200 transition-colors"
      >
        <MoveRight size={13} />
        Move to group
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <input
        ref={inputRef}
        type="text"
        list="bulk-move-groups"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") setOpen(false); }}
        placeholder="Target group…"
        aria-label="Target group"
        className="px-2 py-1 rounded bg-gray-900 border border-gray-700 focus:border-indigo-500 text-xs text-gray-200 outline-none"
      />
      <datalist id="bulk-move-groups">
        {suggestions.filter((s) => s !== currentGroup).map((s) => <option key={s} value={s} />)}
      </datalist>
      <button
        onClick={submit}
        disabled={!target.trim()}
        className="px-2 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-xs text-white disabled:opacity-40"
      >
        Move
      </button>
      <button
        onClick={() => setOpen(false)}
        className="px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs text-gray-400"
      >
        Cancel
      </button>
    </div>
  );
}

export default function VariantGroup() {
  const { creatorId, character } = useParams<{ creatorId: string; character: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();
  const [variants, setVariants] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // Tracks whether the group has ever been populated, so emptying it via
  // bulk ops navigates back — but the initial empty render does not.
  const hadVariants = useRef(false);

  const decodedCharacter = character ? decodeURIComponent(character) : "";
  const numCreatorId = Number(creatorId);
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  useEffect(() => {
    if (!numCreatorId || !decodedCharacter) return;
    setLoading(true);
    setSelected(new Set());
    hadVariants.current = false;
    api.models
      .variants(numCreatorId, decodedCharacter)
      .then((data) => {
        setVariants(data.items);
        if (data.items.length > 0) hadVariants.current = true;
      })
      .finally(() => setLoading(false));
  }, [numCreatorId, decodedCharacter]);

  // Navigate back once the group has been emptied by bulk/single ops.
  useEffect(() => {
    if (hadVariants.current && variants.length === 0) navigate(from);
  }, [variants, navigate, from]);

  const removeVariants = useCallback((ids: number[]) => {
    const drop = new Set(ids);
    setVariants((prev) => prev.filter((v) => !drop.has(v.id)));
    setSelected((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
  }, []);

  const removeVariant = useCallback((id: number) => removeVariants([id]), [removeVariants]);

  // Shared write path: set GroupOverride for a set of models, surfacing partial
  // success (`missing`) and the scan-in-progress 409 as toasts. Optimistic list
  // updates are the caller's responsibility (see removeVariants).
  const applyGroup = useCallback<ApplyGroup>(async (ids, character) => {
    try {
      const res = await api.models.batchSetGroup(ids, character);
      const moved = res.updated.length;
      const skipped = res.missing.length;
      const where = character === null ? "removed from group" : `moved to "${character}"`;
      const noun = moved === 1 ? "model" : "models";
      toast(
        skipped > 0
          ? `${moved} ${noun} ${where}; ${skipped} skipped.`
          : `${moved} ${noun} ${where}.`,
        "success",
      );
      return true;
    } catch (e: any) {
      toast(e?.message || "Couldn't update group — try again.", "error");
      return false;
    }
  }, [toast]);

  // --- Selection -------------------------------------------------------------
  const toggleSelect = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const allSelected = variants.length > 0 && selected.size === variants.length;
  const toggleSelectAll = () =>
    setSelected(allSelected ? new Set() : new Set(variants.map((v) => v.id)));

  const selectedIds = variants.filter((v) => selected.has(v.id)).map((v) => v.id);

  const moveSelected = async (targetGroup: string) => {
    const trimmed = targetGroup.trim();
    if (!trimmed || trimmed === decodedCharacter || selectedIds.length === 0) return;
    if (await applyGroup(selectedIds, trimmed)) removeVariants(selectedIds);
  };

  const ungroupSelected = async () => {
    if (selectedIds.length === 0) return;
    if (await applyGroup(selectedIds, null)) removeVariants(selectedIds);
  };

  // --- Rename (applies to the whole group) -----------------------------------
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const renameRef = useRef<HTMLInputElement>(null);

  const openRename = () => {
    setRenameValue(decodedCharacter);
    setRenaming(true);
    setTimeout(() => renameRef.current?.select(), 0);
  };

  const saveRename = async () => {
    const trimmed = renameValue.trim();
    if (!trimmed || trimmed === decodedCharacter) { setRenaming(false); return; }
    const ids = variants.map((v) => v.id);
    if (await applyGroup(ids, trimmed)) {
      setRenaming(false);
      // The route's :character param is now stale — navigate to the new group.
      navigate(`/groups/${numCreatorId}/${encodeURIComponent(trimmed)}`, {
        replace: true,
        state: { from },
      });
    }
  };

  // --- Keyboard navigation (#169) --------------------------------------------
  // Same WASD/arrow + Enter + "?" controls as the Library grid. No search box
  // here, so "/" is a no-op.
  const [showShortcuts, setShowShortcuts] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);
  const getColumns = useCallback(() => measureGridColumns(gridRef.current), []);

  const openVariant = useCallback((index: number) => {
    const m = variants[index];
    if (!m) return;
    sessionStorage.setItem("library_scroll", String(window.scrollY));
    navigate(modelLinkTo(m), { state: { from } });
  }, [variants, navigate, from]);

  const { focusedIndex, setFocusedIndex } = useLibraryKeyboard({
    count: variants.length,
    getColumns,
    onActivate: openVariant,
    onFocusSearch: () => {},
    onToggleHelp: () => setShowShortcuts((o) => !o),
    onEscape: () => {
      if (showShortcuts) { setShowShortcuts(false); return; }
      const active = document.activeElement;
      if (active instanceof HTMLElement && active.tagName === "INPUT") { active.blur(); return; }
      setFocusedIndex(-1);
    },
  });

  // Keep the focus ring valid as variants are moved/removed out of the group.
  useEffect(() => { setFocusedIndex(-1); }, [variants, setFocusedIndex]);

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
        {renaming ? (
          <div className="flex items-center gap-1">
            <input
              ref={renameRef}
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveRename();
                if (e.key === "Escape") setRenaming(false);
              }}
              aria-label="Group name"
              className="px-2 py-1 rounded bg-gray-900 border border-gray-700 focus:border-indigo-500 text-lg text-white outline-none"
            />
            <button
              onClick={saveRename}
              disabled={!renameValue.trim() || renameValue.trim() === decodedCharacter}
              title="Save name"
              aria-label="Save name"
              className="p-1.5 rounded bg-indigo-700 hover:bg-indigo-600 text-white disabled:opacity-40"
            >
              <Check size={16} />
            </button>
            <button
              onClick={() => setRenaming(false)}
              title="Cancel rename"
              aria-label="Cancel rename"
              className="p-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-400"
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <button
            onClick={openRename}
            disabled={loading || variants.length === 0}
            title="Rename group"
            className="group flex items-center gap-1.5 text-xl font-semibold text-white hover:text-indigo-300 transition-colors disabled:hover:text-white"
          >
            {decodedCharacter}
            <Pencil size={14} className="opacity-0 group-hover:opacity-60" />
          </button>
        )}
        {!loading && (
          <span className="text-sm text-gray-400">
            {variants.length} variant{variants.length !== 1 ? "s" : ""}
          </span>
        )}
        <button
          onClick={() => setShowShortcuts(true)}
          title="Keyboard shortcuts ( ? )"
          aria-label="Keyboard shortcuts"
          className="ml-auto p-1.5 rounded border border-gray-700 bg-gray-900 text-gray-400 hover:text-gray-100 hover:border-gray-500 transition-colors"
        >
          <Keyboard size={16} />
        </button>
      </div>

      {!loading && variants.length > 0 && (
        <div className="flex items-center gap-3 mb-4 text-sm">
          <button
            onClick={toggleSelectAll}
            className="text-gray-400 hover:text-white transition-colors"
          >
            {allSelected ? "Clear selection" : "Select all"}
          </button>
          {selected.size > 0 && (
            <>
              <div className="h-4 w-px bg-gray-700" />
              <span className="text-gray-400">{selected.size} selected</span>
              <BulkMove creatorId={numCreatorId} currentGroup={decodedCharacter} onMove={moveSelected} />
              <button
                onClick={ungroupSelected}
                className="flex items-center gap-1 px-2.5 py-1 rounded bg-gray-800 hover:bg-red-900/40 border border-gray-700 hover:border-red-600 text-gray-400 hover:text-red-400 transition-colors"
              >
                <X size={13} />
                Ungroup
              </button>
            </>
          )}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-24 text-gray-500 text-sm">Loading…</div>
      ) : variants.length === 0 ? (
        <div className="flex justify-center py-24 text-gray-500 text-sm">No variants found.</div>
      ) : (
        <div ref={gridRef} className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
          {variants.map((model, i) => (
            <div key={model.id} className="flex flex-col">
              <div className="relative">
                <label className="absolute top-2 left-2 z-10 flex items-center justify-center p-1 rounded bg-gray-900/80 border border-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.has(model.id)}
                    onChange={() => toggleSelect(model.id)}
                    aria-label={`Select ${model.name}`}
                    className="h-4 w-4 accent-indigo-500 cursor-pointer"
                  />
                </label>
                <ModelCard model={model} backTo={from} focused={focusedIndex === i} />
              </div>
              <GroupAction
                model={model}
                creatorId={numCreatorId}
                applyGroup={applyGroup}
                onRemoved={removeVariant}
                onMoved={removeVariant}
              />
            </div>
          ))}
        </div>
      )}

      {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} showSearch={false} />}
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { ArrowLeft, Layers, MoveRight, X, Keyboard, Pencil, Check, Image as ImageIcon, GripVertical, ListRestart, Link as LinkIcon } from "lucide-react";
import {
  DndContext, PointerSensor, KeyboardSensor, useSensor, useSensors,
  closestCenter, DragStartEvent, DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext, useSortable, rectSortingStrategy, sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { api, Model } from "../api/client";
import ModelCard from "../components/ModelCard";
import ShortcutsOverlay from "../components/ShortcutsOverlay";
import { useToast } from "../context/ToastContext";
import { modelLinkTo } from "../utils/modelLink";
import { measureGridColumns } from "../utils/libraryKeys";
import { reorderedIds } from "../utils/reorderList";
import { useLibraryKeyboard } from "../hooks/useLibraryKeyboard";
import { errMsg } from "../utils/err";

// Shared write paths for every group op (#678): move resolves (or creates) the
// target durable group and merges ids into it; remove splits ids out of the
// current durable group. Resolve true on success so callers can apply
// optimistic updates; toast + return false on failure.
type MoveToGroup = (ids: number[], targetLabel: string) => Promise<boolean>;
type RemoveFromGroup = (ids: number[]) => Promise<boolean>;

function GroupAction({ model, creatorId, moveToGroup, removeFromGroup, onRemoved, onMoved, onRepChanged }: {
  model: Model;
  creatorId: number;
  moveToGroup: MoveToGroup;
  removeFromGroup: RemoveFromGroup;
  onRemoved: (id: number) => void;
  onMoved: (id: number) => void;
  onRepChanged: () => void;
}) {
  const { toast } = useToast();
  const [moving, setMoving] = useState(false);
  const [target, setTarget] = useState("");
  const [saving, setSaving] = useState(false);
  const [settingRep, setSettingRep] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const makeRep = async () => {
    if (model.is_group_rep || settingRep) return;
    setSettingRep(true);
    try {
      await api.models.setGroupRep(model.id, true);
      toast("Group thumbnail updated.", "success");
      onRepChanged();
    } catch (e) {
      toast(errMsg(e) || "Couldn't set the group thumbnail — try again.", "error");
    } finally {
      setSettingRep(false);
    }
  };

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
    const ok = await moveToGroup([model.id], trimmed);
    setSaving(false);
    setMoving(false);
    if (ok) onMoved(model.id);
  };

  const remove = async () => {
    if (await removeFromGroup([model.id])) onRemoved(model.id);
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
          className="flex-1 min-w-0 px-2 py-1 rounded bg-panel border border-border focus:border-accent-start text-xs text-text-primary-alt outline-none"
        />
        <datalist id={listId}>
          {suggestions.filter((s) => s !== model.character).map((s) => <option key={s} value={s} />)}
        </datalist>
        <button
          onClick={saveMove}
          disabled={saving || !target.trim()}
          className="px-2 py-1 rounded bg-indigo-700 hover:bg-accent-end text-xs text-white disabled:opacity-40"
        >
          {saving ? "…" : "Move"}
        </button>
        <button
          onClick={() => setMoving(false)}
          className="px-2 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-xs text-text-secondary"
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
        className="flex items-center gap-1 flex-1 px-2 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-xs text-text-secondary hover:text-text-primary-alt transition-colors"
      >
        <MoveRight size={11} />
        Move to group
      </button>
      <button
        onClick={makeRep}
        disabled={model.is_group_rep || settingRep}
        title={model.is_group_rep ? "This is the group's display thumbnail" : "Use as the group's display thumbnail"}
        aria-label={model.is_group_rep ? "Current group thumbnail" : "Set as group thumbnail"}
        className={`px-2 py-1 rounded border text-xs transition-colors ${
          model.is_group_rep
            ? "bg-indigo-900/50 border-indigo-600 text-indigo-300 cursor-default"
            : "bg-panel-secondary hover:bg-panel-secondary border-border text-text-secondary-alt hover:text-text-primary-alt"
        }`}
      >
        <ImageIcon size={11} />
      </button>
      <button
        onClick={remove}
        title="Remove from this group"
        className="px-2 py-1 rounded bg-panel-secondary hover:bg-red-900/40 border border-border hover:border-red-600 text-xs text-text-secondary-alt hover:text-red-400 transition-colors"
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
        className="flex items-center gap-1 px-2.5 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-text-secondary hover:text-text-primary-alt transition-colors"
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
        className="px-2 py-1 rounded bg-panel border border-border focus:border-accent-start text-xs text-text-primary-alt outline-none"
      />
      <datalist id="bulk-move-groups">
        {suggestions.filter((s) => s !== currentGroup).map((s) => <option key={s} value={s} />)}
      </datalist>
      <button
        onClick={submit}
        disabled={!target.trim()}
        className="px-2 py-1 rounded bg-indigo-700 hover:bg-accent-end text-xs text-white disabled:opacity-40"
      >
        Move
      </button>
      <button
        onClick={() => setOpen(false)}
        className="px-2 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-xs text-text-secondary"
      >
        Cancel
      </button>
    </div>
  );
}

// Bulk "set image for selected" control: a button that expands into a URL
// input. The pasted image (or product page → og:image) is downloaded once
// server-side and applied to every selected member (#184). Module-scope to
// avoid the define-component-in-render remount/focus-loss trap.
function BulkSetImage({ onApply }: { onApply: (url: string) => void | Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const openInput = () => {
    setUrl("");
    setOpen(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const submit = async () => {
    if (!url.trim() || saving) return;
    setSaving(true);
    await onApply(url.trim());
    setSaving(false);
    setOpen(false);
  };

  if (!open) {
    return (
      <button
        onClick={openInput}
        aria-label="Set image for selected"
        className="flex items-center gap-1 px-2.5 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-text-secondary hover:text-text-primary-alt transition-colors"
      >
        <ImageIcon size={13} />
        Set image
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <input
        ref={inputRef}
        type="url"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") setOpen(false); }}
        placeholder="Image or page URL…"
        aria-label="Image URL"
        className="px-2 py-1 rounded bg-panel border border-border focus:border-accent-start text-xs text-text-primary-alt outline-none w-56"
      />
      <button
        onClick={submit}
        disabled={saving || !url.trim()}
        className="px-2 py-1 rounded bg-indigo-700 hover:bg-accent-end text-xs text-white disabled:opacity-40"
      >
        {saving ? "…" : "Apply"}
      </button>
      <button
        onClick={() => setOpen(false)}
        className="px-2 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-xs text-text-secondary"
      >
        Cancel
      </button>
    </div>
  );
}

// Bulk "set store page for selected" control (#500): paste a store URL, applied
// to exactly the selected variants (overwriting any existing URL). Selection is
// the scope — unselected siblings are left untouched (no fill-empty propagation,
// unlike the single-model edit path #202). Module-scope to avoid the
// define-component-in-render remount/focus-loss trap.
function BulkSetStoreLink({ onApply }: { onApply: (url: string) => void | Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const openInput = () => {
    setUrl("");
    setOpen(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const submit = async () => {
    if (!url.trim() || saving) return;
    setSaving(true);
    await onApply(url.trim());
    setSaving(false);
    setOpen(false);
  };

  if (!open) {
    return (
      <button
        onClick={openInput}
        aria-label="Set store page for selected"
        className="flex items-center gap-1 px-2.5 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-text-secondary hover:text-text-primary-alt transition-colors"
      >
        <LinkIcon size={13} />
        Set store page
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <input
        ref={inputRef}
        type="url"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") setOpen(false); }}
        placeholder="Store page URL…"
        aria-label="Store page URL"
        className="px-2 py-1 rounded bg-panel border border-border focus:border-accent-start text-xs text-text-primary-alt outline-none w-56"
      />
      <button
        onClick={submit}
        disabled={saving || !url.trim()}
        className="px-2 py-1 rounded bg-indigo-700 hover:bg-accent-end text-xs text-white disabled:opacity-40"
      >
        {saving ? "…" : "Apply"}
      </button>
      <button
        onClick={() => setOpen(false)}
        className="px-2 py-1 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-xs text-text-secondary"
      >
        Cancel
      </button>
    </div>
  );
}

// Sortable wrapper for one variant card (#399). Drag listeners live on a small
// grip handle (top-left) so card clicks, the selection checkbox, and the link
// still work; the handle is keyboard-operable (Space to pick up, arrows to move).
function SortableCard({ id, children }: { id: number; children: React.ReactNode }) {
  const { setNodeRef, transform, transition, listeners, attributes, isDragging } =
    useSortable({ id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    zIndex: isDragging ? 10 : undefined,
  };
  return (
    <div ref={setNodeRef} style={style} className="relative flex flex-col group/sortable">
      <button
        {...listeners}
        {...attributes}
        aria-label="Drag to reorder"
        title="Drag to reorder within the group"
        className="absolute top-2 left-2 z-30 p-1 rounded bg-black/60 hover:bg-black/90 text-text-primary-alt2 hover:text-white cursor-grab active:cursor-grabbing touch-none opacity-0 group-hover/sortable:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-indigo-400 outline-none transition-opacity"
      >
        <GripVertical size={14} />
      </button>
      {children}
    </div>
  );
}

export default function VariantGroup() {
  const { creatorId, character } = useParams<{ creatorId: string; character: string }>();
  const [searchParams] = useSearchParams();
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
  const groupId = searchParams.get("gid") ? Number(searchParams.get("gid")) : null;
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  useEffect(() => {
    if (!numCreatorId || !decodedCharacter) return;
    setLoading(true);
    setSelected(new Set());
    hadVariants.current = false;
    api.models
      .variants(numCreatorId, decodedCharacter, groupId)
      .then((data) => {
        setVariants(data.items);
        if (data.items.length > 0) hadVariants.current = true;
      })
      .finally(() => setLoading(false));
  }, [numCreatorId, decodedCharacter, groupId]);

  const reloadVariants = useCallback(() => {
    if (!numCreatorId || !decodedCharacter) return;
    api.models
      .variants(numCreatorId, decodedCharacter, groupId)
      .then((data) => setVariants(data.items))
      .catch(() => {});
  }, [numCreatorId, decodedCharacter, groupId]);

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

  // Move ids into the durable group for `targetLabel` (#678). Resolves an
  // existing group by looking up any current member of that character/label —
  // same character-based lookup the target-group autocomplete already used —
  // and merges into it; falls back to creating a brand-new group when none is
  // found. Optimistic list updates are the caller's responsibility.
  const moveToGroup = useCallback<MoveToGroup>(async (ids, targetLabel) => {
    try {
      const { items } = await api.models.variants(numCreatorId, targetLabel);
      const rep = items[0];
      const groupId = rep?.variant_group_id ?? null;
      const label = rep?.variant_group?.label || targetLabel;
      await api.models.mergeGroup(ids, groupId ? { groupId, label } : { label });
      const noun = ids.length === 1 ? "model" : "models";
      toast(`${ids.length} ${noun} moved to "${label}".`, "success");
      return true;
    } catch (e) {
      toast(errMsg(e) || "Couldn't move to that group — try again.", "error");
      return false;
    }
  }, [numCreatorId, toast]);

  // Split ids out of this page's durable group (#678). Requires the ?gid= this
  // page was opened with — every durable group now carries one post-Phase 3.
  const removeFromGroup = useCallback<RemoveFromGroup>(async (ids) => {
    if (groupId == null) {
      toast("Can't remove from a group with no durable group id.", "error");
      return false;
    }
    try {
      await api.models.splitGroup(groupId, ids);
      const noun = ids.length === 1 ? "model" : "models";
      toast(`${ids.length} ${noun} removed from group.`, "success");
      return true;
    } catch (e) {
      toast(errMsg(e) || "Couldn't remove from group — try again.", "error");
      return false;
    }
  }, [groupId, toast]);

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

  // --- Manual drag-reorder (#399) --------------------------------------------
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const dndSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  // Whether the user has imposed a manual order (any member carries one). Drives
  // the "Reset order" affordance; cleared optimistically on reset.
  const [hasManualOrder, setHasManualOrder] = useState(false);
  useEffect(() => {
    setHasManualOrder(variants.some((v) => v.variant_order != null));
  }, [variants]);

  const onReorderStart = (e: DragStartEvent) => setDraggingId(Number(e.active.id));

  const onReorderEnd = async (e: DragEndEvent) => {
    setDraggingId(null);
    const activeId = Number(e.active.id);
    const overId = e.over ? Number(e.over.id) : activeId;
    const order = reorderedIds(variants.map((v) => v.id), activeId, overId);
    if (order.length !== variants.length || order.every((id, i) => id === variants[i].id)) return;
    const prev = variants;
    const byId = new Map(prev.map((v) => [v.id, v]));
    setVariants(order.map((id) => byId.get(id)!));   // optimistic
    setHasManualOrder(true);
    try {
      await api.models.reorderGroup(numCreatorId, decodedCharacter, order, groupId);
    } catch (err) {
      setVariants(prev);   // roll back
      toast(errMsg(err) || "Couldn't save the order — try again.", "error");
    }
  };

  const resetOrder = async () => {
    try {
      await api.models.reorderGroup(numCreatorId, decodedCharacter, [], groupId);
      setHasManualOrder(false);
      reloadVariants();
      toast("Order reset to default.", "success");
    } catch (err) {
      toast(errMsg(err) || "Couldn't reset the order — try again.", "error");
    }
  };

  const moveSelected = async (targetGroup: string) => {
    const trimmed = targetGroup.trim();
    if (!trimmed || trimmed === decodedCharacter || selectedIds.length === 0) return;
    if (await moveToGroup(selectedIds, trimmed)) removeVariants(selectedIds);
  };

  const ungroupSelected = async () => {
    if (selectedIds.length === 0) return;
    if (await removeFromGroup(selectedIds)) removeVariants(selectedIds);
  };

  // Set one image on every selected member (#184). Fetched once server-side,
  // fanned out to each member. On success refetch so the bumped updated_at
  // cache-busts the grid thumbnails (#185); selection is preserved.
  const setImageForSelected = async (url: string) => {
    if (selectedIds.length === 0) return;
    try {
      const res = await api.models.batchThumbnailFromUrl(selectedIds, url);
      const n = res.updated.length;
      const noun = n === 1 ? "model" : "models";
      if (!res.downloaded) {
        toast(`Saved image link on ${n} ${noun} — it may not load if the host blocks embedding.`, "error");
      } else {
        const skipped = res.missing.length;
        toast(skipped > 0 ? `Image set on ${n} ${noun}; ${skipped} skipped.` : `Image set on ${n} ${noun}.`, "success");
      }
      const data = await api.models.variants(numCreatorId, decodedCharacter, groupId);
      setVariants(data.items);
    } catch (e) {
      toast(errMsg(e) || "Couldn't set the group image — try again.", "error");
    }
  };

  // Set the store page on every selected member and, when the site is
  // scrapeable, fetch its metadata once and apply it to all of them (#545).
  // Variants share the same product page, so one scrape fans out to the whole
  // selection. Refetch on success so the grid reflects the change; selection is
  // preserved.
  const setStoreUrlForSelected = async (url: string) => {
    if (selectedIds.length === 0) return;
    try {
      const res = await api.scrape.applyGroup(selectedIds, url);
      const skipped = res.missing.length;
      toast(
        skipped > 0 ? `${res.message} (${skipped} skipped.)` : res.message,
        res.scraped ? "success" : "info",
      );
      const data = await api.models.variants(numCreatorId, decodedCharacter, groupId);
      setVariants(data.items);
    } catch (e) {
      toast(errMsg(e) || "Couldn't set the store page — try again.", "error");
    }
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
    // Relabels the durable VariantGroup row directly (#678) — it no longer
    // rewrites each member's `character` column, so the route must carry the
    // ?gid= forward or the page can't resolve its own group on the next load.
    if (groupId == null) {
      toast("Can't rename a group with no durable group id.", "error");
      return;
    }
    try {
      await api.models.patchGroup(groupId, { label: trimmed });
      setRenaming(false);
      // The route's :character param is now stale — navigate to the new group.
      navigate(`/groups/${numCreatorId}/${encodeURIComponent(trimmed)}?gid=${groupId}`, {
        replace: true,
        state: { from },
      });
    } catch (e) {
      toast(errMsg(e) || "Couldn't rename group — try again.", "error");
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
    // Pause grid WASD/arrow nav while a card is picked up so arrows drive the
    // sortable drag, not the focus ring (#399, mirrors the Library grid #139).
    enabled: draggingId === null,
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
          className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-white transition-colors"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <div className="h-4 w-px bg-panel-secondary" />
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
              className="px-2 py-1 rounded bg-panel border border-border focus:border-accent-start text-lg text-white outline-none"
            />
            <button
              onClick={saveRename}
              disabled={!renameValue.trim() || renameValue.trim() === decodedCharacter}
              title="Save name"
              aria-label="Save name"
              className="p-1.5 rounded bg-indigo-700 hover:bg-accent-end text-white disabled:opacity-40"
            >
              <Check size={16} />
            </button>
            <button
              onClick={() => setRenaming(false)}
              title="Cancel rename"
              aria-label="Cancel rename"
              className="p-1.5 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-text-secondary"
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
          <span className="text-sm text-text-secondary">
            {variants.length} variant{variants.length !== 1 ? "s" : ""}
          </span>
        )}
        <button
          onClick={() => setShowShortcuts(true)}
          title="Keyboard shortcuts ( ? )"
          aria-label="Keyboard shortcuts"
          className="ml-auto p-1.5 rounded border border-border bg-panel text-text-secondary hover:text-text-primary hover:border-border-divider transition-colors"
        >
          <Keyboard size={16} />
        </button>
      </div>

      {!loading && variants.length > 0 && (
        <div className="flex items-center gap-3 mb-4 text-sm">
          <button
            onClick={toggleSelectAll}
            className="text-text-secondary hover:text-white transition-colors"
          >
            {allSelected ? "Clear selection" : "Select all"}
          </button>
          <span className="text-text-muted">·</span>
          <span className="text-text-secondary-alt">Drag a card's grip to reorder</span>
          {hasManualOrder && (
            <button
              onClick={resetOrder}
              title="Clear the manual order and restore the default"
              className="flex items-center gap-1 text-text-secondary hover:text-white transition-colors"
            >
              <ListRestart size={13} />
              Reset order
            </button>
          )}
          {selected.size > 0 && (
            <>
              <div className="h-4 w-px bg-panel-secondary" />
              <span className="text-text-secondary">{selected.size} selected</span>
              <BulkMove creatorId={numCreatorId} currentGroup={decodedCharacter} onMove={moveSelected} />
              <BulkSetImage onApply={setImageForSelected} />
              <BulkSetStoreLink onApply={setStoreUrlForSelected} />
              <button
                onClick={ungroupSelected}
                className="flex items-center gap-1 px-2.5 py-1 rounded bg-panel-secondary hover:bg-red-900/40 border border-border hover:border-red-600 text-text-secondary hover:text-red-400 transition-colors"
              >
                <X size={13} />
                Ungroup
              </button>
            </>
          )}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-24 text-text-secondary-alt text-sm">Loading…</div>
      ) : variants.length === 0 ? (
        <div className="flex justify-center py-24 text-text-secondary-alt text-sm">No variants found.</div>
      ) : (
        <DndContext
          sensors={dndSensors}
          collisionDetection={closestCenter}
          onDragStart={onReorderStart}
          onDragEnd={onReorderEnd}
          onDragCancel={() => setDraggingId(null)}
        >
          <SortableContext items={variants.map((v) => v.id)} strategy={rectSortingStrategy}>
            <div ref={gridRef} className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
              {variants.map((model, i) => (
                <SortableCard key={model.id} id={model.id}>
                  <div className="relative">
                    {/* Checkbox sits right of the drag grip (top-left). */}
                    <label className="absolute top-2 left-9 z-10 flex items-center justify-center p-1 rounded bg-panel/80 border border-border cursor-pointer">
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
                    moveToGroup={moveToGroup}
                    removeFromGroup={removeFromGroup}
                    onRemoved={removeVariant}
                    onMoved={removeVariant}
                    onRepChanged={reloadVariants}
                  />
                </SortableCard>
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} showSearch={false} />}
    </div>
  );
}

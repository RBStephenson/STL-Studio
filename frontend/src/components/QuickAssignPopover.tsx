import { useState, useEffect, useRef } from "react";
import { X, Tag, Layers, Check, Loader2, ImageOff, Pencil, Ungroup } from "lucide-react";
import { api, Collection } from "../api/client";
import { useToast } from "../context/ToastContext";

interface TagSuggestion {
  tag: string;
  count: number;
}

interface Props {
  modelId: number;
  initialTags: string[];
  allTags: TagSuggestion[];
  onTagsChange: (tags: string[]) => void;
  onClose: () => void;
  /** True when the model currently has a thumbnail — gates the Clear image action (#192). */
  hasImage?: boolean;
  /** Called after the thumbnail is cleared so the parent can drop the card image. */
  onImageCleared?: () => void;
  /** Opens the card's inline rename editor (#191). Omit to hide the Rename action. */
  onRename?: () => void;
}

export default function QuickAssignPopover({
  modelId,
  initialTags,
  allTags,
  onTagsChange,
  onClose,
  hasImage = false,
  onImageCleared,
  onRename,
}: Props) {
  const { toast } = useToast();
  const popoverRef = useRef<HTMLDivElement>(null);
  const tagInputRef = useRef<HTMLInputElement>(null);

  const [tags, setTags] = useState<string[]>(initialTags);
  const [tagInput, setTagInput] = useState("");
  const [tagDropdownOpen, setTagDropdownOpen] = useState(false);
  const [tagHighlighted, setTagHighlighted] = useState(0);

  const [collections, setCollections] = useState<Collection[]>([]);
  const [memberIds, setMemberIds] = useState<Set<number>>(new Set());
  const [loadingCollections, setLoadingCollections] = useState(true);
  const [savingTags, setSavingTags] = useState(false);
  const [togglingCollection, setTogglingCollection] = useState<number | null>(null);
  const [imageCleared, setImageCleared] = useState(false);
  const [clearingImage, setClearingImage] = useState(false);

  // Per-subtree grouping strategy (#618): the parent folder of this model.
  const [groupFolder, setGroupFolder] = useState<string | null>(null);
  const [groupStrategy, setGroupStrategy] = useState<"auto" | "off" | null>(null);
  const [savingStrategy, setSavingStrategy] = useState(false);

  // Load collections + current membership + grouping strategy on mount
  useEffect(() => {
    api.models.get(modelId)
      .then((detail) => {
        setMemberIds(new Set(detail.collection_ids ?? []));
        const parent = (detail.folder_path ?? "").replace(/\\/g, "/").replace(/\/+$/, "");
        const folder = parent.slice(0, parent.lastIndexOf("/"));
        if (folder) {
          setGroupFolder(folder);
          api.models.getGroupingStrategy(folder)
            .then((r) => setGroupStrategy(r.strategy))
            .catch(() => {});
        }
      })
      .catch(() => toast("Couldn't load model details.", "error"));
    api.collections.list()
      .then(setCollections)
      .catch(() => toast("Couldn't load collections.", "error"))
      .finally(() => setLoadingCollections(false));
  }, [modelId]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleGrouping = async () => {
    if (!groupFolder) return;
    const next = groupStrategy === "off" ? "auto" : "off";
    setSavingStrategy(true);
    try {
      await api.models.setGroupingStrategy(groupFolder, next);
      setGroupStrategy(next);
      toast(next === "off" ? "Auto-grouping off for this folder." : "Auto-grouping restored.", "success");
    } catch (e: any) {
      toast(e?.message || "Couldn't update grouping — try again.", "error");
    } finally {
      setSavingStrategy(false);
    }
  };

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  const filteredSuggestions = tagInput.trim()
    ? allTags.filter(
        (s) => s.tag.includes(tagInput.toLowerCase().trim()) && !tags.includes(s.tag)
      )
    : [];

  useEffect(() => { setTagHighlighted(0); }, [tagInput]);

  const saveTags = async (nextTags: string[]) => {
    setSavingTags(true);
    try {
      await api.models.update(modelId, { tags: nextTags });
      onTagsChange(nextTags);
    } catch {
      toast("Couldn't update tags — try again.", "error");
    } finally {
      setSavingTags(false);
    }
  };

  const addTag = (tag: string) => {
    const normalized = tag.trim().toLowerCase();
    if (!normalized || tags.includes(normalized)) return;
    const next = [...tags, normalized];
    setTags(next);
    saveTags(next);
    setTagInput("");
    setTagDropdownOpen(false);
    tagInputRef.current?.focus();
  };

  const removeTag = (tag: string) => {
    const next = tags.filter((t) => t !== tag);
    setTags(next);
    saveTags(next);
  };

  const handleTagKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      if (filteredSuggestions.length > 0 && tagDropdownOpen) {
        addTag(filteredSuggestions[tagHighlighted]?.tag ?? tagInput);
      } else if (tagInput.trim()) {
        addTag(tagInput);
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setTagHighlighted((h) => Math.min(h + 1, filteredSuggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setTagHighlighted((h) => Math.max(h - 1, 0));
    } else if (e.key === "Backspace" && !tagInput && tags.length > 0) {
      removeTag(tags[tags.length - 1]);
    } else if (e.key === "Escape") {
      setTagDropdownOpen(false);
    }
  };

  const clearImage = async () => {
    setClearingImage(true);
    try {
      await api.models.clearThumbnail(modelId);
      setImageCleared(true);
      onImageCleared?.();
      toast("Image cleared.", "success");
    } catch {
      toast("Couldn't clear the image — try again.", "error");
    } finally {
      setClearingImage(false);
    }
  };

  const toggleCollection = async (col: Collection) => {
    const isMember = memberIds.has(col.id);
    setTogglingCollection(col.id);
    try {
      if (isMember) {
        await api.collections.removeModel(col.id, modelId);
        setMemberIds((prev) => { const s = new Set(prev); s.delete(col.id); return s; });
      } else {
        await api.collections.addModel(col.id, modelId);
        setMemberIds((prev) => new Set([...prev, col.id]));
      }
    } catch {
      toast("Couldn't update collection — try again.", "error");
    } finally {
      setTogglingCollection(null);
    }
  };

  return (
    <div
      ref={popoverRef}
      className="absolute top-full right-0 mt-1 z-50 w-64 bg-gray-900 border border-gray-700 rounded-lg shadow-2xl"
      // stop clicks inside from bubbling to the Link
      onClick={(e) => e.preventDefault()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700">
        <span className="text-xs font-semibold text-gray-300 uppercase tracking-wide">Quick Assign</span>
        <button
          aria-label="Close quick assign"
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClose(); }}
          className="text-gray-500 hover:text-gray-200 transition-colors"
        >
          <X size={13} />
        </button>
      </div>

      {/* Rename action (#191) */}
      {onRename && (
        <div className="px-3 py-2 border-b border-gray-700/50">
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClose(); onRename(); }}
            className="flex items-center gap-2 w-full px-1.5 py-1 rounded text-xs text-left text-gray-300 hover:bg-gray-800 transition-colors"
          >
            <Pencil size={11} className="text-gray-400" />
            Rename
          </button>
        </div>
      )}

      {/* Tags section */}
      <div className="px-3 py-2 border-b border-gray-700/50">
        <div className="flex items-center gap-1.5 mb-2">
          <Tag size={11} className="text-gray-400" />
          <span className="text-xs text-gray-400 font-medium">Tags</span>
          {savingTags && <Loader2 size={10} className="text-gray-500 animate-spin ml-auto" />}
        </div>

        {/* Current tags */}
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {tags.map((tag) => (
              <span
                key={tag}
                className="flex items-center gap-1 bg-indigo-900/60 text-indigo-300 text-xs px-1.5 py-0.5 rounded-full"
              >
                {tag}
                <button
                  type="button"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); removeTag(tag); }}
                  className="hover:text-white"
                >
                  <X size={9} />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Tag input */}
        <div className="relative">
          <input
            ref={tagInputRef}
            type="text"
            value={tagInput}
            placeholder="Add tag…"
            onChange={(e) => { setTagInput(e.target.value); setTagDropdownOpen(true); }}
            onKeyDown={handleTagKeyDown}
            onFocus={() => tagInput && setTagDropdownOpen(true)}
            onClick={(e) => e.stopPropagation()}
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
          />
          {tagDropdownOpen && filteredSuggestions.length > 0 && (
            <div className="absolute z-10 top-full mt-0.5 w-full bg-gray-800 border border-gray-700 rounded shadow-xl overflow-hidden">
              {filteredSuggestions.slice(0, 8).map((s, i) => (
                <button
                  key={s.tag}
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); addTag(s.tag); }}
                  className={`w-full flex items-center justify-between px-2 py-1 text-xs text-left ${
                    i === tagHighlighted ? "bg-indigo-600 text-white" : "text-gray-300 hover:bg-gray-700"
                  }`}
                >
                  {s.tag}
                  <span className={`text-xs ${i === tagHighlighted ? "text-indigo-200" : "text-gray-600"}`}>
                    {s.count}×
                  </span>
                </button>
              ))}
              {tagInput.trim() && !filteredSuggestions.find((s) => s.tag === tagInput.trim().toLowerCase()) && (
                <button
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); addTag(tagInput); }}
                  className="w-full flex items-center gap-1.5 px-2 py-1 text-xs text-gray-400 hover:bg-gray-700 border-t border-gray-700"
                >
                  <span className="text-indigo-400">+</span>
                  Create "{tagInput.trim().toLowerCase()}"
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Collections section */}
      <div className="px-3 py-2">
        <div className="flex items-center gap-1.5 mb-2">
          <Layers size={11} className="text-gray-400" />
          <span className="text-xs text-gray-400 font-medium">Collections</span>
        </div>

        {loadingCollections ? (
          <div className="flex items-center justify-center py-2">
            <Loader2 size={14} className="text-gray-500 animate-spin" />
          </div>
        ) : collections.length === 0 ? (
          <p className="text-xs text-gray-600 py-1">No collections yet.</p>
        ) : (
          <div className="flex flex-col gap-0.5 max-h-32 overflow-y-auto">
            {collections.map((col) => {
              const isMember = memberIds.has(col.id);
              const toggling = togglingCollection === col.id;
              return (
                <button
                  key={col.id}
                  type="button"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleCollection(col); }}
                  disabled={toggling}
                  className="flex items-center gap-2 px-1.5 py-1 rounded text-xs text-left hover:bg-gray-800 transition-colors disabled:opacity-50"
                >
                  <span
                    className={`w-3.5 h-3.5 rounded border flex items-center justify-center flex-shrink-0 ${
                      isMember
                        ? "bg-indigo-500 border-indigo-400"
                        : "border-gray-600"
                    }`}
                  >
                    {isMember && <Check size={9} className="text-white" strokeWidth={3} />}
                  </span>
                  <span className={isMember ? "text-gray-200" : "text-gray-400"}>{col.name}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Grouping strategy (#618): stop/resume auto-grouping this folder */}
      {groupFolder && groupStrategy !== null && (
        <div className="px-3 py-2 border-t border-gray-700/50">
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleGrouping(); }}
            disabled={savingStrategy}
            title={`Folder: ${groupFolder}`}
            className="flex items-center gap-2 w-full px-1.5 py-1 rounded text-xs text-left text-gray-300 hover:bg-gray-800 transition-colors disabled:opacity-50"
          >
            {savingStrategy ? <Loader2 size={11} className="animate-spin" /> : <Ungroup size={11} className="text-gray-400" />}
            {groupStrategy === "off" ? "Resume auto-grouping this folder" : "Stop auto-grouping this folder"}
          </button>
        </div>
      )}

      {/* Image section (#192) */}
      {hasImage && !imageCleared && (
        <div className="px-3 py-2 border-t border-gray-700/50">
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); clearImage(); }}
            disabled={clearingImage}
            className="flex items-center gap-2 w-full px-1.5 py-1 rounded text-xs text-left text-rose-400 hover:bg-rose-900/30 transition-colors disabled:opacity-50"
          >
            {clearingImage ? <Loader2 size={11} className="animate-spin" /> : <ImageOff size={11} />}
            Clear image
          </button>
        </div>
      )}
    </div>
  );
}

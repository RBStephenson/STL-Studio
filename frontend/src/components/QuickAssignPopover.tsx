import { useState, useEffect, useRef } from "react";
import { X, Tag, Layers, Check, Loader2 } from "lucide-react";
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
}

export default function QuickAssignPopover({
  modelId,
  initialTags,
  allTags,
  onTagsChange,
  onClose,
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

  // Load collections + current membership on mount
  useEffect(() => {
    Promise.all([api.collections.list(), api.models.get(modelId)])
      .then(([cols, detail]) => {
        setCollections(cols);
        setMemberIds(new Set(detail.collection_ids ?? []));
      })
      .catch(() => toast("Couldn't load collections.", "error"))
      .finally(() => setLoadingCollections(false));
  }, [modelId]); // eslint-disable-line react-hooks/exhaustive-deps

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
      className="absolute bottom-full left-0 mb-1 z-50 w-64 bg-gray-900 border border-gray-700 rounded-lg shadow-2xl"
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
    </div>
  );
}

// Tag management for ModelDetail: user tags (inline editor), auto-detected tags,
// and hidden/suppressed auto-tags. Extracted from ModelDetail.tsx (STUDIO-63 P2)
// — behavior-preserving. Renders three sibling blocks; each self-hides when empty.

import { Fragment } from "react";
import { Link } from "react-router-dom";
import { Tag, Plus, X, ChevronDown, ChevronRight } from "lucide-react";
import TagInput from "../../../components/TagInput";

interface TagsPanelProps {
  tags: string[];
  autoTags: string[];
  removedAutoTags: string[];
  editingTags: boolean;
  tagSuggestions: { tag: string; count: number }[];
  showHiddenTags: boolean;
  onSetUserTags: (next: string[]) => void;
  onDoneEditing: () => void;
  onOpenEditor: () => void;
  onAdd: (tag: string) => void;
  onSuppress: (tag: string) => void;
  onRestore: (tag: string) => void;
  onToggleHidden: () => void;
}

export default function TagsPanel({
  tags,
  autoTags,
  removedAutoTags,
  editingTags,
  tagSuggestions,
  showHiddenTags,
  onSetUserTags,
  onDoneEditing,
  onOpenEditor,
  onAdd,
  onSuppress,
  onRestore,
  onToggleHidden,
}: TagsPanelProps) {
  const visibleAutoTags = autoTags.filter((t) => !removedAutoTags.includes(t));
  const hidden = autoTags.filter((t) => removedAutoTags.includes(t));

  return (
    <Fragment>
      {/* User tags — chips browse by tag; inline editor adds/removes
          without opening the full edit screen (#411) */}
      {editingTags ? (
        <div className="flex flex-col gap-1.5">
          <TagInput
            value={tags}
            onChange={onSetUserTags}
            suggestions={tagSuggestions}
          />
          <button
            onClick={onDoneEditing}
            className="text-xs text-gray-500 hover:text-gray-300 w-fit"
          >
            Done
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          {tags.map((tag) => (
            <Link
              key={tag}
              to={`/?tag=${encodeURIComponent(tag)}`}
              className="flex items-center gap-1 text-xs bg-gray-800 text-gray-400 hover:bg-indigo-950 hover:text-indigo-300 hover:border-indigo-700 border border-transparent px-2 py-1 rounded-full transition-colors"
            >
              <Tag size={10} />
              {tag}
            </Link>
          ))}
          <button
            onClick={onOpenEditor}
            title="Add or remove tags"
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-indigo-300 border border-dashed border-gray-700 hover:border-indigo-700 px-2 py-1 rounded-full transition-colors"
          >
            <Plus size={10} />
            {tags.length > 0 ? "Edit tags" : "Add tag"}
          </button>
        </div>
      )}

      {/* Auto-detected tags — click + to promote to a user tag, × to remove
          (suppressed tags survive rescans), click label to browse */}
      {visibleAutoTags.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs text-gray-600">Auto-detected · click + to add as tag · × to remove · click label to browse</p>
          <div className="flex flex-wrap gap-1.5">
            {visibleAutoTags.map((tag) => {
              const already = tags.includes(tag);
              return (
                <div key={tag} className="flex items-center rounded-full border overflow-hidden border-gray-700">
                  <button
                    onClick={() => onAdd(tag)}
                    disabled={already}
                    title={already ? "Already a tag" : "Add as user tag"}
                    className={`flex items-center px-1.5 py-0.5 text-xs border-r border-gray-700 transition-colors ${
                      already
                        ? "bg-indigo-900/30 text-indigo-500 cursor-default"
                        : "bg-gray-800/60 text-gray-500 hover:bg-indigo-950 hover:text-indigo-400"
                    }`}
                  >
                    {already ? <Tag size={9} /> : <Plus size={9} />}
                  </button>
                  <Link
                    to={`/?tag=${encodeURIComponent(tag)}`}
                    className="flex items-center px-2 py-0.5 text-xs bg-gray-800/60 text-gray-500 hover:bg-indigo-950 hover:text-indigo-300 transition-colors"
                  >
                    {tag}
                  </Link>
                  <button
                    onClick={() => onSuppress(tag)}
                    title="Remove this auto-detected tag"
                    className="flex items-center px-1.5 py-0.5 text-xs border-l border-gray-700 bg-gray-800/60 text-gray-600 hover:bg-rose-950 hover:text-rose-400 transition-colors"
                  >
                    <X size={9} />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Hidden (suppressed) auto-tags — restore any that the scanner still
          detects. Only shows tags currently in auto_tags so restoring is
          guaranteed to bring the chip back. */}
      {hidden.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <button
            onClick={onToggleHidden}
            className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 transition-colors w-fit"
          >
            {showHiddenTags ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            {hidden.length} hidden auto-{hidden.length === 1 ? "tag" : "tags"}
          </button>
          {showHiddenTags && (
            <div className="flex flex-wrap gap-1.5">
              {hidden.map((tag) => (
                <button
                  key={tag}
                  onClick={() => onRestore(tag)}
                  title="Restore this auto-detected tag"
                  className="flex items-center gap-1 rounded-full border border-gray-800 px-2 py-0.5 text-xs bg-gray-900/60 text-gray-600 line-through hover:no-underline hover:border-emerald-800 hover:bg-emerald-950 hover:text-emerald-400 transition-colors"
                >
                  <Plus size={9} />
                  {tag}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </Fragment>
  );
}

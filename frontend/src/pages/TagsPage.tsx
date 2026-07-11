import { useState, useEffect } from "react";
import { Tag, Pencil, GitMerge, Trash2, Check, X, Loader2, Search, Filter } from "lucide-react";
import { api } from "../api/client";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import HelpLink from "../components/HelpLink";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import { SkeletonBlock, SkeletonPanel } from "../components/SkeletonBlock";

interface TagRow {
  tag: string;
  count: number;
}

export default function TagsPage() {
  const { toast } = useToast();
  const confirm = useConfirm();
  const [tags, setTags] = useState<TagRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);

  const [merging, setMerging] = useState<string | null>(null);
  const [mergeTarget, setMergeTarget] = useState("");
  const [mergeSaving, setMergeSaving] = useState(false);

  const [deleting, setDeleting] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api.models.tags()
      .then(setTags)
      .catch((e) => setError(e?.message || "Could not load tags."))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const filtered = search.trim()
    ? tags.filter((t) => t.tag.includes(search.trim().toLowerCase()))
    : tags;

  const startRename = (tag: string) => {
    setRenaming(tag);
    setRenameValue(tag);
    setMerging(null);
  };

  const cancelRename = () => { setRenaming(null); setRenameValue(""); };

  const submitRename = async (oldTag: string) => {
    const newTag = renameValue.trim().toLowerCase();
    if (!newTag || newTag === oldTag) { cancelRename(); return; }
    setRenameSaving(true);
    try {
      const res = await api.models.renameTag(oldTag, newTag);
      toast(`Renamed "${oldTag}" → "${newTag}" on ${res.updated} model(s).`, "success");
      cancelRename();
      load();
    } catch {
      toast("Couldn't rename tag — try again.", "error");
    } finally {
      setRenameSaving(false);
    }
  };

  const startMerge = (tag: string) => {
    setMerging(tag);
    setMergeTarget("");
    setRenaming(null);
  };

  const cancelMerge = () => { setMerging(null); setMergeTarget(""); };

  const submitMerge = async (sourceTag: string) => {
    const target = mergeTarget.trim().toLowerCase();
    if (!target || target === sourceTag) { cancelMerge(); return; }
    const ok = await confirm({
      title: "Merge tags?",
      message: `All models tagged "${sourceTag}" will also get "${target}", and "${sourceTag}" will be removed. This cannot be undone.`,
      confirmLabel: "Merge",
      destructive: true,
    });
    if (!ok) return;
    setMergeSaving(true);
    try {
      const res = await api.models.mergeTag(sourceTag, target);
      toast(`Merged "${sourceTag}" into "${target}" on ${res.updated} model(s).`, "success");
      cancelMerge();
      load();
    } catch {
      toast("Couldn't merge tags — try again.", "error");
    } finally {
      setMergeSaving(false);
    }
  };

  const deleteTag = async (tag: string, count: number) => {
    const ok = await confirm({
      title: `Delete tag "${tag}"?`,
      message: `This will remove "${tag}" from ${count} model(s). This cannot be undone.`,
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    setDeleting(tag);
    try {
      const res = await api.models.deleteTag(tag);
      toast(`Removed "${tag}" from ${res.updated} model(s).`, "success");
      load();
    } catch {
      toast("Couldn't delete tag — try again.", "error");
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Tag size={22} className="text-indigo-400" />
          <h1 className="text-2xl font-bold text-white">Tag Management</h1>
          <HelpLink section="tags" />
        </div>
        <span className="text-sm text-text-secondary-alt">{tags.length} tags</span>
      </div>

      <div className="relative mb-4">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary-alt pointer-events-none" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter tags…"
          className="w-full pl-8 pr-3 py-2 bg-panel-secondary border border-border rounded-lg text-sm text-text-primary placeholder-gray-600 focus:outline-none focus:border-accent-start"
        />
      </div>

      {loading ? (
        <SkeletonPanel className="flex flex-col gap-1" data-testid="tags-loading-skeleton">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-panel-secondary">
              <SkeletonBlock className="h-3.5 w-24" />
              <SkeletonBlock className="h-3 w-16" />
            </div>
          ))}
        </SkeletonPanel>
      ) : error ? (
        <ErrorState
          title="Couldn't load tags"
          message="Something went wrong reading your tag index. Try again."
          onRetry={load}
        />
      ) : filtered.length === 0 ? (
        search ? (
          <EmptyState
            icon={Filter}
            heading={`No tags match "${search}"`}
            body="Try a different filter term, or clear it to see all tags."
            secondaryAction={{ label: "Clear filter", onClick: () => setSearch("") }}
          />
        ) : (
          <p className="text-center text-text-secondary-alt py-16">No tags found.</p>
        )
      ) : (
        <div className="flex flex-col gap-1">
          {filtered.map((row) => {
            const isRenaming = renaming === row.tag;
            const isMerging = merging === row.tag;
            const isDeleting = deleting === row.tag;
            const otherTags = tags.filter((t) => t.tag !== row.tag);

            return (
              <div
                key={row.tag}
                className="bg-panel border border-border-subtle rounded-lg px-4 py-3"
              >
                {/* Main row */}
                <div className="flex items-center gap-3">
                  <span className="flex-1 font-mono text-sm text-text-primary-alt">{row.tag}</span>
                  <span className="text-xs text-text-secondary-alt tabular-nums w-16 text-right">
                    {row.count} {row.count === 1 ? "model" : "models"}
                  </span>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => isRenaming ? cancelRename() : startRename(row.tag)}
                      title="Rename"
                      aria-label={`Rename tag ${row.tag}`}
                      className={`p-1.5 rounded transition-colors ${
                        isRenaming ? "text-indigo-400 bg-indigo-900/30" : "text-text-secondary-alt hover:text-indigo-300 hover:bg-panel-secondary"
                      }`}
                    >
                      <Pencil size={13} />
                    </button>
                    <button
                      onClick={() => isMerging ? cancelMerge() : startMerge(row.tag)}
                      title="Merge into another tag"
                      aria-label={`Merge tag ${row.tag}`}
                      className={`p-1.5 rounded transition-colors ${
                        isMerging ? "text-amber-400 bg-amber-900/20" : "text-text-secondary-alt hover:text-amber-300 hover:bg-panel-secondary"
                      }`}
                    >
                      <GitMerge size={13} />
                    </button>
                    <button
                      onClick={() => deleteTag(row.tag, row.count)}
                      disabled={isDeleting}
                      title="Delete"
                      aria-label={`Delete tag ${row.tag}`}
                      className="p-1.5 rounded text-text-secondary-alt hover:text-red-400 hover:bg-panel-secondary transition-colors disabled:opacity-40"
                    >
                      {isDeleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                    </button>
                  </div>
                </div>

                {/* Rename form */}
                {isRenaming && (
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      type="text"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") submitRename(row.tag);
                        if (e.key === "Escape") cancelRename();
                      }}
                      autoFocus
                      placeholder="New tag name…"
                      className="flex-1 bg-panel-secondary border border-border-divider rounded px-2.5 py-1.5 text-sm text-text-primary focus:outline-none focus:border-accent-start"
                    />
                    <button
                      onClick={() => submitRename(row.tag)}
                      disabled={renameSaving || !renameValue.trim()}
                      aria-label="Confirm rename"
                      className="p-1.5 rounded bg-accent-end hover:bg-accent-start text-white disabled:opacity-40 transition-colors"
                    >
                      {renameSaving ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                    </button>
                    <button onClick={cancelRename} aria-label="Cancel rename" className="p-1.5 rounded text-text-secondary-alt hover:text-text-primary-alt transition-colors">
                      <X size={13} />
                    </button>
                  </div>
                )}

                {/* Merge form */}
                {isMerging && (
                  <div className="mt-2 flex items-center gap-2">
                    <select
                      value={mergeTarget}
                      onChange={(e) => setMergeTarget(e.target.value)}
                      className="flex-1 bg-panel-secondary border border-border-divider rounded px-2.5 py-1.5 text-sm text-text-primary focus:outline-none focus:border-amber-500"
                    >
                      <option value="">Merge into…</option>
                      {otherTags.map((t) => (
                        <option key={t.tag} value={t.tag}>{t.tag} ({t.count})</option>
                      ))}
                    </select>
                    <button
                      onClick={() => submitMerge(row.tag)}
                      disabled={mergeSaving || !mergeTarget}
                      aria-label="Confirm merge"
                      className="p-1.5 rounded bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-40 transition-colors"
                    >
                      {mergeSaving ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                    </button>
                    <button onClick={cancelMerge} aria-label="Cancel merge" className="p-1.5 rounded text-text-secondary-alt hover:text-text-primary-alt transition-colors">
                      <X size={13} />
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

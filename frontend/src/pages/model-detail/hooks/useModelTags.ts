// Tag state + handlers for the ModelDetail page: user tags, suppressed
// auto-tags, the inline editor, and lazily-loaded tag suggestions. Extracted
// from ModelDetail.tsx (STUDIO-63 P3) — behavior-preserving. All mutations are
// optimistic-local with revert on failure, matching the original inline logic.

import { useState, useEffect } from "react";
import { api, ModelDetail as ModelDetailType } from "../../../api/client";
import { useToast } from "../../../context/ToastContext";

export interface UseModelTags {
  tags: string[];
  removedAutoTags: string[];
  showHiddenTags: boolean;
  editingTags: boolean;
  tagSuggestions: { tag: string; count: number }[];
  addTag: (tag: string) => Promise<void>;
  setUserTags: (next: string[]) => Promise<void>;
  openTagEditor: () => void;
  doneEditing: () => void;
  toggleHidden: () => void;
  suppressAutoTag: (tag: string) => Promise<void>;
  restoreAutoTag: (tag: string) => Promise<void>;
}

export function useModelTags(model: ModelDetailType | null, modelId: number | undefined): UseModelTags {
  const { toast } = useToast();
  const [tags, setTags] = useState<string[]>([]);
  const [removedAutoTags, setRemovedAutoTags] = useState<string[]>([]);
  const [showHiddenTags, setShowHiddenTags] = useState(false);
  const [editingTags, setEditingTags] = useState(false);
  const [tagSuggestions, setTagSuggestions] = useState<{ tag: string; count: number }[]>([]);

  // Sync local tag state from the loaded model.
  useEffect(() => {
    if (model) {
      setTags(model.tags ?? []);
      setRemovedAutoTags(model.removed_auto_tags ?? []);
    }
  }, [model]);

  // Reset UI-only tag state when navigating to a different model.
  useEffect(() => {
    setShowHiddenTags(false);
    setEditingTags(false);
  }, [modelId]);

  const addTag = async (tag: string) => {
    if (tags.includes(tag)) return;
    const prev = tags;
    const next = [...tags, tag];
    setTags(next);
    try {
      await api.models.update(Number(modelId), { tags: next });
    } catch {
      setTags(prev);  // revert on failure
      toast("Couldn't add tag — try again.", "error");
    }
  };

  // Replace the full user-tag set (inline editor add/remove). Optimistic with
  // revert, mirroring addTag.
  const setUserTags = async (next: string[]) => {
    const prev = tags;
    setTags(next);
    try {
      await api.models.update(Number(modelId), { tags: next });
    } catch {
      setTags(prev);  // revert on failure
      toast("Couldn't update tags — try again.", "error");
    }
  };

  // Open the inline tag editor, lazily loading tag suggestions on first use.
  const openTagEditor = () => {
    setEditingTags(true);
    if (tagSuggestions.length === 0) {
      api.models.tags().then(setTagSuggestions).catch(() => {});
    }
  };

  // Suppress an auto-detected tag so it stops showing and survives rescans.
  // If it was already promoted to a user tag, drop that too.
  const suppressAutoTag = async (tag: string) => {
    const prevRemoved = removedAutoTags;
    const prevTags = tags;
    const nextRemoved = removedAutoTags.includes(tag) ? removedAutoTags : [...removedAutoTags, tag];
    const nextTags = tags.filter((t) => t !== tag);
    setRemovedAutoTags(nextRemoved);
    setTags(nextTags);
    try {
      await api.models.update(Number(modelId), { removed_auto_tags: nextRemoved, tags: nextTags });
    } catch {
      setRemovedAutoTags(prevRemoved);  // revert on failure
      setTags(prevTags);
      toast("Couldn't remove tag — try again.", "error");
    }
  };

  // Un-suppress a previously removed auto-tag so it reappears as auto-detected.
  const restoreAutoTag = async (tag: string) => {
    const prevRemoved = removedAutoTags;
    const nextRemoved = removedAutoTags.filter((t) => t !== tag);
    setRemovedAutoTags(nextRemoved);
    try {
      await api.models.update(Number(modelId), { removed_auto_tags: nextRemoved });
    } catch {
      setRemovedAutoTags(prevRemoved);  // revert on failure
      toast("Couldn't restore tag — try again.", "error");
    }
  };

  return {
    tags,
    removedAutoTags,
    showHiddenTags,
    editingTags,
    tagSuggestions,
    addTag,
    setUserTags,
    openTagEditor,
    doneEditing: () => setEditingTags(false),
    toggleHidden: () => setShowHiddenTags((s) => !s),
    suppressAutoTag,
    restoreAutoTag,
  };
}

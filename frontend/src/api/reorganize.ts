import { request } from "./base";
import type {
  ReorganizeAiSuggestResult,
  ReorganizeApplyResult,
  ReorganizeOverride,
  ReorganizePreview,
  ReorganizeUndoResult,
} from "./types";

export const reorganizeApi = {
  preview: (template?: string, rootId?: number) => {
    const p = new URLSearchParams();
    if (template) p.set("template", template);
    if (rootId != null) p.set("root_id", String(rootId));
    const qs = p.toString();
    return request<ReorganizePreview>(`/reorganize/preview${qs ? `?${qs}` : ""}`);
  },
  previewWithOverrides: (body: {
    template?: string;
    root_id?: number;
    overrides: Record<number, ReorganizeOverride>;
  }) =>
    request<ReorganizePreview>("/reorganize/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  apply: (manifest_id: string, entry_ids: number[]) =>
    request<ReorganizeApplyResult>("/reorganize/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manifest_id, entry_ids }),
    }),
  undo: (manifest_id: string) =>
    request<ReorganizeUndoResult>("/reorganize/undo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manifest_id }),
    }),
  aiSuggest: (manifest_id: string, model_ids: number[]) =>
    request<ReorganizeAiSuggestResult>("/reorganize/ai-suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manifest_id, model_ids }),
    }),
};

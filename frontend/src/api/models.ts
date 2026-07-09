import { request, BASE } from "./base";
import type {
  AiOrganizePreviewResult,
  AiOrganizeResult,
  AiOrganizeStrategy,
  AiOrganizeSuggestion,
  Creator,
  ModelDetail,
  ModelList,
  ModelStats,
  PrintStatus,
  VariantGroup,
} from "./types";

export const modelsApi = {
  list: (params: Record<string, string | number | boolean>) => {
    const qs = new URLSearchParams(
      Object.entries(params)
        .filter(([, v]) => v !== "" && v !== undefined && v !== null)
        .map(([k, v]) => [k, String(v)])
    ).toString();
    return request<ModelList>(`/models${qs ? `?${qs}` : ""}`);
  },
  get: (id: number) => request<ModelDetail>(`/models/${id}`),
  stats: () => request<ModelStats>("/models/stats"),
  creators: () => request<Creator[]>("/models/creators/list"),
  createCreator: (name: string, source_url?: string) =>
    request<Creator>("/models/creators", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, source_url: source_url || null }),
    }),
  tags: () => request<{ tag: string; count: number }[]>("/models/tags/all"),
  renameTag: (oldTag: string, newTag: string) =>
    request<{ ok: boolean; updated: number }>("/models/tags/rename", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_tag: oldTag, new_tag: newTag }),
    }),
  mergeTag: (sourceTag: string, targetTag: string) =>
    request<{ ok: boolean; updated: number }>("/models/tags/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_tag: sourceTag, target_tag: targetTag }),
    }),
  deleteTag: async (tag: string) => {
    const res = await fetch(`${BASE}/models/tags/${encodeURIComponent(tag)}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json() as Promise<{ ok: boolean; updated: number }>;
  },
  update: (id: number, body: Record<string, unknown>) =>
    request<{ ok: boolean }>(`/models/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  setGroupRep: (id: number, isGroupRep: boolean) =>
    request<{ ok: boolean; is_group_rep: boolean }>(`/models/${id}/group-rep`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_group_rep: isGroupRep }),
    }),
  setThumbnail: (id: number, body: { thumbnail_path?: string | null; thumbnail_url?: string | null }) =>
    request<{ ok: boolean }>(`/models/${id}/thumbnail`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  clearThumbnail: (id: number) =>
    request<{ ok: boolean }>(`/models/${id}/thumbnail`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thumbnail_path: null, thumbnail_url: null }),
    }),
  // Re-syncs image_paths with what's actually in the model's folder — picks up
  // files placed there manually, drops entries for files no longer on disk.
  refreshGallery: (id: number) =>
    request<{ ok: boolean; image_paths: string[]; thumbnail_path: string | null }>(
      `/models/${id}/images/refresh`,
      { method: "POST" },
    ),
  deleteOtherFile: (id: number, path: string) =>
    request<{ ok: boolean }>(`/models/${id}/other-files`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  uploadGalleryImages: async (id: number, files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    const res = await fetch(`${BASE}/models/${id}/images/upload`, { method: "POST", body: form });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new Error(data?.detail ?? `${res.status} ${res.statusText}`);
    }
    return res.json() as Promise<{ ok: boolean; image_paths: string[]; thumbnail_path: string | null }>;
  },
  setNSFW: (id: number, nsfw: boolean) =>
    request<{ ok: boolean }>(`/models/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nsfw }),
    }),
  setFavorite: (id: number, is_favorite: boolean) =>
    request<{ ok: boolean; is_favorite: boolean }>(`/models/${id}/favorite`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_favorite }),
    }),
  setRating: (id: number, rating: number | null) =>
    request<{ ok: boolean; user_rating: number | null }>(`/models/${id}/rating`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating }),
    }),
  reorderQueue: (ids: number[]) =>
    request<{ ok: boolean; updated: number }>("/models/queue/reorder", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    }),
  setExcluded: (id: number, excluded: boolean) =>
    request<{ ok: boolean; excluded: boolean }>(`/models/${id}/exclude`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ excluded }),
    }),
  setPrintStatus: (id: number, status: PrintStatus) =>
    request<{ ok: boolean; print_status: PrintStatus; print_count: number }>(`/models/${id}/print-status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }),
  bulkTag: (ids: number[], addTags: string[], removeTags: string[]) =>
    request<{ ok: boolean; updated: number }>("/models/bulk", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, add_tags: addTags, remove_tags: removeTags }),
    }),
  bulkExclude: (ids: number[], excluded: boolean) =>
    request<{ ok: boolean; updated: number }>("/models/bulk/exclude", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, excluded }),
    }),
  bulkReview: (ids: number[], needs_review: boolean) =>
    request<{ ok: boolean; updated: number }>("/models/bulk/review", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, needs_review }),
    }),
  bulkEnrich: (
    ids: number[],
    fields: { creator_name?: string; title?: string; notes?: string; source_url?: string; source_site?: string },
  ) =>
    request<{ ok: boolean; updated: number }>("/models/bulk/enrich", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, ...fields }),
    }),
  bulkDelete: (ids: number[], deleteFiles: boolean) =>
    request<{ deleted: number; folders_removed: number }>("/models/bulk", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, delete_files: deleteFiles }),
    }),
  characters: (creatorId: number) =>
    request<string[]>(`/models/characters?creator_id=${creatorId}`),
  variants: (creatorId: number, character: string, groupId?: number | null) => {
    if (groupId) {
      return request<ModelList>(`/models/variants?group_id=${groupId}`);
    }
    return request<ModelList>(`/models/variants?creator_id=${creatorId}&character=${encodeURIComponent(character)}`);
  },
  splitPack: (id: number) =>
    request<{ ok: boolean; created: number; message: string }>(`/models/${id}/split`, {
      method: "POST",
    }),
  // Manual variant groups (#617): merge selected models, split members out,
  // relabel / set rep.
  mergeGroup: (modelIds: number[], opts: { groupId?: number; label?: string } = {}) =>
    request<VariantGroup>("/models/groups/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_ids: modelIds, group_id: opts.groupId, label: opts.label }),
    }),
  splitGroup: (groupId: number, modelIds: number[]) =>
    request<{ ok: boolean; removed: number[] }>(`/models/groups/${groupId}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_ids: modelIds }),
    }),
  patchGroup: (groupId: number, body: { label?: string; rep_model_id?: number }) =>
    request<VariantGroup>(`/models/groups/${groupId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // Per-subtree grouping strategy (#618): "off" stops auto-grouping a folder,
  // "auto" restores it.
  getGroupingStrategy: (path: string) =>
    request<{ path: string; strategy: "auto" | "off" }>(
      `/models/grouping-strategy?path=${encodeURIComponent(path)}`,
    ),
  setGroupingStrategy: (path: string, strategy: "auto" | "off") =>
    request<{ ok: boolean; path: string; strategy: string }>("/models/grouping-strategy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, strategy }),
    }),
  // Persist a manual model order within a variant group (#399). Empty `ids`
  // resets the group to its heuristic order.
  reorderGroup: (creatorId: number, character: string, ids: number[], groupId?: number | null) =>
    request<{ ok: boolean; reset: boolean; updated: number }>(`/models/group/reorder`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ creator_id: creatorId, character, group_id: groupId, ids }),
    }),
  updateSTLFile: (fileId: number, body: Record<string, unknown>) =>
    request<{ ok: boolean }>(`/models/stl-files/${fileId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  aiOrganize: (modelId: number, strategy: AiOrganizeStrategy = "parts") =>
    request<AiOrganizePreviewResult>(`/models/${modelId}/ai-organize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ strategy }),
    }),
  aiOrganizeApply: (modelId: number, items: AiOrganizeSuggestion[]) =>
    request<AiOrganizeResult>(`/models/${modelId}/ai-organize/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }),
  batchThumbnailFromUrl: (modelIds: number[], url: string) =>
    request<{ ok: boolean; downloaded: boolean; detail?: string; updated: number[]; missing: number[] }>(
      `/models/group/thumbnail/from-url`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_ids: modelIds, url }),
      },
    ),
  neighbors: (id: number, params: Record<string, string | number | boolean>) => {
    const qs = new URLSearchParams(
      Object.entries(params)
        .filter(([, v]) => v !== "" && v !== undefined && v !== null)
        .map(([k, v]) => [k, String(v)])
    ).toString();
    return request<{ prev_id: number | null; next_id: number | null }>(
      `/models/${id}/neighbors${qs ? `?${qs}` : ""}`
    );
  },
};

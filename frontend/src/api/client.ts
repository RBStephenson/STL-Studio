const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    let detail: string | undefined;
    try { detail = (await res.json()).detail; } catch { /* ignore */ }
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface Model {
  id: number;
  name: string;
  title: string | null;
  description: string | null;
  notes: string | null;
  character: string | null;
  variant_count?: number;
  folder_path: string;
  native_folder_path: string | null;
  source_url: string | null;
  source_site: string | null;
  license: string | null;
  tags: string[];
  auto_tags: string[];
  category: string | null;
  needs_review: boolean;
  nsfw: boolean;
  excluded: boolean;
  is_favorite: boolean;
  in_queue: boolean;
  queued_at: string | null;
  printed_at: string | null;
  thumbnail_path: string | null;
  thumbnail_url: string | null;
  image_paths: string[];
  rating: number | null;
  download_count: number | null;
  creator_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ModelStats {
  total: number;
  needs_review: number;
  no_thumbnail: number;
  favorites: number;
  queued: number;
  printed: number;
  excluded: number;
}

export interface STLFile {
  id: number;
  path: string;
  filename: string;
  size_bytes: number | null;
  part_type: string | null;
}

export interface ModelDetail extends Model {
  stl_files: STLFile[];
  creator: { id: number; name: string; source_url: string | null } | null;
  collection_ids: number[];
  has_group_override: boolean;
  group_override: string | null;
}

export interface ModelList {
  total: number;
  page: number;
  page_size: number;
  items: Model[];
}

export interface Creator {
  id: number;
  name: string;
  source_url: string | null;
  model_count: number;
}

export interface ScanRoot {
  id: number;
  path: string;
  enabled: boolean;
  layout: string;
  last_scanned: string | null;
}

export interface DirEntry {
  name: string;
  path: string;
}

export interface DirListing {
  path: string;
  parent: string | null;
  is_drive_list: boolean;
  entries: DirEntry[];
}

export interface ScanStatus {
  running: boolean;
  message: string;
  models_found: number | null;
  files_found: number | null;
  cancelled: boolean;
}

export interface Collection {
  id: number;
  name: string;
  description: string | null;
  cover_image_path: string | null;
  model_count: number;
  created_at: string;
}

export interface ScrapePreview {
  title: string | null;
  description: string | null;
  source_url: string | null;
  source_site: string | null;
  external_id: string | null;
  creator_name: string | null;
  thumbnail_url: string | null;
  image_urls: string[];
  tags: string[];
  category: string | null;
  license: string | null;
  like_count: number | null;
  download_count: number | null;
}

export const api = {
  models: {
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
    tags: () => request<{ tag: string; count: number }[]>("/models/tags/all"),
    update: (id: number, body: Record<string, unknown>) =>
      request<{ ok: boolean }>(`/models/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
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
    setQueue: (id: number, in_queue: boolean) =>
      request<{ ok: boolean; in_queue: boolean }>(`/models/${id}/queue`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ in_queue }),
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
    setPrinted: (id: number, printed: boolean) =>
      request<{ ok: boolean; printed_at: string | null }>(`/models/${id}/printed`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ printed }),
      }),
    bulkTag: (ids: number[], addTags: string[], removeTags: string[]) =>
      request<{ ok: boolean; updated: number }>("/models/bulk", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, add_tags: addTags, remove_tags: removeTags }),
      }),
    characters: (creatorId: number) =>
      request<string[]>(`/models/characters?creator_id=${creatorId}`),
    variants: (creatorId: number, character: string) =>
      request<ModelList>(`/models/variants?creator_id=${creatorId}&character=${encodeURIComponent(character)}`),
    splitPack: (id: number) =>
      request<{ ok: boolean; created: number; message: string }>(`/models/${id}/split`, {
        method: "POST",
      }),
    setGroupOverride: (id: number, character: string | null) =>
      request<{ ok: boolean; character: string | null }>(`/models/${id}/set-group`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character }),
      }),
    clearGroupOverride: (id: number) =>
      request<{ ok: boolean; deleted: boolean }>(`/models/${id}/set-group`, {
        method: "DELETE",
      }),
    updateSTLFile: (fileId: number, body: Record<string, unknown>) =>
      request<{ ok: boolean }>(`/models/stl-files/${fileId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
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
  },
  files: {
    openFolder: (path: string) =>
      request<{ ok: boolean }>(`/files/open-folder?path=${encodeURIComponent(path)}`),
  },
  scrape: {
    fetchUrl: (url: string) =>
      request<ScrapePreview>(`/scrape/fetch?url=${encodeURIComponent(url)}`),
    applyMetadata: (modelId: number, body: Partial<ScrapePreview>) =>
      request<{ ok: boolean }>(`/scrape/apply/${modelId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
  },
  scan: {
    start: () => request<ScanStatus>("/scan/start", { method: "POST" }),
    startCreator: (creatorId: number) =>
      request<ScanStatus>(`/scan/creator/${creatorId}`, { method: "POST" }),
    cancel: () => request<{ ok: boolean }>("/scan/cancel", { method: "POST" }),
    status: () => request<ScanStatus>("/scan/status"),
    browse: (path?: string) =>
      request<DirListing>(`/scan/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),
    roots: () => request<ScanRoot[]>("/scan/roots"),
    addRoot: (path: string, layout?: string) =>
      request<ScanRoot>("/scan/roots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, layout: layout || "{creator}" }),
      }),
    updateRoot: (id: number, body: { layout?: string; enabled?: boolean }) =>
      request<ScanRoot>(`/scan/roots/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    removeRoot: (id: number) =>
      request<{ ok: boolean }>(`/scan/roots/${id}`, { method: "DELETE" }),
  },
  database: {
    backup: async () => {
      const res = await fetch(`${BASE}/database/backup`);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `stl_inventory_backup_${stamp}.db`;
      a.click();
      URL.revokeObjectURL(url);
    },
    restore: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${BASE}/database/restore`, { method: "POST", body: form });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
        throw new Error(detail);
      }
      return res.json() as Promise<{ ok: boolean }>;
    },
    reset: async () => {
      const res = await fetch(`${BASE}/database/reset`, { method: "POST" });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
        throw new Error(detail);
      }
      return res.json() as Promise<{ ok: boolean }>;
    },
  },
  collections: {
    list: () => request<Collection[]>("/collections"),
    create: (name: string, description?: string) =>
      request<Collection>("/collections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description }),
      }),
    getModels: (collectionId: number) =>
      request<Model[]>(`/collections/${collectionId}/models`),
    addModel: async (collectionId: number, modelId: number) => {
      const res = await fetch(`${BASE}/collections/${collectionId}/models/${modelId}`, { method: "POST" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    },
    removeModel: async (collectionId: number, modelId: number) => {
      const res = await fetch(`${BASE}/collections/${collectionId}/models/${modelId}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    },
    update: (collectionId: number, body: { name?: string; description?: string }) =>
      request<Collection>(`/collections/${collectionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    delete: async (collectionId: number) => {
      const res = await fetch(`${BASE}/collections/${collectionId}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    },
    bulkAddModels: async (collectionId: number, modelIds: number[]) => {
      await Promise.all(modelIds.map((id) => {
        return fetch(`${BASE}/collections/${collectionId}/models/${id}`, { method: "POST" });
      }));
    },
  },
  fileUrl: (path: string) => `/api/files/image?path=${encodeURIComponent(path)}`,
  stlUrl: (path: string) => `/api/files/stl?path=${encodeURIComponent(path)}`,
  downloadZip: async (fileIds: number[], zipName: string) => {
    const res = await fetch(`${BASE}/files/download-zip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_ids: fileIds, zip_name: zipName }),
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = zipName + ".zip";
    a.click();
    URL.revokeObjectURL(url);
  },
};

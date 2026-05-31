const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
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
  is_favorite: boolean;
  in_queue: boolean;
  queued_at: string | null;
  printed_at: string | null;
  thumbnail_path: string | null;
  thumbnail_url: string | null;
  image_paths: string[];
  rating: number | null;
  download_count: number | null;
  orynt3d_parsed: boolean;
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
    variants: (creatorId: number, character: string) =>
      request<ModelList>(`/models/variants?creator_id=${creatorId}&character=${encodeURIComponent(character)}`),
    updateSTLFile: (fileId: number, body: Record<string, unknown>) =>
      request<{ ok: boolean }>(`/models/stl-files/${fileId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
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
    addRoot: (path: string) =>
      request<ScanRoot>("/scan/roots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      }),
    removeRoot: (id: number) =>
      request<{ ok: boolean }>(`/scan/roots/${id}`, { method: "DELETE" }),
  },
  collections: {
    list: () => request<Collection[]>("/collections"),
    create: (name: string, description?: string) =>
      request<Collection>("/collections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description }),
      }),
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

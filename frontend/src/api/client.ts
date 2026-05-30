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
  character: string | null;
  variant_count?: number;
  folder_path: string;
  source_url: string | null;
  source_site: string | null;
  license: string | null;
  tags: string[];
  auto_tags: string[];
  category: string | null;
  needs_review: boolean;
  nsfw: boolean;
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
  scan: {
    start: () => request<ScanStatus>("/scan/start", { method: "POST" }),
    cancel: () => request<{ ok: boolean }>("/scan/cancel", { method: "POST" }),
    status: () => request<ScanStatus>("/scan/status"),
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

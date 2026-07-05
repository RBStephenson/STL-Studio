import { request, BASE } from "./base";
import type { Collection, Model } from "./types";

export const collectionsApi = {
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
  update: (collectionId: number, body: { name?: string; description?: string | null }) =>
    request<Collection>(`/collections/${collectionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  delete: async (collectionId: number) => {
    const res = await fetch(`${BASE}/collections/${collectionId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  },
  // Reuses addModel so each POST's res.ok is checked — a non-2xx rejects the
  // whole call rather than silently reporting success (#STUDIO-91). Callers wrap
  // this in try/catch and surface the failure.
  bulkAddModels: async (collectionId: number, modelIds: number[]) => {
    await Promise.all(
      modelIds.map((id) => collectionsApi.addModel(collectionId, id)),
    );
  },
  setCoverFromUrl: (collectionId: number, url: string) =>
    request<Collection>(`/collections/${collectionId}/cover/from-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  setCoverFromModel: (collectionId: number, modelId: number) =>
    request<Collection>(`/collections/${collectionId}/cover/from-model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId }),
    }),
  uploadCover: async (collectionId: number, file: File): Promise<Collection> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/collections/${collectionId}/cover/upload`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status} ${text}`);
    }
    return res.json();
  },
  clearCover: (collectionId: number) =>
    request<Collection>(`/collections/${collectionId}/cover`, { method: "DELETE" }),
};

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
};

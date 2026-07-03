import { request } from "./base";
import type {
  AiSettings,
  AppSettings,
  CultsSettings,
  EnvReloadResult,
  FilterPreset,
  MmfSettings,
} from "./types";

export const settingsApi = {
  get: () => request<AppSettings>("/settings"),
  update: (patch: Partial<AppSettings>) =>
    request<AppSettings>("/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  // Single-preset writes go through dedicated endpoints so the server does the
  // read-modify-write against the stored list — a stale client snapshot can't
  // drop unrelated presets (#287).
  upsertPreset: (preset: FilterPreset) =>
    request<AppSettings>("/settings/filter-presets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(preset),
    }),
  deletePreset: (name: string) =>
    request<AppSettings>(`/settings/filter-presets?name=${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  // Re-read the .env / environment config without a full restart (#140).
  reloadEnv: () =>
    request<EnvReloadResult>("/settings/reload", { method: "POST" }),
  // AI settings (#517). The API key is write-only — get() returns only
  // whether one is set plus a masked hint, never the plaintext.
  ai: {
    get: () => request<AiSettings>("/settings/ai"),
    setKey: (key: string) =>
      request<AiSettings>("/settings/ai/key", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      }),
    clearKey: () =>
      request<AiSettings>("/settings/ai/key", { method: "DELETE" }),
  },
  cults: {
    get: () => request<CultsSettings>("/settings/cults"),
    setCredentials: (username: string, api_key: string) =>
      request<CultsSettings>("/settings/cults/credentials", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, api_key }),
      }),
    clearCredentials: () =>
      request<CultsSettings>("/settings/cults/credentials", { method: "DELETE" }),
  },
  mmf: {
    get: () => request<MmfSettings>("/settings/mmf"),
    setKey: (key: string) =>
      request<MmfSettings>("/settings/mmf/key", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      }),
    clearKey: () =>
      request<MmfSettings>("/settings/mmf/key", { method: "DELETE" }),
  },
};

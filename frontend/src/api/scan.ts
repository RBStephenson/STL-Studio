import { request } from "./base";
import type { DirListing, Library, ScanRoot, ScanStatus } from "./types";

export const scanApi = {
  start: () => request<ScanStatus>("/scan/start", { method: "POST" }),
  startCreator: (creatorId: number) =>
    request<ScanStatus>(`/scan/creator/${creatorId}`, { method: "POST" }),
  cancel: () => request<{ ok: boolean }>("/scan/cancel", { method: "POST" }),
  status: () => request<ScanStatus>("/scan/status"),
  browse: (path?: string, mode?: string) => {
    const params = new URLSearchParams();
    if (path) params.set("path", path);
    if (mode) params.set("mode", mode);
    const qs = params.toString();
    return request<DirListing>(`/scan/browse${qs ? `?${qs}` : ""}`);
  },
  startInboxScan: (path: string) =>
    request<ScanStatus>("/scan/inbox", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  roots: () => request<ScanRoot[]>("/scan/roots"),
  libraries: () => request<Library[]>("/scan/libraries"),
  addRoot: (path: string, layout?: string, opts?: { name?: string; is_writable?: boolean; group_by_character?: boolean }) =>
    request<ScanRoot>("/scan/roots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, layout: layout || "{creator}", ...opts }),
    }),
  updateRoot: (id: number, body: { layout?: string; enabled?: boolean; name?: string; is_writable?: boolean; group_by_character?: boolean }) =>
    request<ScanRoot>(`/scan/roots/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  removeRoot: (id: number) =>
    request<{ ok: boolean }>(`/scan/roots/${id}`, { method: "DELETE" }),
};

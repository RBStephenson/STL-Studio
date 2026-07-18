import { request } from "./base";
import type {
  DownloadImagesStart,
  DownloadImagesStatus,
  ImportApplyStart,
  ImportApplyStatus,
  ImportPreview,
  SourceContents,
  SourceMapping,
} from "./types";

export const importApi = {
  sourceContents: (source: string) =>
    request<SourceContents>(`/import/source-contents?source=${encodeURIComponent(source)}`),
  // creatorName (#1110): pass the pack's already-known Creator field value
  // (typed, or Fetch-populated) so a single-pack scan attaches models to the
  // real creator directly instead of a folder-named placeholder.
  scanFolder: (path: string, creatorName?: string) =>
    request<{ running: boolean; message: string }>("/import/scan-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, creator_name: creatorName || undefined }),
    }),
  preview: (source: string) =>
    request<ImportPreview>(`/import/preview?source=${encodeURIComponent(source)}`),
  getMapping: (path: string) =>
    request<SourceMapping | null>(`/import/source-mapping?path=${encodeURIComponent(path)}`),
  setMapping: (source_path: string, library_id: number) =>
    request<SourceMapping>("/import/source-mapping", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_path, library_id }),
    }),
  apply: (source: string) =>
    request<ImportApplyStart>("/import/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    }),
  applyStatus: () => request<ImportApplyStatus>("/import/apply/status"),
  downloadImages: (packPath: string, imageUrls: string[]) =>
    request<DownloadImagesStart>("/import/download-images", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pack_path: packPath, image_urls: imageUrls }),
    }),
  downloadImagesStatus: () => request<DownloadImagesStatus>("/import/download-images/status"),
};

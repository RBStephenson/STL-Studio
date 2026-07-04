import { request, BASE } from "./base";
import type { DriveStatus } from "./types";

export const filesApi = {
  openFolder: (path: string) =>
    request<{ ok: boolean }>(`/files/open-folder?path=${encodeURIComponent(path)}`, {
      method: "POST",
    }),
  driveStatus: () => request<DriveStatus>("/files/drive-status"),
};

// `version` (e.g. a model's updated_at) makes the URL change when the image
// content changes, letting the backend serve it as an immutable long-cache
// response so repeat loads are instant (#185).
export const fileUrl = (path: string, version?: string | null) =>
  `/api/files/image?path=${encodeURIComponent(path)}` +
  (version ? `&v=${encodeURIComponent(version)}` : "");

export const documentUrl = (path: string) =>
  `/api/files/document?path=${encodeURIComponent(path)}`;

// version (the file size) lets the backend serve an immutable long-cache
// response so reopening the viewer doesn't re-read the STL from the drive (#304).
export const stlUrl = (path: string, version?: string | number | null) =>
  `/api/files/stl?path=${encodeURIComponent(path)}` +
  (version != null ? `&v=${encodeURIComponent(String(version))}` : "");

export const downloadZip = async (fileIds: number[], zipName: string) => {
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
};

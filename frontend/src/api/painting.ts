import { request, ApiError, BASE, downloadPdf, stampQuery, triggerBlobDownload } from "./base";
import type { SeriesExportOptions, StampOptions } from "./base";
import type {
  ColorMatchResult,
  Guide,
  GuideCreateInput,
  GuideDraftStatus,
  GuideImportResult,
  GuideList,
  GuideUpdateInput,
  GuideValidationResult,
  ImportDiff,
  Paint,
  PaintBrand,
  PaintCreate,
  PaintLine,
  PaintList,
  PaintOverrideInput,
  ReferenceImage,
} from "./types";

export const paintingApi = {
  brands: {
    list: () => request<PaintBrand[]>("/painting/brands"),
    create: (name: string) =>
      request<PaintBrand>("/painting/brands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      }),
  },
  lines: {
    create: (body: { brand_id: number; name: string; code_pattern?: string | null }) =>
      request<PaintLine>("/painting/lines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
  },
  inventory: {
    importPreview: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${BASE}/painting/inventory/import`, { method: "POST", body: form });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
        throw new Error(detail);
      }
      return res.json() as Promise<ImportDiff>;
    },
    importConfirm: async (file: File, opts: { added: boolean; changed: boolean; removed: boolean }) => {
      const form = new FormData();
      form.append("file", file);
      form.append("apply_added", String(opts.added));
      form.append("apply_changed", String(opts.changed));
      form.append("apply_removed", String(opts.removed));
      const res = await fetch(`${BASE}/painting/inventory/import/confirm`, { method: "POST", body: form });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
        throw new Error(detail);
      }
      return res.json() as Promise<{ ok: boolean; applied: { added: number; changed: number; removed: number } }>;
    },
    exportCsv: async () => {
      const res = await fetch(`${BASE}/painting/inventory/export.csv`);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const stamp = new Date().toISOString().slice(0, 10);
      triggerBlobDownload(blob, `paintRack_export_${stamp}.csv`);
    },
  },
  paints: {
    list: (params: Record<string, string | number | boolean>) => {
      const qs = new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== "" && v !== undefined && v !== null)
          .map(([k, v]) => [k, String(v)])
      ).toString();
      return request<PaintList>(`/painting/paints${qs ? `?${qs}` : ""}`);
    },
    create: (body: PaintCreate) =>
      request<Paint>("/painting/paints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    update: (id: number, patch: Partial<PaintCreate>) =>
      request<Paint>(`/painting/paints/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }),
    delete: (id: number) =>
      request<{ ok: boolean }>(`/painting/paints/${id}`, { method: "DELETE" }),
    // Force-add an off-shelf paint during guide import (#417): lands in the
    // synthetic 'Imported / Uncategorized' line, known-but-not-owned.
    forceAdd: (name: string, hex: string | null) =>
      request<Paint>("/painting/paints/import-forced", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, hex }),
      }),
  },
  guides: {
    list: (params: Record<string, string | number | boolean> = {}) => {
      const qs = new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== "" && v !== undefined && v !== null)
          .map(([k, v]) => [k, String(v)])
      ).toString();
      return request<GuideList>(`/painting/guides${qs ? `?${qs}` : ""}`);
    },
    get: (id: number) => request<Guide>(`/painting/guides/${id}`),
    // The set of model ids that have at least one guide (Library badge, #263).
    modelIds: () => request<{ model_ids: number[] }>("/painting/guides/model-ids"),
    // Import a legacy guide HTML file → lands a draft + returns the report (#277).
    // `dryRun` previews without persisting; `paintOverrides` resolves unresolved
    // swatch paints on the committing call (#417).
    import_: (
      html: string,
      slug: string,
      opts: { dryRun?: boolean; paintOverrides?: PaintOverrideInput[] } = {},
    ) =>
      request<GuideImportResult>("/painting/guides/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          html,
          slug,
          dry_run: opts.dryRun ?? false,
          paint_overrides: opts.paintOverrides ?? [],
        }),
      }),
    // Create a new guide (#329). Backend GuideCreate requires slug+title;
    // everything else (incl. the `tabs` spine) is optional.
    create: (body: GuideCreateInput) =>
      request<Guide>("/painting/guides", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    // Partial update (#258/#329). Omitted scalar/JSON fields are unchanged;
    // sending `tabs` REPLACES the whole tab subtree (omit to leave it alone).
    update: (id: number, patch: GuideUpdateInput) =>
      request<Guide>(`/painting/guides/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }),
    delete: (id: number) =>
      request<{ ok: boolean }>(`/painting/guides/${id}`, { method: "DELETE" }),
    // Validator findings for the editor panel + publish gate (#489).
    validate: (id: number) =>
      request<GuideValidationResult>(`/painting/guides/${id}/validation`),
    // Kick off async AI draft generation (#524). 202 + initial status; 503
    // when no API key, 409 when a draft is already generating for this guide.
    startDraft: (id: number) =>
      request<GuideDraftStatus>(`/painting/guides/${id}/draft`, { method: "POST" }),
    // Poll the draft-generation job; carries the candidate draft + flags when done.
    draftStatus: (id: number) =>
      request<GuideDraftStatus>(`/painting/guides/${id}/draft/status`),
    // Reference image (#535/#536): the bytes feed Claude vision at draft time.
    // `<img src>` target for the stored image; `v` busts the cache after a replace.
    referenceImageUrl: (id: number, v?: number | string) =>
      `${BASE}/painting/guides/${id}/reference-image${v !== undefined ? `?v=${v}` : ""}`,
    uploadReferenceImage: async (id: number, file: File, altText?: string) => {
      const form = new FormData();
      form.append("file", file);
      if (altText) form.append("alt_text", altText);
      const res = await fetch(`${BASE}/painting/guides/${id}/reference-image`, {
        method: "POST", body: form,
      });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
        throw new ApiError(res.status, detail);
      }
      return res.json() as Promise<ReferenceImage>;
    },
    deleteReferenceImage: (id: number) =>
      request<{ ok: boolean }>(`/painting/guides/${id}/reference-image`, { method: "DELETE" }),
    // Render the guide to a print-ready PDF and trigger a download (#320).
    // Stamping options (#511): footer on by default, watermark off.
    exportPdf: (id: number, slug: string, opts: StampOptions = {}) =>
      downloadPdf(
        `${BASE}/painting/guides/${id}/export/pdf${stampQuery(opts)}`,
        `${slug}.pdf`,
      ),
    // Render every published guide in a series into one bundled PDF (#490/#511).
    exportSeriesPdf: (seriesId: number, opts: SeriesExportOptions = {}) =>
      downloadPdf(
        `${BASE}/painting/series/${seriesId}/export/pdf${stampQuery(opts)}`,
        `series-${seriesId}-bundle.pdf`,
      ),
  },
  // Color-match studio (#493/#561): sample a reference image into a palette of
  // owned-paint suggestions. Suggest-only — nothing is persisted server-side.
  colorMatch: async (
    file: File,
    opts: { k?: number; candidatesPerRegion?: number } = {},
  ): Promise<ColorMatchResult> => {
    const form = new FormData();
    form.append("file", file);
    if (opts.k !== undefined) form.append("k", String(opts.k));
    if (opts.candidatesPerRegion !== undefined)
      form.append("candidates_per_region", String(opts.candidatesPerRegion));
    const res = await fetch(`${BASE}/painting/colormatch`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new ApiError(res.status, detail);
    }
    return res.json() as Promise<ColorMatchResult>;
  },
  // Eyedropper (#561): match a single point. x/y are normalized [0,1] from the
  // image's top-left. Returns a single-region result.
  colorMatchPoint: async (
    file: File, x: number, y: number,
    opts: { candidatesPerRegion?: number } = {},
  ): Promise<ColorMatchResult> => {
    const form = new FormData();
    form.append("file", file);
    form.append("x", String(x));
    form.append("y", String(y));
    if (opts.candidatesPerRegion !== undefined)
      form.append("candidates_per_region", String(opts.candidatesPerRegion));
    const res = await fetch(`${BASE}/painting/colormatch/point`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new ApiError(res.status, detail);
    }
    return res.json() as Promise<ColorMatchResult>;
  },
};

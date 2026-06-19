const BASE = "/api";

// Error carrying the HTTP status so callers can distinguish a 404 (resource
// gone) from a 5xx or a network failure. Still an Error, so existing handlers
// that only read `.message` keep working.
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    let detail: string | undefined;
    try { detail = (await res.json()).detail; } catch { /* ignore */ }
    throw new ApiError(res.status, detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export type PrintStatus = "none" | "queued" | "printing" | "printed";
export const PRINT_STATUS_CYCLE: PrintStatus[] = ["none", "queued", "printing", "printed"];
export const PRINT_STATUS_LABELS: Record<PrintStatus, string> = {
  none: "Not printed",
  queued: "Queued",
  printing: "Printing",
  printed: "Printed",
};

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
  removed_auto_tags: string[];
  category: string | null;
  needs_review: boolean;
  nsfw: boolean;
  excluded: boolean;
  is_favorite: boolean;
  is_group_rep: boolean;
  variant_order: number | null;
  user_rating: number | null;
  queued_at: string | null;
  printed_at: string | null;
  print_status: PrintStatus;
  print_count: number;
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
  printing: number;
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

export interface DriveStatusRoot {
  path: string;
  enabled: boolean;
  available: boolean;
}

export interface DriveStatus {
  roots: DriveStatusRoot[];
  all_available: boolean;
}

export interface FilterPreset {
  name: string;
  qs: string;
}

export interface AppSettings {
  painting_guides_enabled: boolean;
  show_nsfw: boolean;
  library_page_size: number;
  filter_presets: FilterPreset[];
  recent_days: number;
  library_sort: LibrarySort;
  scan_ignore_patterns: string[];
  scan_tag_rules: ScanTagRule[];
  scan_parts_names: string[];
}

export interface ScanTagRule {
  keyword: string;
  tag: string;
}

export type LibrarySort = "name" | "added" | "creator" | "rating";

export interface EnvReloadResult {
  ok: boolean;
  scan_roots: string[];
  drive_mappings: Record<string, string>;
  restart_required: string[];
}

// --- Painting module (Paint Shelf, M1) ---

export const PAINT_FINISHES = [
  "matte", "satin", "gloss", "metallic", "ink", "wash",
  "fluor", "primer", "medium", "pigment", "texture",
] as const;
export type PaintFinish = (typeof PAINT_FINISHES)[number];

export interface PaintLine {
  id: number;
  brand_id: number;
  name: string;
  code_pattern: string | null;
}

export interface PaintBrand {
  id: number;
  name: string;
  lines: PaintLine[];
}

export interface Paint {
  id: number;
  paint_line_id: number;
  code: string;
  name: string;
  hex: string | null;
  value_pct: number | null;
  finish: string;
  matchable: boolean;
  owned: boolean;
  handling_flags: string[];
  substitute_for: number[];
  notes: string | null;
  source: string | null;
}

export interface PaintCreate {
  paint_line_id: number;
  code: string;
  name: string;
  hex?: string | null;
  value_pct?: number | null;
  finish: PaintFinish;
  owned?: boolean;
  notes?: string | null;
  source?: string | null;
}

export interface PaintList {
  total: number;
  page: number;
  page_size: number;
  items: Paint[];
}

export interface ImportDiffRow {
  brand: string;
  code: string;
  name: string;
  paint_class: string;
  size?: string;
  count?: number;
  color?: string;
  paint_id?: number;
  changes?: Record<string, { from: string | number; to: string | number }>;
}

export interface ImportWarning {
  brand: string;
  code: string;
  name: string;
  paint_class: string;
  message: string;
}

export interface ImportDiff {
  added: ImportDiffRow[];
  changed: ImportDiffRow[];
  removed: ImportDiffRow[];
  warnings: ImportWarning[];
  summary: { rows: number; added: number; changed: number; removed: number; warnings: number };
}

// --- Painting guides (M2 reader, #259) ------------------------------------
// Mirrors the backend GuideRead tree (app/painting/schemas). Swatch/mix reads
// carry a resolved `paint` summary the reader draws (the spine stores paint_id).

export interface PaintSummary {
  name: string;
  code: string;
  brand: string;
  hex: string | null;
}

export interface GuideSwatch {
  id: number;
  paint_id: number;
  value_pct: number | null;
  role_label: string | null;
  sort_order: number;
  paint: PaintSummary | null;
}

export interface GuideMixComponent {
  id: number;
  paint_id: number;
  parts: number;
  sort_order: number;
  paint: PaintSummary | null;
}

export interface GuideStep {
  id: number;
  title: string;
  technique_tag: string | null;
  technique_label: string | null;
  body: string | null;
  value_intent: string | null;
  tip: string | null;
  warning: string | null;
  ratio_box: string | null;
  sort_order: number;
  swatches: GuideSwatch[];
  mix_components: GuideMixComponent[];
}

export interface GuidePhase {
  id: number;
  label: string;
  subtab_key: string | null;
  sort_order: number;
  steps: GuideStep[];
}

export interface ValueChip {
  hex: string;
  value_pct: number;
  zone_label: string;
}

export interface GuideTabSection {
  heading: string;
  intro: string | null;
}

export interface SubTabDef {
  key: string;
  label: string;
  css_class: string | null;
  sort_order: number;
  // tip/warning/intro-<p> nested inside this subtab's .sub-content (#271).
  callouts?: TabCallout[];
}

export interface MethodCard {
  title: string;
  body: string | null;
  pros: string | null;
  cons: string | null;
  best: string | null;
  recommended: boolean;
  badge: string | null;
}

export interface MethodBlock {
  recommendation: string | null;
  cards: MethodCard[];
  freckle_note: string | null;
}

export interface TabCallout {
  kind: "tip" | "warning" | "text";
  html: string;
}

export interface RawBlock {
  css_class: string;
  html: string;
}

export interface GuideTab {
  id: number;
  name: string;
  dom_id: string | null;
  sort_order: number;
  has_expert_subtab: boolean;
  section: GuideTabSection | null;
  value_map: { label: string | null; chips: ValueChip[] } | null;
  subtabs: SubTabDef[];
  callouts: TabCallout[];
  raw_blocks?: RawBlock[];
  method_block: MethodBlock | null;
  phases: GuidePhase[];
}

export interface GuideTheme {
  bg?: string | null;
  surface?: string | null;
  surface2?: string | null;
  surface3?: string | null;
  border?: string | null;
  text?: string | null;
  text_muted?: string | null;
  text_dim?: string | null;
  accent?: string | null;
  hero_gradient?: string | null;
}

export interface PaintPill {
  name: string;
  color?: string | null;
}

export interface CreatorCredit {
  name: string | null;
  url: string | null;
  link_text: string | null;
}

export interface ThinningConfig {
  airbrush_rows: { technique: string; nozzle?: string | null; ratio: string; behavior?: string | null }[];
  brush_rows: { technique: string; ratio: string; behavior?: string | null }[];
  thinning_cards: { title: string; body: string }[];
}

export interface Guide {
  id: number;
  slug: string;
  title: string;
  title_lead: string | null;
  subtitle: string | null;
  category_id: number | null;
  category_label: string | null;
  series_id: number | null;
  model_id: number | null;
  scale: string | null;
  status: string;
  franchise: string | null;
  quote: string | null;
  creator_credit: CreatorCredit | null;
  light_source: string | null;
  philosophy_note: string | null;
  paint_lines_used: PaintPill[];
  technique_tags: string[];
  character_brief: { philosophy?: string | null; [k: string]: unknown } | null;
  theme: GuideTheme | null;
  head_style: string | null;
  thinning_config: ThinningConfig | null;
  tabs: GuideTab[];
  created_at: string | null;
  updated_at: string | null;
  published_at: string | null;
}

// Editor input shapes (#329). Mirror backend GuideCreate/GuideUpdate. The full
// `tabs` spine (TabIn) is omitted here — the metadata editor never sends it, so
// the content spine is left untouched (replace-subtree only fires when present).
export type GuideScale = "1:6" | "1:12" | "75mm" | "28mm" | "bust" | "other";
export type GuideStatus = "draft" | "in_review" | "published" | "archived";

export interface GuideCreateInput {
  slug: string;
  title: string;
  title_lead?: string | null;
  subtitle?: string | null;
  category_label?: string | null;
  model_id?: number | null;
  scale?: GuideScale | null;
  status?: GuideStatus;
  franchise?: string | null;
  quote?: string | null;
  creator_credit?: CreatorCredit | null;
  light_source?: string | null;
  philosophy_note?: string | null;
  paint_lines_used?: PaintPill[];
  technique_tags?: string[];
}

// Content-spine input shapes (#329 PR 2). Mirror backend SwatchIn/StepIn/
// PhaseIn/TabIn. Sending `tabs` on a guide update REPLACES the whole subtree,
// so the editor always serializes the complete tree. Mix components are
// deferred to #339, so only single-paint swatches are authored here.
export type StepTechnique = "airbrush" | "brush" | "wash" | "finish" | "effects" | "filter";

export interface SwatchInput {
  paint_id: number;
  value_pct?: number | null;
  role_label?: string | null;
  sort_order?: number;
}

export interface StepInput {
  title: string;
  technique_tag?: StepTechnique | null;
  technique_label?: string | null;
  body?: string | null;
  value_intent?: string | null;
  tip?: string | null;
  warning?: string | null;
  ratio_box?: string | null;
  sort_order?: number;
  swatches?: SwatchInput[];
}

export interface PhaseInput {
  label?: string;
  subtab_key?: string | null;
  sort_order?: number;
  steps?: StepInput[];
}

export interface TabInput {
  name: string;
  dom_id?: string | null;
  sort_order?: number;
  section?: { heading: string; intro: string | null } | null;
  phases?: PhaseInput[];
}

// All-optional partial update; create fields plus the optional content spine.
export type GuideUpdateInput = Partial<GuideCreateInput> & { tabs?: TabInput[] };

export interface GuideListItem {
  id: number;
  slug: string;
  title: string;
  category_id: number | null;
  series_id: number | null;
  model_id: number | null;
  scale: string | null;
  status: string;
  franchise: string | null;
  technique_tags: string[];
  paint_lines_used: PaintPill[];
  updated_at: string | null;
  published_at: string | null;
}

export interface GuideList {
  total: number;
  page: number;
  page_size: number;
  items: GuideListItem[];
}

// --- Guide import (#277) --------------------------------------------------
// The importer resolves swatch paints against the Paint Shelf; unresolved ones
// are dropped from the draft and reported here (the inventory-gap list, §9.7).

export interface UnresolvedPaint {
  name: string;
  brand: string | null;
  step: string | null;
  hex: string | null; // swatch dot colour, seeds a forced add (#417)
}

// A user resolution mapping an unresolved swatch name to a chosen paint (#417).
export interface PaintOverrideInput {
  name: string;
  brand?: string | null;
  paint_id: number;
}

export interface GuideImportReport {
  resolved_paints: number;
  unresolved_paints: UnresolvedPaint[];
  unmapped_nodes: string[];
  notes: string[];
}

export interface GuideImportResult {
  guide: Guide | null; // null on a dry_run preview — nothing persisted (#417)
  report: GuideImportReport;
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
    renameTag: (oldTag: string, newTag: string) =>
      request<{ ok: boolean; updated: number }>("/models/tags/rename", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ old_tag: oldTag, new_tag: newTag }),
      }),
    mergeTag: (sourceTag: string, targetTag: string) =>
      request<{ ok: boolean; updated: number }>("/models/tags/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_tag: sourceTag, target_tag: targetTag }),
      }),
    deleteTag: async (tag: string) => {
      const res = await fetch(`${BASE}/models/tags/${encodeURIComponent(tag)}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return res.json() as Promise<{ ok: boolean; updated: number }>;
    },
    update: (id: number, body: Record<string, unknown>) =>
      request<{ ok: boolean }>(`/models/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    setGroupRep: (id: number, isGroupRep: boolean) =>
      request<{ ok: boolean; is_group_rep: boolean }>(`/models/${id}/group-rep`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_group_rep: isGroupRep }),
      }),
    setThumbnail: (id: number, body: { thumbnail_path?: string | null; thumbnail_url?: string | null }) =>
      request<{ ok: boolean }>(`/models/${id}/thumbnail`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    clearThumbnail: (id: number) =>
      request<{ ok: boolean }>(`/models/${id}/thumbnail`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thumbnail_path: null, thumbnail_url: null }),
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
    setRating: (id: number, rating: number | null) =>
      request<{ ok: boolean; user_rating: number | null }>(`/models/${id}/rating`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating }),
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
    setPrintStatus: (id: number, status: PrintStatus) =>
      request<{ ok: boolean; print_status: PrintStatus; print_count: number }>(`/models/${id}/print-status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      }),
    bulkTag: (ids: number[], addTags: string[], removeTags: string[]) =>
      request<{ ok: boolean; updated: number }>("/models/bulk", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, add_tags: addTags, remove_tags: removeTags }),
      }),
    bulkExclude: (ids: number[], excluded: boolean) =>
      request<{ ok: boolean; updated: number }>("/models/bulk/exclude", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, excluded }),
      }),
    bulkReview: (ids: number[], needs_review: boolean) =>
      request<{ ok: boolean; updated: number }>("/models/bulk/review", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, needs_review }),
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
    batchSetGroup: (modelIds: number[], character: string | null) =>
      request<{ ok: boolean; character: string | null; updated: number[]; missing: number[] }>(
        `/models/group/batch-set`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_ids: modelIds, character }),
        },
      ),
    // Persist a manual model order within a variant group (#399). Empty `ids`
    // resets the group to its heuristic order.
    reorderGroup: (creatorId: number, character: string, ids: number[]) =>
      request<{ ok: boolean; reset: boolean; updated: number }>(`/models/group/reorder`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ creator_id: creatorId, character, ids }),
      }),
    updateSTLFile: (fileId: number, body: Record<string, unknown>) =>
      request<{ ok: boolean }>(`/models/stl-files/${fileId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    batchThumbnailFromUrl: (modelIds: number[], url: string) =>
      request<{ ok: boolean; downloaded: boolean; detail?: string; updated: number[]; missing: number[] }>(
        `/models/group/thumbnail/from-url`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_ids: modelIds, url }),
        },
      ),
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
      request<{ ok: boolean }>(`/files/open-folder?path=${encodeURIComponent(path)}`, {
        method: "POST",
      }),
    driveStatus: () => request<DriveStatus>("/files/drive-status"),
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
  settings: {
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
  },
  painting: {
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
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `paintRack_export_${stamp}.csv`;
        a.click();
        URL.revokeObjectURL(url);
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
      // Render the guide to a print-ready PDF and trigger a download (#320).
      // A blob endpoint, so it can't go through request(); surfaces the 503
      // "Chromium not installed" detail like the other download helpers.
      exportPdf: async (id: number, slug: string) => {
        const res = await fetch(`${BASE}/painting/guides/${id}/export/pdf`);
        if (!res.ok) {
          let detail = `${res.status} ${res.statusText}`;
          try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
          throw new ApiError(res.status, detail);
        }
        const url = URL.createObjectURL(await res.blob());
        const a = document.createElement("a");
        a.href = url;
        a.download = `${slug}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      },
    },
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
  // `version` (e.g. a model's updated_at) makes the URL change when the image
  // content changes, letting the backend serve it as an immutable long-cache
  // response so repeat loads are instant (#185).
  fileUrl: (path: string, version?: string | null) =>
    `/api/files/image?path=${encodeURIComponent(path)}` +
    (version ? `&v=${encodeURIComponent(version)}` : ""),
  // version (the file size) lets the backend serve an immutable long-cache
  // response so reopening the viewer doesn't re-read the STL from the drive (#304).
  stlUrl: (path: string, version?: string | number | null) =>
    `/api/files/stl?path=${encodeURIComponent(path)}` +
    (version != null ? `&v=${encodeURIComponent(String(version))}` : ""),
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

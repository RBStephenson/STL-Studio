// Domain types mirroring the backend schemas. Split out of the former
// client.ts monolith (#STUDIO-62); re-exported wholesale from the client.ts
// barrel so existing `import { type Model } from "../api/client"` keep working.

export type PrintStatus = "none" | "queued" | "printing" | "printed";
export const PRINT_STATUS_CYCLE: PrintStatus[] = ["none", "queued", "printing", "printed"];
export const PRINT_STATUS_LABELS: Record<PrintStatus, string> = {
  none: "Not printed",
  queued: "Queued",
  printing: "Printing",
  printed: "Printed",
};

/** Scanner-detected structured variant attributes (#608). All optional —
 *  only present when the folder name carried the signal. */
export interface ParsedAttributes {
  support_status?: "unsupported" | "pre-supported" | "supported";
  cut_status?: "solid" | "hollow" | "split" | "merged" | "full-cut";
  slicer?: "lychee" | "chitubox";
  version?: string;
}

/** Durable variant group (#613). `source` distinguishes scanner-proposed
 *  ("auto") groups from user-curated ("manual") ones. */
export interface VariantGroup {
  id: number;
  creator_id: number;
  label: string | null;
  rep_model_id: number | null;
  source: "auto" | "manual";
  reason: string | null;
  confidence: number | null;
}

export interface Model {
  id: number;
  name: string;
  title: string | null;
  description: string | null;
  notes: string | null;
  character: string | null;
  variant_group_id: number | null;
  variant_group: VariantGroup | null;
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
  parsed_attributes: ParsedAttributes;
  needs_review: boolean;
  is_inbox: boolean;
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
  removed_image_paths: string[];
  other_files: string[];
  primary_image_path: string | null;
  rating: number | null;
  like_count: number | null;
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
  part_name: string | null;
  sup_of_id?: number | null;
}

export interface ModelDetail extends Model {
  stl_files: STLFile[];
  creator: { id: number; name: string; source_url: string | null } | null;
  collection_ids: number[];
  // True when this model's current folder no longer matches where it would
  // land under the library's organize template (see /settings library tab).
  unorganized: boolean;
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
  name: string | null;
  is_writable: boolean;
  group_by_character: boolean;
}

export interface Library {
  id: number;
  path: string;
  name: string;
  is_writable: boolean;
  write_enabled: boolean;
}

export interface SourceContentsEntry {
  name: string;
  path: string;
  already_imported: boolean;
  file_count: number; // recursive STL-family count on disk (#456)
}

export interface SourceContents {
  source: string;
  is_flat: boolean;
  entries: SourceContentsEntry[];
  file_count: number; // root recursive STL count, for the flat single-card (#456)
}

export interface ImportPreviewPack {
  name: string;
  source_path: string;
  file_count: number;
  model_ids: number[];
  creator_name: string | null;
  title: string | null;
  character: string | null;
  notes: string | null;
  source_url: string | null;
  tags: string[];
}

export interface ImportPreview {
  source: string;
  library_id: number | null;
  packs: ImportPreviewPack[];
}

export interface SourceMapping {
  source_path: string;
  library_id: number;
}

export interface ImportApplyIneligible {
  model_id: number;
  proposed_dir: string;
  reasons: string[];
}

export interface ImportApplyResult {
  manifest_id: string;
  moved_models: number;
  moved_files: number;
  skipped: number;
  ineligible: ImportApplyIneligible[];
  undo_log: string | null;
}

export interface ImportApplyStart {
  // false = nothing to move — `result` is already final, no need to poll.
  // true = a background job is running; poll importApi.applyStatus().
  started: boolean;
  result: ImportApplyResult | null;
}

export interface ImportApplyStatus {
  running: boolean;
  message: string;
  moved_files: number;
  total_files: number;
  error: string | null;
  result: ImportApplyResult | null;
}

export interface DownloadImagesResult {
  downloaded: number;
}

export interface DownloadImagesStart {
  // false = nothing to download — `result` is already final, no need to poll.
  // true = a background job is running; poll importApi.downloadImagesStatus().
  started: boolean;
  result: DownloadImagesResult | null;
}

export interface DownloadImagesStatus {
  running: boolean;
  message: string;
  downloaded: number;
  total: number;
  error: string | null;
  result: DownloadImagesResult | null;
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
  // App-level default guide theme (#514): new guides inherit these colors.
  guide_theme_defaults: GuideTheme;
  // AI model id + generation effort for guide generation (#517). The API key is
  // NOT here — it's write-only via the dedicated /settings/ai endpoints.
  ai_model: string;
  ai_effort: AiEffort;
  part_categories_enabled: boolean;
  horizontal_parts_layout: boolean;
  gallery_enabled: boolean;
  gallery_auto_rotate: boolean;
  gallery_rotation_seconds: number;
  ai_organize_enabled: boolean;
  ai_organize_url: string;
  ai_organize_model: string;
  ai_guides_enabled: boolean;
  ai_guides_api: number | null;
  ai_organize_api: number | null;
  // Application log verbosity — changing it takes effect immediately (no restart).
  log_level: LogLevel;
  // Library reorganize destination template ("" = the built-in default,
  // {creator}/{character}/{title}; optional {scale}) and whether every segment renders
  // lowercase/hyphenated (import-style) rather than case-preserving.
  reorganize_template: string;
  reorganize_slugify: boolean;
  // Feature flag: gates the Reorganize Library feature end-to-end (UI + the
  // destructive apply/undo writes). Off by default; toggled on the Library tab.
  reorganize_enabled: boolean;
  // Collections page: every card gets the same box size (the one cover art
  // already uses) instead of a compact box for collections with no cover.
  collections_uniform_size: boolean;
}

export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export interface AiApiConfig {
  id: number;
  name: string;
  api_type: "anthropic" | "openai";
  url: string | null;
  model: string;
  effort: string | null;
  // Per-connection request timeout in seconds (default 10).
  request_timeout: number;
  key_set: boolean;
  key_hint: string | null;
}

// AI organizer settings — OpenAI-compatible endpoint for part naming.
export interface AiOrganizeSettings {
  key_set: boolean;
  key_hint: string | null;
  enabled: boolean;
  url: string;
  model: string;
}

// "parts" (default) categorizes by physical part type (Head, Weapon, ...).
// "unit" groups by in-game unit/character instead (#878) — freeform, not
// limited to the standard category list.
export type AiOrganizeStrategy = "parts" | "unit";

export interface AiOrganizeSuggestion {
  id: number;
  part_type: string | null;
  part_name: string | null;
  sup_of_id: number | null;
}

export interface AiOrganizeResult {
  applied: AiOrganizeSuggestion[];
  message: string;
}

export interface AiOrganizeSuggestionPreview {
  id: number;
  filename: string;
  part_type: string | null;
  part_name: string | null;
  sup_of_id: number | null;
  sup_base_filename: string | null;
}

export interface AiOrganizePreviewResult {
  suggestions: AiOrganizeSuggestionPreview[];
  // Outcome of the optional LLM pass so the UI can distinguish "AI ran" from
  // "AI failed / was skipped": "ok" | "skipped" | "disabled" | "error".
  // llm_detail carries the failure reason when llm_status === "error".
  llm_status?: "ok" | "skipped" | "disabled" | "error";
  llm_detail?: string | null;
}

export interface AiOrganizeModelsList {
  models: string[];
}

export type AiEffort = "low" | "medium" | "high";

// AI settings status (#517) — key is write-only, never returned in full.
export interface AiSettings {
  key_set: boolean;
  key_hint: string | null;
  model: string;
  effort: AiEffort;
}

// Cults3D credential status (#578) — credentials are write-only.
export interface CultsSettings {
  credentials_set: boolean;
  hint: string | null;
}

// MyMiniFactory API key status — key is write-only, never returned in full.
export interface MmfSettings {
  key_set: boolean;
  key_hint: string | null;
}

export interface ScanTagRule {
  keyword: string;
  tag: string;
}

export type LibrarySort = "name" | "added" | "creator" | "rating";

export interface EnvReloadResult {
  ok: boolean;
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
  paint_id: number | null; // null when the swatch is kept by name only (#477)
  name: string | null;     // raw swatch text when unresolved
  value_pct: number | null;
  role_label: string | null;
  sort_order: number;
  paint: PaintSummary | null;
}

export interface GuideMixComponent {
  id: number;
  paint_id: number | null; // null when the component is kept by name only (#425)
  name: string | null;     // raw component text when unresolved
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

export interface ValidationFlag {
  severity: "block" | "warn";
  code: string;
  message: string;
  tab_index: number | null;
  phase_index: number | null;
  step_index: number | null;
  swatch_index: number | null;
  path: string | null;
}

export interface GuideValidationResult {
  ok: boolean;
  flags: ValidationFlag[];
}

// A guide's reference image metadata (#535/#536). The bytes are served by the
// GET reference-image endpoint; this carries the provenance + dimensions.
export interface ReferenceImage {
  id: number;
  guide_id: number | null;
  provenance: string;
  source_url: string | null;
  alt_text: string | null;
  width: number | null;
  height: number | null;
  created_at: string;
}

// Color-match studio (#493/#561). Mirrors backend ColorMatch* schemas.
export type ColorBand = "very_close" | "close" | "family" | "loose";

export interface ColorMatchCandidate {
  paint_id: number;
  code: string;
  name: string;
  brand: string;
  line: string;
  hex: string | null;
  finish: string;
  delta_l: number;
  delta_e: number | null;
  band: ColorBand;
}

export interface ColorMatchLadder {
  shadow: ColorMatchCandidate[];
  mid: ColorMatchCandidate[];
  highlight: ColorMatchCandidate[];
}

export interface ColorMatchRegion {
  hex: string;
  lab: [number, number, number];
  value_l: number;
  weight: number;
  ladder: ColorMatchLadder;
  hue_candidates: ColorMatchCandidate[];
  glaze_options: ColorMatchCandidate[];
}

export interface ColorMatchResult {
  regions: ColorMatchRegion[];
  caveat: string;
}

// AI draft-generation job status (#524/#492). When `status === "done"` the
// candidate `draft` (proposed tabs), validator `flags`, and `unresolved` paints
// are populated for the review UI to diff before the user accepts.
export type DraftJobStatus = "idle" | "running" | "done" | "error";

export interface DraftUnresolvedPaint {
  name: string;
  tab: string;
  step: string;
}

export interface GuideDraftStatus {
  status: DraftJobStatus;
  message: string;
  draft: { tabs: TabInput[] } | null;
  flags: ValidationFlag[];
  unresolved: DraftUnresolvedPaint[];
  error: string | null;
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
  reference_image_id: number | null;
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
  theme?: GuideTheme | null;
}

// Content-spine input shapes (#329 PR 2). Mirror backend SwatchIn/StepIn/
// PhaseIn/TabIn. Sending `tabs` on a guide update REPLACES the whole subtree,
// so the editor always serializes the complete tree. Mix components are
// deferred to #339, so only single-paint swatches are authored here.
export type StepTechnique = "airbrush" | "brush" | "wash" | "finish" | "effects" | "filter";

export interface SwatchInput {
  paint_id?: number | null; // omit/null when kept by name only (#477)
  name?: string | null;
  value_pct?: number | null;
  role_label?: string | null;
  sort_order?: number;
}

export interface MixComponentInput {
  paint_id?: number | null; // omit/null when kept by name only (#425)
  name?: string | null;
  parts: number;
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
  mix_components?: MixComponentInput[];
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

// Result of setting a store page + fetch/apply across selected variants (#545).
export interface GroupScrapeResult {
  applied: number;
  scraped: boolean;
  source_site: string | null;
  missing: number[];
  message: string;
}

// --- Library reorganize, Phase 1 preview (#323) ---
export type ReorganizeMoveKind = "move" | "rename" | "case_rename" | "in_place" | "merge";
export type ReorganizeCollisionKind =
  | "none" | "exact" | "case_only" | "unicode_only" | "legitimate_duplicate";

export interface ReorganizeFileMove {
  stl_file_id: number | null;
  current_path: string;
  proposed_path: string;
  size_bytes: number;
  mtime_ns: number;
  content_hash: string | null;
  fingerprint_method: "stat" | "content_hash";
  missing_file: boolean;
  // "stl" repaths an STLFile row; "image" repaths one of the model's own
  // image_paths/thumbnail_path/primary_image_path instead.
  kind: "stl" | "image";
}

export interface ReorganizeEntry {
  model_id: number;
  model_name: string;
  files: ReorganizeFileMove[];
  kind: ReorganizeMoveKind;
  proposed_dir: string;
  eligible: boolean;
  pack_override_paths: string[];
  collision: boolean;
  collision_kind: ReorganizeCollisionKind;
  collision_with: number[];
  unclassifiable: boolean;
  missing_fields: string[];
  over_length: boolean;
  reserved_name: boolean;
  overlaps_other: boolean;
  spans_multiple_dirs: boolean;
  is_symlink: boolean;
  escapes_scan_root: boolean;
  missing_files_on_disk: boolean;
}

export interface ReorganizeStats {
  total: number;
  eligible: number;
  moves_needed: number;
  already_in_place: number;
  collisions: number;
  unclassifiable: number;
  over_length: number;
  reserved: number;
  overlaps: number;
  blocked: number;
}

export interface ReorganizePreview {
  manifest_id: string;
  template: string;
  generated_at: string;
  entries: ReorganizeEntry[];
  stats: ReorganizeStats;
}

// Phase 2c resolution + apply/undo.
export interface ReorganizeOverride {
  creator?: string;
  character?: string;
  scale?: string;
  title?: string;
  suffix?: string;
}

export interface ReorganizeApplyResult {
  manifest_id: string;
  moved_files: number;
  moved_models: number;
  undo_log: string;
}

export interface ReorganizeUndoSkip {
  path: string;
  reason: string;
}

export interface ReorganizeUndoResult {
  manifest_id: string;
  reversed_files: number;
  skipped: ReorganizeUndoSkip[];
}

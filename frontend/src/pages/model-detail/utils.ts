// Pure helpers and shared types for the ModelDetail page.
// Extracted from ModelDetail.tsx (STUDIO-63 P1) — behavior-preserving.

export const PART_TYPE_SUGGESTIONS = [
  "Head", "Torso", "Body",
  "Right Arm", "Left Arm", "Arms",
  "Right Leg", "Left Leg", "Legs",
  "Hands", "Feet", "Base",
  "Weapon", "Shield", "Armor", "Cloak", "Cape",
  "Hair", "Wings", "Tail", "Accessories",
];

export const toPascalCase = (s: string): string =>
  s.trim().split(/\s+/).filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");

export function autoPartName(filename: string): string {
  return filename
    .replace(/\.(stl|STL)$/, "")
    .replace(/^Sup_/i, "")
    .replace(/_/g, " ")
    .trim();
}

export const ALPHA_BANDS = [
  ["A", "D"], ["E", "H"], ["I", "L"], ["M", "P"], ["Q", "T"], ["U", "Z"],
] as const;

export function buildAlphaBand(first: string): string {
  const u = first.toUpperCase();
  if (/[0-9]/.test(u)) return "0–9";
  for (const [start, end] of ALPHA_BANDS) {
    if (u >= start && u <= end) return `${start}–${end}`;
  }
  return "#";
}

export function groupAlphabetically<T extends { id: number; filename: string }>(files: T[]): Array<[string, T[]]> {
  const order = [...ALPHA_BANDS.map(([s, e]) => `${s}–${e}`), "0–9", "#"];
  const map = new Map<string, T[]>();
  for (const f of files) {
    const band = buildAlphaBand(f.filename[0] ?? "");
    if (!map.has(band)) map.set(band, []);
    map.get(band)!.push(f);
  }
  return [...map.entries()]
    .sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));
}

export type FileEntry<T> = { file: T; depth: 0 | 1 };

export function buildFileHierarchy<T extends { id: number; filename: string; sup_of_id?: number | null }>(
  files: T[]
): FileEntry<T>[] {
  const supIds = new Set(files.filter((f) => f.sup_of_id != null).map((f) => f.id));
  const result: FileEntry<T>[] = [];
  for (const f of files.filter((f) => !supIds.has(f.id)).sort((a, b) => a.filename.localeCompare(b.filename))) {
    result.push({ file: f, depth: 0 });
    const sups = files.filter((s) => s.sup_of_id === f.id).sort((a, b) => a.filename.localeCompare(b.filename));
    for (const sup of sups) result.push({ file: sup, depth: 1 });
  }
  // Orphaned sup files (parent not in this group) fall through as top-level.
  for (const f of files.filter((f) => supIds.has(f.id))) {
    if (!result.find((r) => r.file.id === f.id)) result.push({ file: f, depth: 0 });
  }
  return result;
}

export type ViewMode = "images" | "3d";

export type NavTarget = { id: number; from: string };

// Parse a Library origin URL into the filter params needed for the neighbors
// endpoint. Returns null when the origin isn't the Library grid (path "/") —
// models reached from a variant group, collection, or deep link show no Prev/Next.
export function parseLibraryOrigin(from: string | undefined): Record<string, string | number | boolean> | null {
  if (!from) return null;
  const [path, search = ""] = from.split("?");
  if (path !== "/") return null;
  const sp = new URLSearchParams(search);
  const params: Record<string, string | number | boolean> = {};
  for (const key of ["q", "creator_id", "exclude_creator_id", "source_site", "tag", "exclude_tag"]) {
    const val = sp.get(key);
    if (val) params[key] = val;
  }
  if (sp.get("needs_review") === "1") params.needs_review = true;
  // nsfw and has_thumbnail are tri-state: "1"=true, "0"=false, absent=no filter
  for (const key of ["nsfw", "has_thumbnail"]) {
    const val = sp.get(key);
    if (val === "1") params[key] = true;
    else if (val === "0") params[key] = false;
  }
  const fav = sp.get("is_favorite") === "1";
  const printStatus = sp.get("print_status") ?? "";
  const excludePrinted = sp.get("exclude_printed") === "1";
  const excluded = sp.get("excluded") === "1";
  const inbox = sp.get("is_inbox") === "1";
  if (fav) params.is_favorite = true;
  if (printStatus) params.print_status = printStatus;
  if (excludePrinted) params.exclude_printed = true;
  if (excluded) params.excluded = true;
  if (inbox) params.is_inbox = true;
  // "Recently added" view (#170): same window + newest-first order as the grid,
  // so Prev/Next walks the list the user was looking at.
  const addedDays = sp.get("added_days");
  if (addedDays) {
    params.added_within_days = addedDays;
    params.sort = "added";
  } else if (sp.get("sort")) {
    // Chosen Library sort (#247): walk Prev/Next in the same order as the grid.
    params.sort = sp.get("sort")!;
  }
  params.group_variants = !fav && !printStatus && !excluded;
  return params;
}

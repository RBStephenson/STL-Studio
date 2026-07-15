import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, RefreshCw, Square, AlertCircle } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
import type {
  ReorganizeEntry,
  ReorganizePreview,
  ReorganizeMoveKind,
  ReorganizeOverride,
  ReorganizeApplyResult,
  ReorganizeCollisionKind,
} from "../api/client";
import ReorganizeStatsBar from "../components/reorganize/ReorganizeStatsBar";

const DEFAULT_TEMPLATE = "{creator}/{character}/{title}";
const DEBOUNCE_MS = 500;
const PAGE_SIZES = [20, 50, 100] as const;

type FilterTab = "all" | "moves" | "collisions" | "unclassifiable" | "blocked" | "in_place";

/** Page numbers to render, collapsing runs into a single "…" — always keeps
 *  first, last, and the pages immediately around `current` (ADDENDUM §6). */
function paginationRange(current: number, total: number): (number | "ellipsis")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = new Set([1, total, current, current - 1, current + 1]);
  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const out: (number | "ellipsis")[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (prev && p - prev > 1) out.push("ellipsis");
    out.push(p);
    prev = p;
  }
  return out;
}

// Tabs mix two dimensions: what KIND of change an entry needs (Moves,
// Already In Place) and WHY it can't proceed yet (Collisions, Unclassifiable,
// Blocked) — so a row can land in more than one tab, e.g. a would-be move
// that's also a collision shows under Collisions and Blocked, not Moves,
// until the collision is resolved. Hints spell this out (STUDIO-164).
const FILTERS: { key: FilterTab; label: string; hint: string }[] = [
  { key: "all", label: "All", hint: "Every model in this preview" },
  { key: "moves", label: "Moves", hint: "Will move or rename on Apply right now — blocked movers show under Collisions/Unclassifiable/Blocked instead until resolved" },
  { key: "collisions", label: "Collisions", hint: "Proposed destination collides with another model or file" },
  { key: "unclassifiable", label: "Unclassifiable", hint: "Missing a value (e.g. character) the template needs — resolve it below" },
  { key: "blocked", label: "Blocked", hint: "Can't be applied for any reason — collision, unclassifiable, over-length, locked, etc." },
  { key: "in_place", label: "Already In Place", hint: "Already matches the destination template — nothing to do" },
];

const KIND_LABEL: Record<ReorganizeMoveKind, string> = {
  move: "move",
  rename: "rename",
  case_rename: "case rename",
  in_place: "in place",
  merge: "merge",
};

// A row the user is actively resolving via an override stays visible in
// whatever tab they're on, even once the override makes it eligible and it
// would otherwise fall out of that tab (e.g. Blocked) — otherwise the row
// vanishes the moment it becomes selectable and the user never sees the
// checkbox appear (STUDIO-182).
function matchesFilter(e: ReorganizeEntry, tab: FilterTab, hasOverride: boolean): boolean {
  if (hasOverride) return true;
  switch (tab) {
    case "all": return true;
    // Only entries that will actually move on Apply right now — a move-kind
    // entry that's still blocked belongs under Blocked/Collisions/
    // Unclassifiable instead (STUDIO-164).
    case "moves": return ["move", "rename", "case_rename"].includes(e.kind) && e.eligible;
    case "collisions": return e.collision;
    case "unclassifiable": return e.unclassifiable;
    case "blocked": return !e.eligible;
    case "in_place": return e.kind === "in_place";
  }
}

const COLLISION_EXPLANATIONS: Record<ReorganizeCollisionKind, string> = {
  none: "",
  exact: "Another model already resolves to this exact destination path.",
  case_only: "Another model's destination path differs only by letter case — that collides on case-insensitive filesystems.",
  unicode_only: "Another model's destination path differs only by Unicode normalization (e.g. accented characters) — that collides on some filesystems.",
  same_destination: "Another model resolves to this same destination. This does not mean their files are duplicates.",
};

interface BlockerFlag {
  label: string;
  explanation: string;
}

/** Blocker/flag chips for a single entry, each with a plain-English
 *  explanation (STUDIO-162) — previously chips were bare codes like
 *  "locked" or "over-length" with no way to know why or what to do. */
function blockerFlags(e: ReorganizeEntry): BlockerFlag[] {
  const flags: BlockerFlag[] = [];
  if (e.ambiguous_package) {
    flags.push({
      label: "package boundary",
      explanation: "The model's character does not match a physical ancestor folder, so Reorganize cannot safely determine the release package boundary.",
    });
  }
  if (e.collision) {
    flags.push({
      label: `collision: ${e.collision_kind}`,
      explanation: `${COLLISION_EXPLANATIONS[e.collision_kind]}${
        e.collision_with.length ? ` Conflicts with ${e.collision_with.length} other model(s).` : ""
      }`,
    });
  }
  if (e.unclassifiable) {
    flags.push({
      label: "unclassifiable",
      explanation: e.missing_fields.length
        ? `Missing a value for: ${e.missing_fields.join(", ")}. Fill it in below to resolve.`
        : "The destination template needs a value this model doesn't have. Fill it in below to resolve.",
    });
  }
  if (e.over_length) {
    flags.push({ label: "over-length", explanation: "The proposed path is too long for the filesystem. Shorten a field below (e.g. use a suffix) to resolve." });
  }
  if (e.reserved_name) {
    flags.push({ label: "reserved name", explanation: "The proposed name is reserved by the operating system (e.g. CON, NUL). Adjust a field below to resolve." });
  }
  if (e.overlaps_other) {
    flags.push({ label: "overlap", explanation: "This model's files overlap with another model's files on disk. Needs a rescan or manual disk fix — not resolvable here." });
  }
  if (e.spans_multiple_dirs) {
    const directories = e.source_directories.length
      ? ` Source directories: ${e.source_directories.join("; ")}.`
      : "";
    flags.push({
      label: "multi-dir",
      explanation: `This model's STL files are spread across multiple directories, so Reorganize can't safely move it as one unit.${directories} Needs a manual disk fix.`,
    });
  }
  if (e.is_symlink) {
    flags.push({ label: "symlink", explanation: "One or more files are symlinks — Reorganize skips symlinked files to avoid moving something it doesn't actually own." });
  }
  if (e.escapes_scan_root) {
    flags.push({ label: "escapes root", explanation: "The proposed destination would land outside the scan root, which Reorganize refuses to do for safety." });
  }
  if (e.missing_files_on_disk) {
    flags.push({ label: "missing files", explanation: "One or more of this model's files are missing on disk. Rescan the library to refresh what's tracked." });
  }
  if (e.locked) {
    flags.push({ label: "locked", explanation: "This model is locked and won't be touched by Reorganize until it's unlocked." });
  }
  return flags;
}

/** Which blockers a user can resolve here (the rest need a rescan / disk fix). */
function isResolvable(e: ReorganizeEntry): boolean {
  return e.unclassifiable || e.collision || e.over_length || e.reserved_name;
}

export default function ReorganizePage() {
  const { settings } = useAppSettings();
  const [template, setTemplate] = useState(DEFAULT_TEMPLATE);
  // Seed the field from the saved library setting once it's loaded (async),
  // but only until the user starts typing their own one-off template.
  const [templateTouched, setTemplateTouched] = useState(false);
  useEffect(() => {
    if (!templateTouched && settings.reorganize_template) {
      setTemplate(settings.reorganize_template);
    }
  }, [settings.reorganize_template, templateTouched]);
  const [overrides, setOverrides] = useState<Record<number, ReorganizeOverride>>({});
  const [preview, setPreview] = useState<ReorganizePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTabRaw] = useState<FilterTab>("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[0]);
  // Switching tabs/rebuilding/changing page size always resets to page 1
  // (ADDENDUM §6) — the row set underneath changed, so a stale page index
  // would silently show an empty or wrong slice.
  const setTab = (t: FilterTab) => { setTabRaw(t); setPage(1); };
  const changePageSize = (size: number) => { setPageSize(size); setPage(1); };
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [creatorFilter, setCreatorFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const [applyMsg, setApplyMsg] = useState<string | null>(null);
  const [applyErr, setApplyErr] = useState<string | null>(null);
  const [lastApply, setLastApply] = useState<ReorganizeApplyResult | null>(null);
  const { toast } = useToast();

  // Scanning is a deliberate, user-triggered action (STUDIO-155) — nothing
  // fetches until the user clicks Build/Retry/Rebuild. `runToken` bumps on
  // each of those triggers; the debounced effect below only fires once
  // `started` is true, so template/override edits still auto-refresh an
  // *existing* plan without the page auto-scanning on mount.
  const [started, setStarted] = useState(false);
  const [runToken, setRunToken] = useState(0);
  const cancelledRef = useRef(false);
  const runReorgScan = () => {
    cancelledRef.current = false; setStarted(true); setRunToken((t) => t + 1);
    // Rebuild Plan resets to tab "All", page 1 (ADDENDUM §6) — keeps whatever
    // page size was last selected.
    setTabRaw("all"); setPage(1);
  };
  const cancelReorgScan = () => { cancelledRef.current = true; setLoading(false); setStarted(false); };

  const hasOverrides = Object.keys(overrides).length > 0;

  useEffect(() => {
    if (!started) return;
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const data = hasOverrides
          ? await api.reorganize.previewWithOverrides({ template, overrides })
          : await api.reorganize.preview(template);
        if (!cancelled && !cancelledRef.current) {
          setPreview(data); setError(null);
          toast("Reorganize plan ready.", "success");
        }
      } catch (e) {
        if (!cancelled && !cancelledRef.current) {
          setError(e instanceof ApiError ? e.message : "Failed to load preview");
          if (e instanceof ApiError && e.status === 400) setPreview(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started, template, overrides, hasOverrides, runToken]);

  const creatorOptions = useMemo(() => {
    const creators = new Map<string, string>();
    for (const entry of preview?.entries ?? []) {
      const value = entry.creator_id === null ? `name:${entry.creator_name}` : `id:${entry.creator_id}`;
      creators.set(value, entry.creator_name || "Unknown creator");
    }
    return [...creators.entries()]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [preview]);

  const creatorFiltered = useMemo(() => {
    const entries = preview?.entries ?? [];
    if (creatorFilter === "all") return entries;
    return entries.filter((entry) =>
      creatorFilter === (entry.creator_id === null ? `name:${entry.creator_name}` : `id:${entry.creator_id}`),
    );
  }, [preview, creatorFilter]);

  useEffect(() => {
    if (creatorFilter !== "all" && !creatorOptions.some((option) => option.value === creatorFilter)) {
      setCreatorFilter("all");
      setPage(1);
    }
  }, [creatorFilter, creatorOptions]);

  const creatorVisibleIds = useMemo(
    () => new Set(creatorFiltered.map((entry) => entry.model_id)),
    [creatorFiltered],
  );

  const visible = useMemo(
    () => creatorFiltered.filter((e) => matchesFilter(e, tab, Boolean(overrides[e.model_id]))),
    [creatorFiltered, tab, overrides],
  );

  const totalPages = Math.max(1, Math.ceil(visible.length / pageSize));
  // Clamp when the filtered set shrinks out from under the current page
  // (e.g. a resolved row moves tabs, or a smaller page size is picked).
  useEffect(() => {
    setPage((p) => Math.min(p, totalPages));
  }, [totalPages]);

  const paged = useMemo(
    () => visible.slice((page - 1) * pageSize, page * pageSize),
    [visible, page, pageSize],
  );
  const rangeStart = visible.length === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, visible.length);
  const pageNumbers = useMemo(() => paginationRange(page, totalPages), [page, totalPages]);

  const eligibleIds = useMemo(
    () => new Set((preview?.entries ?? []).filter((e) => e.eligible && e.kind !== "in_place").map((e) => e.model_id)),
    [preview],
  );

  // Selectable rows on the *current page* (STUDIO-160, extended for
  // pagination) — "select all" only touches what's visible on screen, so
  // switching tabs or pages doesn't silently select rows the user never saw.
  const visibleSelectableIds = useMemo(
    () => paged.filter((e) => eligibleIds.has(e.model_id)).map((e) => e.model_id),
    [paged, eligibleIds],
  );
  const allVisibleSelected =
    visibleSelectableIds.length > 0 && visibleSelectableIds.every((id) => selected.has(id));
  const toggleSelectAllVisible = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        visibleSelectableIds.forEach((id) => next.delete(id));
      } else {
        visibleSelectableIds.forEach((id) => next.add(id));
      }
      return next;
    });

  // Drop selections that are no longer eligible or are hidden by the creator filter.
  useEffect(() => {
    setSelected((prev) => new Set(
      [...prev].filter((id) => eligibleIds.has(id) && creatorVisibleIds.has(id)),
    ));
  }, [eligibleIds, creatorVisibleIds]);

  const toggle = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleSelect = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const setOverride = (id: number, patch: Partial<ReorganizeOverride>) =>
    setOverrides((prev) => {
      const merged = { ...prev[id], ...patch };
      // Drop empty fields; remove the entry entirely if nothing's left.
      const cleaned: ReorganizeOverride = {};
      for (const [k, v] of Object.entries(merged)) {
        if (v && String(v).trim()) (cleaned as Record<string, string>)[k] = v as string;
      }
      const next = { ...prev };
      if (Object.keys(cleaned).length) next[id] = cleaned;
      else delete next[id];
      return next;
    });

  // AI-assisted field suggestions (STUDIO-186) — advisory only. A suggestion
  // only prefills the override fields above; it never applies on its own.
  const [aiSuggesting, setAiSuggesting] = useState<Set<number>>(new Set());
  const [aiSuggestErr, setAiSuggestErr] = useState<Record<number, string>>({});
  const suggestWithAi = async (id: number) => {
    if (!preview) return;
    setAiSuggesting((prev) => new Set(prev).add(id));
    setAiSuggestErr((prev) => { const next = { ...prev }; delete next[id]; return next; });
    try {
      const res = await api.reorganize.aiSuggest(preview.manifest_id, [id]);
      if (res.llm_status !== "ok") {
        setAiSuggestErr((prev) => ({ ...prev, [id]: res.llm_detail || "AI suggestion unavailable" }));
        return;
      }
      const sug = res.suggestions.find((s) => s.model_id === id);
      if (!sug) {
        setAiSuggestErr((prev) => ({ ...prev, [id]: "No suggestion returned for this row" }));
        return;
      }
      const patch: Partial<ReorganizeOverride> = {};
      if (sug.creator) patch.creator = sug.creator;
      if (sug.character) patch.character = sug.character;
      if (sug.title) patch.title = sug.title;
      setOverride(id, patch);
    } catch (e) {
      setAiSuggestErr((prev) => ({ ...prev, [id]: e instanceof ApiError ? e.message : "AI suggestion failed" }));
    } finally {
      setAiSuggesting((prev) => { const next = new Set(prev); next.delete(id); return next; });
    }
  };

  const runApply = async () => {
    if (!preview || selected.size === 0) return;
    setBusy(true); setApplyMsg(null); setApplyErr(null);
    try {
      const res = await api.reorganize.apply(preview.manifest_id, [...selected]);
      setLastApply(res);
      setApplyMsg(`Moved ${res.moved_files} file(s) across ${res.moved_models} model(s).`);
      setSelected(new Set());
      // Files are now in their new homes — re-preview reflects reality.
      const fresh = await api.reorganize.preview(template);
      setPreview(fresh); setOverrides({});
    } catch (e) {
      setApplyErr(e instanceof ApiError ? e.message : "Apply failed");
    } finally {
      setBusy(false);
    }
  };

  const runUndo = async () => {
    if (!lastApply) return;
    setBusy(true); setApplyMsg(null); setApplyErr(null);
    try {
      const res = await api.reorganize.undo(lastApply.manifest_id);
      const skip = res.skipped.length ? `, ${res.skipped.length} skipped` : "";
      setApplyMsg(`Reversed ${res.reversed_files} file(s)${skip}.`);
      setLastApply(null);
      const fresh = await api.reorganize.preview(template);
      setPreview(fresh);
    } catch (e) {
      setApplyErr(e instanceof ApiError ? e.message : "Undo failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Reorganize Library</h1>
        <p className="text-sm text-text-secondary-alt mt-1">
          Nothing is scanned until you build a plan. Building only reads your
          library; applying is a separate, explicit step.
        </p>
      </div>

      {/* Template editor */}
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm text-text-primary-alt2">
          Destination template
          {loading && preview && (
            <span className="flex items-center gap-1 text-xs text-text-secondary-alt">
              <Loader2 size={12} className="animate-spin" /> Updating preview…
            </span>
          )}
        </label>
        <input
          type="text"
          value={template}
          onChange={(e) => { setTemplate(e.target.value); setTemplateTouched(true); }}
          className="w-full bg-panel border border-border rounded px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:border-accent-start"
          aria-label="Destination template"
        />
        <div className="text-xs text-text-secondary-alt">
          Tokens: <code className="text-indigo-400">{"{creator}"}</code>{" "}
          <code className="text-indigo-400">{"{character}"}</code>{" "}
          <code className="text-indigo-400">{"{scale}"}</code>{" "}
          <code className="text-indigo-400">{"{title}"}</code> — separate levels with <code>/</code>.
        </div>
        {settings.reorganize_package_mode_enabled && (
          <div className="text-xs text-indigo-300">
            Package preservation is on: Reorganize uses the creator/character prefix
            and keeps each release package's name and internal folders unchanged.
          </div>
        )}
        {error && preview && <div className="text-sm text-rose-400">{error}</div>}
      </div>

      {!started && !loading && (
        <div className="flex flex-col items-center justify-center text-center py-14 px-8 border border-dashed border-border-subtle rounded-xl bg-panel/40">
          <div className="w-13 h-13 rounded-full bg-indigo-950/60 flex items-center justify-center mb-4" style={{ width: 52, height: 52 }}>
            <RefreshCw size={22} className="text-indigo-400" />
          </div>
          <p className="text-sm font-semibold text-text-primary mb-1">No plan yet</p>
          <p className="text-sm text-text-secondary-alt max-w-sm mb-4">
            Build a plan to see proposed moves against your template above. This reads
            your library only — no files move until you apply.
          </p>
          <button
            type="button"
            onClick={runReorgScan}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-accent-end hover:bg-accent-start text-white text-sm font-semibold transition-colors"
          >
            <RefreshCw size={14} /> Build Reorganize Plan
          </button>
        </div>
      )}

      {loading && !preview && (
        <div className="flex items-center gap-3.5 bg-indigo-950/20 border border-indigo-900/50 rounded-xl px-4 py-4">
          <Loader2 size={18} className="animate-spin text-indigo-400 shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-text-primary">Building reorganize plan…</p>
            <p className="text-xs text-text-secondary-alt mt-0.5">
              Scanning your library against the destination template. This can take a
              few minutes on large libraries.
            </p>
          </div>
          <button
            type="button"
            onClick={cancelReorgScan}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-panel-secondary border border-border text-text-primary-alt2 text-xs shrink-0"
          >
            <Square size={11} /> Cancel
          </button>
        </div>
      )}

      {!loading && error && !preview && (
        <div className="flex flex-col items-center justify-center text-center py-14 px-8 border border-dashed border-rose-900/40 rounded-xl bg-rose-950/10">
          <div className="w-13 h-13 rounded-full bg-rose-950/40 flex items-center justify-center mb-4" style={{ width: 52, height: 52 }}>
            <AlertCircle size={22} className="text-rose-300" />
          </div>
          <p className="text-sm font-semibold text-text-primary mb-1">Couldn't build the plan</p>
          <p className="text-sm text-text-secondary-alt max-w-sm mb-4">{error}</p>
          <button
            type="button"
            onClick={runReorgScan}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-accent-end hover:bg-accent-start text-white text-sm font-semibold transition-colors"
          >
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      )}

      {preview && (
        <>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={runReorgScan}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-panel-secondary border border-border text-text-primary-alt2 text-xs"
            >
              <RefreshCw size={11} /> Rebuild Plan
            </button>
          </div>
          <ReorganizeStatsBar stats={preview.stats} />

          <div className="flex items-center gap-2">
            <label htmlFor="creator-filter" className="text-sm text-text-primary-alt2">Creator</label>
            <select
              id="creator-filter"
              aria-label="Filter by creator"
              value={creatorFilter}
              onChange={(event) => { setCreatorFilter(event.target.value); setPage(1); }}
              className="min-w-56 bg-panel border border-border rounded px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-accent-start"
            >
              <option value="all">All creators</option>
              {creatorOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>

          {/* Filter tabs */}
          <div className="flex gap-1 flex-wrap border-b border-border-subtle">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setTab(f.key)}
                title={f.hint}
                className={`px-3 py-1.5 text-sm rounded-t ${
                  tab === f.key
                    ? "bg-panel-secondary text-text-primary border-b-2 border-accent-start"
                    : "text-text-secondary-alt hover:text-text-primary-alt2"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          {/* Page-size selector (ADDENDUM §6) */}
          <div className="flex items-center justify-end gap-2 text-xs text-text-secondary-alt">
            <span>Per page</span>
            <div className="flex rounded-lg overflow-hidden border border-border">
              {PAGE_SIZES.map((size) => (
                <button
                  key={size}
                  type="button"
                  onClick={() => changePageSize(size)}
                  aria-pressed={pageSize === size}
                  className={`px-2.5 py-1 text-xs ${
                    pageSize === size
                      ? "bg-accent-start text-white"
                      : "bg-panel-secondary text-text-primary-alt2 hover:text-text-primary"
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>

          {/* Manifest table */}
          <div className="space-y-1">
            {visibleSelectableIds.length > 0 && (
              <label className="flex items-center gap-2 text-xs text-text-secondary-alt py-1 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleSelectAllVisible}
                  aria-label={allVisibleSelected ? "Deselect all eligible" : "Select all eligible"}
                />
                {allVisibleSelected ? "Deselect all eligible" : `Select all eligible (${visibleSelectableIds.length})`}
              </label>
            )}
            {visible.length === 0 && (
              <div className="text-sm text-text-muted py-6 text-center">
                {creatorFilter === "all" ? "No models in this view." : "No models for this creator in this view."}
              </div>
            )}
            {paged.map((e) => {
              const flags = blockerFlags(e);
              const isOpen = expanded.has(e.model_id);
              const canSelect = eligibleIds.has(e.model_id);
              // Resolvable rows (fixable here via the override fields) get amber;
              // unresolvable ones (need a rescan or disk fix) stay rose (STUDIO-161)
              // — previously both looked identical orange, so users couldn't tell
              // at a glance what they could actually fix.
              const rowStyle = e.eligible
                ? "border-border-subtle"
                : isResolvable(e)
                  ? "border-amber-700/60 bg-amber-950/20"
                  : "border-rose-900/60 bg-rose-950/20";
              return (
                <div
                  key={e.model_id}
                  className={`rounded border ${rowStyle}`}
                >
                  <div className="w-full flex items-center gap-3 px-3 py-2">
                    {canSelect && (
                      <input
                        type="checkbox"
                        checked={selected.has(e.model_id)}
                        onChange={() => toggleSelect(e.model_id)}
                        aria-label={`Select ${e.model_name}`}
                        className="shrink-0"
                      />
                    )}
                    <button onClick={() => toggle(e.model_id)} className="flex items-center gap-3 text-left flex-1 min-w-0">
                      <span className="text-xs px-2 py-0.5 rounded bg-panel-secondary text-text-primary-alt2 shrink-0">
                        {KIND_LABEL[e.kind]}
                      </span>
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm text-text-primary-alt truncate">{e.model_name}</span>
                        {e.collision && (
                          <span
                            className="block text-xs text-text-muted truncate font-mono"
                            title={`Source: ${e.source_path}`}
                          >
                            Source: {e.source_path}
                          </span>
                        )}
                        <span className="block text-xs text-text-secondary-alt truncate font-mono">→ {e.proposed_dir}</span>
                        {e.shared_files.length > 0 && (
                          <span className={`block text-xs ${
                            e.character_package_ids.every((id) => selected.has(id))
                              ? "text-emerald-400"
                              : "text-amber-400"
                          }`}>
                            {e.shared_files.length} shared character file{e.shared_files.length === 1 ? "" : "s"}{" "}
                            {e.character_package_ids.every((id) => selected.has(id))
                              ? "will move with the complete character"
                              : `will remain unless all ${e.character_package_ids.length} packages are selected`}
                          </span>
                        )}
                      </span>
                    </button>
                    {flags.map((f) => (
                      <span
                        key={f.label}
                        title={f.explanation}
                        className={`text-xs px-2 py-0.5 rounded shrink-0 ${
                          isResolvable(e) ? "bg-amber-950 text-amber-300" : "bg-rose-950 text-rose-300"
                        }`}
                      >
                        {f.label}
                      </span>
                    ))}
                    {!e.eligible && isResolvable(e) && !isOpen && (
                      <span className="text-xs px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 shrink-0">
                        click to resolve
                      </span>
                    )}
                  </div>
                  {isOpen && (
                    <div className="px-3 pb-2 space-y-2 border-t border-border-subtle pt-2">
                      {e.files.map((f) => (
                        <div key={f.current_path} className="text-xs font-mono text-text-secondary-alt">
                          <span className="text-text-muted">{f.current_path}</span>
                          <span className="text-text-muted-alt"> → </span>
                          <span className="text-text-secondary">{f.proposed_path}</span>
                        </div>
                      ))}
                      {e.shared_files.length > 0 && (
                        <div className="pt-2 border-t border-border-subtle/60 space-y-1">
                          <div className="text-xs text-text-secondary">Shared character assets</div>
                          {e.shared_files.map((f) => (
                            <div key={f.current_path} className="text-xs font-mono text-text-secondary-alt">
                              <span className="text-text-muted">{f.current_path}</span>
                              <span className="text-text-muted-alt"> → </span>
                              <span className="text-text-secondary">{f.proposed_path}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {!e.eligible && flags.length > 0 && (
                        <div className="pt-2 border-t border-border-subtle/60">
                          <div className="text-xs text-text-secondary mb-1">Why</div>
                          <ul className="space-y-1">
                            {flags.map((f) => (
                              <li key={f.label} className="text-xs text-text-secondary-alt">
                                <span className={isResolvable(e) ? "text-amber-300" : "text-rose-300"}>{f.label}:</span>{" "}
                                {f.explanation}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {!e.eligible && isResolvable(e) && (
                        <div className="pt-2 border-t border-border-subtle/60">
                          <div className="flex items-center justify-between mb-1">
                            <div className="text-xs text-text-secondary">Resolve</div>
                            {settings.reorganize_ai_suggestions_enabled && (e.unclassifiable || e.collision) && (
                              <button
                                type="button"
                                onClick={() => suggestWithAi(e.model_id)}
                                disabled={aiSuggesting.has(e.model_id)}
                                className="text-xs text-indigo-400 hover:text-indigo-300 disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                {aiSuggesting.has(e.model_id) ? "Suggesting…" : "Suggest with AI"}
                              </button>
                            )}
                          </div>
                          {aiSuggestErr[e.model_id] && (
                            <div className="text-xs text-rose-400 mb-1">{aiSuggestErr[e.model_id]}</div>
                          )}
                          {e.suggested_suffix && !overrides[e.model_id]?.suffix && (
                            <button
                              type="button"
                              onClick={() => setOverride(e.model_id, { suffix: e.suggested_suffix ?? undefined })}
                              className="text-xs text-indigo-400 hover:text-indigo-300 mb-2"
                            >
                              Use suggested suffix: {e.suggested_suffix}
                            </button>
                          )}
                          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                            {(["creator", "character", "scale", "title", "suffix"] as const).map((field) => (
                              <input
                                key={field}
                                type="text"
                                placeholder={field}
                                aria-label={`${field} for ${e.model_name}`}
                                value={overrides[e.model_id]?.[field] ?? ""}
                                onChange={(ev) => setOverride(e.model_id, { [field]: ev.target.value })}
                                className="bg-panel border border-border rounded px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-start"
                              />
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Pagination footer (ADDENDUM §6) — hidden when everything fits on one page */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between flex-wrap gap-2 pt-1 text-xs text-text-secondary-alt">
              <span>
                Showing {rangeStart}–{rangeEnd} of {visible.length}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  aria-label="Previous page"
                  className="px-2.5 py-1 rounded bg-panel-secondary border border-border text-text-primary-alt2 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Prev
                </button>
                {pageNumbers.map((p, i) =>
                  p === "ellipsis" ? (
                    <span key={`ellipsis-${i}`} className="px-1.5 text-text-muted">
                      …
                    </span>
                  ) : (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setPage(p)}
                      aria-label={`Page ${p}`}
                      aria-current={p === page ? "page" : undefined}
                      className={`px-2.5 py-1 rounded ${
                        p === page
                          ? "bg-accent-start text-white"
                          : "bg-panel-secondary border border-border text-text-primary-alt2 hover:text-text-primary"
                      }`}
                    >
                      {p}
                    </button>
                  ),
                )}
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  aria-label="Next page"
                  className="px-2.5 py-1 rounded bg-panel-secondary border border-border text-text-primary-alt2 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Apply / Undo */}
      <div className="pt-2 flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={runApply}
          disabled={busy || selected.size === 0}
          className={`px-4 py-2 rounded text-sm ${
            busy || selected.size === 0
              ? "bg-panel-secondary text-text-muted cursor-not-allowed"
              : "bg-accent-end text-white hover:bg-accent-start"
          }`}
        >
          {busy ? "Working…" : `Apply ${selected.size || ""}`.trim()}
        </button>
        {lastApply && (
          <button
            type="button"
            onClick={runUndo}
            disabled={busy}
            className="px-4 py-2 rounded text-sm bg-panel-secondary text-text-primary-alt hover:bg-panel-secondary disabled:opacity-50"
          >
            Undo last apply
          </button>
        )}
        {applyMsg && <span className="text-sm text-emerald-400">{applyMsg}</span>}
        {applyErr && <span className="text-sm text-rose-400">{applyErr}</span>}
      </div>
    </div>
  );
}

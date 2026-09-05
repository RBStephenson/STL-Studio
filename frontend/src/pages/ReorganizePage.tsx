import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, RefreshCw, Square, AlertCircle } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
import type {
  ReorganizeEntry,
  ReorganizePreview,
  ReorganizeOverride,
  ReorganizeApplyResult,
  ScanRoot,
} from "../api/client";
import ReorganizeStatsBar from "../components/reorganize/ReorganizeStatsBar";
import TemplateEditor from "../components/reorganize/TemplateEditor";
import DestinationTree from "../components/reorganize/DestinationTree";
import { KIND_LABEL, blockerFlags, isResolvable } from "../components/reorganize/entryFlags";

const DEBOUNCE_MS = 500;
const PAGE_SIZES = [20, 50, 100] as const;

type FilterTab = "all" | "moves" | "collisions" | "unclassifiable" | "blocked" | "in_place";
/** The list answers "which rows will move and can I fix them"; the tree answers
 *  "what will my library look like" (STUDIO-404). Same entries, same selection,
 *  different question — so they are view modes, not separate pages. */
type ViewMode = "list" | "tree";

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

// KIND_LABEL, COLLISION_EXPLANATIONS, blockerFlags and isResolvable moved to
// components/reorganize/entryFlags.ts (STUDIO-404) — the destination tree needs
// the same words for a blocked row, and a second copy of them here is exactly
// the drift STUDIO-406 was about. Behaviour is unchanged; they moved verbatim.

export default function ReorganizePage() {
  const { settings, loaded: settingsLoaded } = useAppSettings();
  // Starts empty rather than at a locally-declared default (STUDIO-406) — the
  // default is the server's now, and arrives with the settings fetch.
  const [template, setTemplate] = useState("");
  // Seed the field from the saved library setting once it's loaded (async),
  // falling back to the server's default when nothing is saved, and only until
  // the user starts typing their own one-off template.
  const [templateTouched, setTemplateTouched] = useState(false);
  useEffect(() => {
    if (templateTouched) return;
    const seed = settings.reorganize_template || settings.reorganize_template_default;
    if (seed) setTemplate(seed);
  }, [settings.reorganize_template, settings.reorganize_template_default, templateTouched]);
  const [overrides, setOverrides] = useState<Record<number, ReorganizeOverride>>({});
  const [preview, setPreview] = useState<ReorganizePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTabRaw] = useState<FilterTab>("all");
  // Deliberately NOT reset by Rebuild Plan, unlike tab and page (ADDENDUM §6).
  // Those reset because the row set underneath changed; which shape you want to
  // look at is a preference about yourself, and re-answering it after every
  // rebuild would be the annoying kind of helpful.
  const [view, setView] = useState<ViewMode>("list");
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
  const [scanRoots, setScanRoots] = useState<ScanRoot[]>([]);
  const [scanRootsLoading, setScanRootsLoading] = useState(true);
  const [scanRootsError, setScanRootsError] = useState(false);
  const [rootId, setRootId] = useState<number | undefined>();
  const { toast } = useToast();

  useEffect(() => {
    let cancelled = false;
    api.scan.roots()
      .then((roots) => {
        if (!cancelled) setScanRoots(roots);
      })
      .catch(() => {
        if (!cancelled) setScanRootsError(true);
      })
      .finally(() => {
        if (!cancelled) setScanRootsLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

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

  const changeRoot = (value: string) => {
    setRootId(value ? Number(value) : undefined);
    setPreview(null);
    setError(null);
    setOverrides({});
    setSelected(new Set());
    setExpanded(new Set());
    setCreatorFilter("all");
    setLastApply(null);
    setApplyMsg(null);
    setApplyErr(null);
    setTabRaw("all");
    setPage(1);
  };

  useEffect(() => {
    if (!started) return;
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const data = hasOverrides
          ? await api.reorganize.previewWithOverrides({ template, root_id: rootId, overrides })
          : await api.reorganize.preview(template, rootId);
        if (!cancelled && !cancelledRef.current) {
          setPreview(data); setError(null);
          toast("Reorganize plan ready.", "success");
        }
      } catch (e) {
        if (!cancelled && !cancelledRef.current) {
          // Deliberately keeps the last good preview (STUDIO-406). This effect
          // re-fires on every template keystroke, so a half-typed template
          // ("{creator}/{char") returns 400 — and clearing here threw away a
          // manifest that stat'd every file on disk, over a state that lasts
          // one keypress. The error renders inline above the table instead,
          // which is already how every non-400 failure behaves.
          setError(e instanceof ApiError ? e.message : "Failed to load preview");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started, template, rootId, overrides, hasOverrides, runToken]);

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

  // Bulk select/deselect for the tree (STUDIO-404). The tree hands over the ids
  // it means — already intersected with `eligibleIds` — so this stays a dumb
  // set operation and there is still only one definition of what's selectable.
  const setSelectionFor = (ids: number[], select: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) select ? next.add(id) : next.delete(id);
      return next;
    });

  // Package mode is a manifest-wide setting mirrored onto every entry, so any
  // entry answers for the plan — but read it off the entries rather than the
  // local setting, which can have been toggled since the plan was built.
  const packageMode = useMemo(
    () => (preview?.entries ?? []).some((e) => e.package_mode),
    [preview],
  );

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
      const fresh = await api.reorganize.preview(template, rootId);
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
      const fresh = await api.reorganize.preview(template, rootId);
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

      {/* Scope and template editor */}
      <div className="space-y-2">
        <label htmlFor="reorganize-scan-root" className="block text-sm text-text-primary-alt2">
          Scan root
        </label>
        <select
          id="reorganize-scan-root"
          aria-label="Scan root"
          value={rootId ?? ""}
          onChange={(e) => changeRoot(e.target.value)}
          disabled={scanRootsLoading || busy}
          className="w-full bg-panel border border-border rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-start disabled:opacity-60"
        >
          <option value="">All scan roots</option>
          {scanRoots.map((root) => (
            <option key={root.id} value={root.id}>
              {root.name ? `${root.name} (${root.path})` : root.path}{root.enabled ? "" : " (disabled)"}
            </option>
          ))}
        </select>
        <p className="text-xs text-text-secondary-alt">
          Build against every configured scan root or limit the plan to one root.
        </p>
        {scanRootsError && (
          <p className="text-xs text-amber-400">
            Scan roots could not be loaded. Reorganize will continue using all scan roots.
          </p>
        )}
        <label className="flex items-center gap-2 text-sm text-text-primary-alt2">
          Destination template
          {loading && preview && (
            <span className="flex items-center gap-1 text-xs text-text-secondary-alt">
              <Loader2 size={12} className="animate-spin" /> Updating preview…
            </span>
          )}
        </label>
        {/* Held back until the settings fetch lands (STUDIO-406), for the same
            reason the Settings copy is: the template seeds from the server, so
            rendering early would flash "the template is empty" over a library
            that has a perfectly good one. */}
        {settingsLoaded ? (
          <TemplateEditor
            value={template}
            onChange={(next) => { setTemplate(next); setTemplateTouched(true); }}
            rootId={rootId}
            defaultTemplate={settings.reorganize_template_default}
            scopeNote={
              <>
                This template applies to <strong>this plan only</strong> and is not saved.
                It starts from your saved template;{" "}
                <a href="/settings#library" className="text-indigo-400 hover:text-indigo-300 underline">
                  change that in Settings
                </a>{" "}
                to affect new creator folders, import moves and the unorganized badge too.
              </>
            }
          />
        ) : (
          <div className="h-9 rounded bg-panel-inset border border-border animate-pulse" />
        )}
        <div className="rounded-lg border border-border-subtle bg-panel/60 px-3 py-2 text-xs text-text-secondary-alt space-y-1">
          <p>
            Directory slugify is {settings.reorganize_slugify ? "on" : "off"}: destination
            folders {settings.reorganize_slugify
              ? "are lowercased and hyphenated"
              : "keep their original casing and spacing"}.{" "}
            <a href="/settings#library" className="text-indigo-400 hover:text-indigo-300 underline">
              Change in Settings
            </a>
          </p>
          <p>
            After a successful apply, source folders left empty by the selected moves are removed.
          </p>
        </div>
        {/* The package-mode note lives in TemplateEditor now (STUDIO-402): it
            keys off `package_mode` in the preview response rather than the
            local setting, and it belongs next to the template it's telling you
            is inert. */}
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

          {/* Filter tabs, with the list/tree toggle alongside them (STUDIO-404)
              — both views read the same filtered set, so the tabs govern both. */}
          <div className="flex items-end justify-between gap-3 flex-wrap border-b border-border-subtle">
            <div className="flex gap-1 flex-wrap">
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
            <div className="flex rounded-lg overflow-hidden border border-border mb-1.5 shrink-0">
              {([
                { key: "list" as const, label: "List", hint: "Per-model rows — audit, resolve and select individual models" },
                { key: "tree" as const, label: "Tree", hint: "The proposed folder structure — judge the shape of the result" },
              ]).map((mode) => (
                <button
                  key={mode.key}
                  type="button"
                  onClick={() => setView(mode.key)}
                  aria-pressed={view === mode.key}
                  title={mode.hint}
                  className={`px-2.5 py-1 text-xs ${
                    view === mode.key
                      ? "bg-accent-start text-white"
                      : "bg-panel-secondary text-text-primary-alt2 hover:text-text-primary"
                  }`}
                >
                  {mode.label}
                </button>
              ))}
            </div>
          </div>

          {/* Page-size selector (ADDENDUM §6) — the tree doesn't paginate, it
              lazily expands, so this has nothing to say about it. */}
          {view === "list" && (
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
          )}

          {view === "tree" && (
            <DestinationTree
              entries={visible}
              selectableIds={eligibleIds}
              selected={selected}
              onSelect={setSelectionFor}
              packageMode={packageMode}
            />
          )}

          {/* Manifest table */}
          {view === "list" && (
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
                      {/* Eligible rows get the same fields (STUDIO-400): a row can
                          classify successfully and still classify WRONG, and before
                          this the only fix was editing the global template. Blocked
                          rows that no override can repair — locked, symlink,
                          multi-dir, overlaps, missing files, escapes-root — are
                          deliberately still excluded: typing a character can't
                          unlock a model, so the form would only buy a full manifest
                          rebuild that cannot change the outcome. */}
                      {(e.eligible || isResolvable(e)) && (
                        <div className="pt-2 border-t border-border-subtle/60">
                          <div className="flex items-center justify-between mb-1">
                            <div className="text-xs text-text-secondary">
                              {e.eligible ? "Adjust" : "Resolve"}
                            </div>
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
          )}

          {/* Pagination footer (ADDENDUM §6) — hidden when everything fits on one page */}
          {view === "list" && totalPages > 1 && (
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

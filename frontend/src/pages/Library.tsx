import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams, useNavigate, useLocation, Link } from "react-router-dom";
import { Search, SlidersHorizontal, AlertCircle, Tag, X, Bookmark, BookmarkPlus, Star, Printer, FolderPlus, ArrowRight, EyeOff, Package, GripVertical, Layers, Sparkles, Keyboard } from "lucide-react";
import {
  DndContext, DragOverlay, PointerSensor, useSensor, useSensors,
  useDraggable, useDroppable, pointerWithin,
  DragStartEvent, DragEndEvent,
} from "@dnd-kit/core";
import { api, Model, Creator, ModelStats, Collection, FilterPreset, LibrarySort, PRINT_STATUS_LABELS } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import ModelCard from "../components/ModelCard";
import ScanButton from "../components/ScanButton";
import BulkTagBar from "../components/BulkTagBar";
import HelpLink from "../components/HelpLink";
import { useToast } from "../context/ToastContext";
import { nextTagParams } from "../utils/tagFilter";
import { nextSelection } from "../utils/selection";
import { modelLinkTo } from "../utils/modelLink";
import { useLibraryKeyboard } from "../hooks/useLibraryKeyboard";
import ShortcutsOverlay from "../components/ShortcutsOverlay";

const SITES = ["thingiverse", "printables", "myminifactory", "cults3d", "gumroad", "thangs", "makerworld", "other"];

// Last applied Library filter querystring, remembered across navigation so that
// returning to the Library — via the navbar link, an in-page back, or browser
// Back — resumes the prior filter set instead of dropping to the unfiltered view
// (#288). "Clear all" removes this so an intentional reset stays reset.
const LIBRARY_QUERY_KEY = "library_query";

// Compact tri-state toggle: "all" | "1" | "0"
function TriToggle({ label, value, onChange }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const opts: { val: string; label: string }[] = [
    { val: "", label: "All" },
    { val: "1", label: "Yes" },
    { val: "0", label: "No" },
  ];
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-gray-500">{label}</span>
      <div className="flex rounded overflow-hidden border border-gray-700">
        {opts.map((o) => (
          <button
            key={o.val}
            onClick={() => onChange(o.val)}
            className={`px-2 py-1 text-xs transition-colors ${
              value === o.val
                ? "bg-indigo-600 text-white"
                : "bg-gray-800 text-gray-400 hover:text-gray-200"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function PaginationBar({ page, totalPages, onPage, className = "mt-8" }: { page: number; totalPages: number; onPage: (p: number) => void; className?: string }) {
  const [draft, setDraft] = useState(String(page));

  useEffect(() => { setDraft(String(page)); }, [page]);

  const btnCls = "px-3 py-1.5 rounded bg-gray-900 border border-gray-700 text-sm disabled:opacity-40 hover:border-gray-500 transition-colors";

  function commit(raw: string) {
    const n = parseInt(raw, 10);
    if (!isNaN(n)) onPage(Math.min(totalPages, Math.max(1, n)));
  }

  return (
    <div className={`flex items-center justify-center gap-2 ${className}`}>
      <button onClick={() => onPage(page - 1)} disabled={page === 1} className={btnCls}>Prev</button>
      <div className="flex items-center gap-1.5 text-sm text-gray-400">
        <input
          type="text"
          inputMode="numeric"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(e) => { if (e.key === "Enter") { commit(draft); (e.target as HTMLInputElement).blur(); } }}
          className="w-12 text-center rounded bg-gray-900 border border-gray-600 py-1 text-sm text-white focus:outline-none focus:border-indigo-500"
        />
        <span>/ {totalPages}</span>
      </div>
      <button onClick={() => onPage(page + 1)} disabled={page === totalPages} className={btnCls}>Next</button>
    </div>
  );
}

/** Wraps a library card so it can be dragged onto another card to form a variant
 *  group. The drag listeners live on a small hover grip (bottom-left) so plain
 *  clicks still navigate and the card's other hover controls keep working.
 *  Group cards (variant_count > 1) can be dropped onto but not dragged — merging
 *  whole groups is a separate follow-up. */
function DraggableCard({ model, draggingCreatorId, children }: {
  model: Model;
  draggingCreatorId: number | null;
  children: React.ReactNode;
}) {
  const isGroup = (model.variant_count ?? 1) > 1;
  const { setNodeRef: dragRef, listeners, attributes, isDragging } =
    useDraggable({ id: model.id, disabled: isGroup });
  const { setNodeRef: dropRef, isOver } = useDroppable({ id: model.id });
  const setRefs = useCallback((el: HTMLElement | null) => {
    dragRef(el); dropRef(el);
  }, [dragRef, dropRef]);

  // Grouping is per-creator, so only same-creator cards are valid drop targets.
  const sameCreator = draggingCreatorId != null && draggingCreatorId === (model.creator_id ?? -1);
  const validTarget = isOver && sameCreator && !isDragging;

  return (
    <div
      ref={setRefs}
      className={`relative group/drag rounded-lg transition-shadow ${isDragging ? "opacity-40" : ""} ${
        validTarget ? "ring-2 ring-indigo-400" : ""
      }`}
    >
      {!isGroup && (
        <button
          {...listeners}
          {...attributes}
          title="Drag onto another model to group them as variants"
          aria-label="Drag to group"
          className="absolute bottom-2 left-2 z-20 p-1 rounded bg-black/60 hover:bg-black/90 text-gray-300 hover:text-white cursor-grab active:cursor-grabbing touch-none opacity-0 group-hover/drag:opacity-100 transition-opacity"
        >
          <GripVertical size={14} />
        </button>
      )}
      {children}
    </div>
  );
}

export default function Library() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();

  // All filter state lives in the URL
  const page         = Number(searchParams.get("page") ?? 1);
  const search       = searchParams.get("q") ?? "";
  const creatorId    = searchParams.get("creator_id") ?? "";
  const excludeCreatorId = searchParams.get("exclude_creator_id") ?? "";
  const site         = searchParams.get("source_site") ?? "";
  const activeTag    = searchParams.get("tag") ?? "";
  const excludeTag   = searchParams.get("exclude_tag") ?? "";
  const needsReview  = searchParams.get("needs_review") === "1";
  const nsfwParam    = searchParams.get("nsfw") ?? "";        // "" | "1" | "0"
  const thumbParam   = searchParams.get("has_thumbnail") ?? ""; // "" | "1" | "0"
  const favParam     = searchParams.get("is_favorite") === "1";
  const printStatusParam = searchParams.get("print_status") ?? "";
  const excludedParam = searchParams.get("excluded") === "1";
  const minRating    = searchParams.get("min_rating") ?? "";  // "" | "1".."5" (#167)
  const addedDays    = searchParams.get("added_days") ?? ""; // "Recently added" window (#170)
  const sortParam    = searchParams.get("sort") ?? "";       // "" | "name" | "added" | "creator" (#247)

  // Update one or more filter params in a single history entry and reset to
  // page 1. Multi-key form serves the mutually exclusive pairs
  // (creator_id/exclude_creator_id, tag/exclude_tag). Page itself goes
  // through setPage, never through here.
  const setParams = (updates: Record<string, string>) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [key, value] of Object.entries(updates)) {
        if (value) next.set(key, value); else next.delete(key);
      }
      next.delete("page");
      return next;
    });
  };
  const setParam = (key: string, value: string) => setParams({ [key]: value });

  // Search is debounced (#220): the input binds to local state for instant
  // feedback, and the `q` URL param is written ~250 ms after the last keystroke
  // with { replace: true } so typing doesn't fire a fetch per character or push
  // a history entry per character (Back used to step through "a", "ak", …).
  const [searchInput, setSearchInput] = useState(search);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep the input in sync when `q` changes from outside the box (clear-filters,
  // back/forward navigation, applying a preset). While typing, `q` is stale
  // between debounce flushes so this effect doesn't fight the local state. Any
  // pending debounce is dropped here too: an external `q` change supersedes a
  // half-typed value, so a late timer mustn't resurrect it (e.g. type then Back).
  useEffect(() => {
    setSearchInput(search);
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
  }, [search]);
  useEffect(() => () => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
  }, []);
  const onSearchChange = (value: string) => {
    setSearchInput(value);
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set("q", value); else next.delete("q");
        next.delete("page");
        return next;
      }, { replace: true });
    }, 250);
  };

  const setPage = (p: number) => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      p > 1 ? next.set("page", String(p)) : next.delete("page");
      return next;
    });
  };

  const [models, setModels] = useState<Model[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<ModelStats | null>(null);
  const [creators, setCreators] = useState<Creator[]>([]);
  const [allTags, setAllTags] = useState<{ tag: string; count: number }[]>([]);
  const [tagSearch, setTagSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [showFilters, setShowFilters] = useState(
    !!(creatorId || excludeCreatorId || site || activeTag || excludeTag || nsfwParam || thumbParam)
  );
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const { settings, update: updateSettings, upsertPreset, deletePreset: removePreset } = useAppSettings();
  const presets = settings.filter_presets;
  const pageSize = settings.library_page_size;

  // Sort (#247): the URL is canonical, but when it carries no `sort` the persisted
  // default applies. addedDays ("Recently added") forces newest-first regardless.
  const effectiveSort = addedDays ? "added" : (sortParam || settings.library_sort);
  // Mirror a non-default persisted sort into the URL so presets capture it and the
  // detail-page Prev/Next (which only sees the origin URL) walks the same order.
  useEffect(() => {
    if (!sortParam && !addedDays && settings.library_sort && settings.library_sort !== "name") {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("sort", settings.library_sort);
        return next;
      }, { replace: true });
    }
  }, [sortParam, addedDays, settings.library_sort, setSearchParams]);

  // Changing the dropdown drives the URL and persists the new default server-side.
  const changeSort = (value: LibrarySort) => {
    void updateSettings({ library_sort: value });
    setParam("sort", value);
  };
  const [savingPreset, setSavingPreset] = useState(false);
  const [presetName, setPresetName] = useState("");
  const presetInputRef = useRef<HTMLInputElement>(null);
  // null = unknown/loading; number = how many scan folders are configured
  const [scanRootCount, setScanRootCount] = useState<number | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  // Model ids that have a painting guide → "Guide" badge (#263). Only fetched
  // when the painting module is enabled.
  const [guideModelIds, setGuideModelIds] = useState<Set<number>>(new Set());

  const scrollRestoredRef = useRef(false);
  const fetchIdRef = useRef(0);

  const fetchModels = useCallback(async () => {
    const fetchId = ++fetchIdRef.current;
    setLoading(true);
    try {
      // Variant grouping collapses non-representative variants. When filtering by
      // favorites/queue/printed (which apply to individual variants), disable grouping
      // so a flagged non-representative variant isn't hidden behind its group.
      const groupVariants = !favParam && !printStatusParam && !excludedParam;
      const params: Record<string, string | number | boolean> = { page, page_size: pageSize, group_variants: groupVariants };
      if (search)      params.q             = search;
      if (creatorId)   params.creator_id    = creatorId;
      if (excludeCreatorId) params.exclude_creator_id = excludeCreatorId;
      if (site)        params.source_site   = site;
      if (activeTag)   params.tag           = activeTag;
      if (excludeTag)  params.exclude_tag   = excludeTag;
      if (needsReview) params.needs_review  = true;
      if (nsfwParam)   params.nsfw          = nsfwParam === "1";
      if (thumbParam)  params.has_thumbnail = thumbParam === "1";
      if (favParam)    params.is_favorite   = true;
      if (printStatusParam) params.print_status  = printStatusParam;
      if (excludedParam) params.excluded    = true;
      if (minRating)   params.min_rating   = minRating;
      if (addedDays)   params.added_within_days = addedDays;
      if (effectiveSort && effectiveSort !== "name") params.sort = effectiveSort;
      const data = await api.models.list(params);
      if (fetchId !== fetchIdRef.current) return; // stale response — a newer fetch is in flight
      setModels(data.items);
      setTotal(data.total);
    } finally {
      if (fetchId === fetchIdRef.current) setLoading(false);
    }
  }, [page, pageSize, search, creatorId, excludeCreatorId, site, activeTag, excludeTag, needsReview, nsfwParam, thumbParam, favParam, printStatusParam, excludedParam, minRating, addedDays, effectiveSort]);

  useEffect(() => { fetchModels(); }, [fetchModels]);
  useEffect(() => { api.scan.roots().then((r) => setScanRootCount(r.length)).catch(() => setScanRootCount(null)); }, []);
  useEffect(() => { api.models.creators().then(setCreators).catch(() => {}); }, []);
  const refreshStats = useCallback(() => { api.models.stats().then(setStats).catch(() => {}); }, []);
  useEffect(() => { refreshStats(); }, [refreshStats]);
  useEffect(() => { api.models.tags().then(setAllTags).catch(() => {}); }, []);
  useEffect(() => { api.collections.list().then(setCollections).catch(() => {}); }, []);
  useEffect(() => {
    if (!settings.painting_guides_enabled) { setGuideModelIds(new Set()); return; }
    api.painting.guides.modelIds()
      .then((r) => setGuideModelIds(new Set(r.model_ids)))
      .catch(() => {});
  }, [settings.painting_guides_enabled]);

  // Restore scroll position when navigating back from a model detail page
  useEffect(() => {
    if (loading || scrollRestoredRef.current) return;
    const saved = sessionStorage.getItem("library_scroll");
    if (saved) {
      window.scrollTo({ top: Number(saved), behavior: "instant" });
      sessionStorage.removeItem("library_scroll");
      scrollRestoredRef.current = true;
    }
  }, [loading]);

  useEffect(() => {
    if (savingPreset) presetInputRef.current?.focus();
  }, [savingPreset]);

  const totalPages = Math.ceil(total / pageSize);
  const hasFilters = !!(creatorId || excludeCreatorId || site || activeTag || excludeTag || needsReview || nsfwParam || thumbParam || favParam || printStatusParam || minRating || addedDays);

  const visibleTags = allTags.filter(({ tag }) =>
    !tagSearch || tag.includes(tagSearch.toLowerCase())
  );

  // Current URL params as a preset-saveable string (excluding page)
  const currentQS = (() => {
    const p = new URLSearchParams(searchParams);
    p.delete("page");
    return p.toString();
  })();

  // --- Filter stickiness (#288) ---------------------------------------------
  // Resume the last filter set when the Library is entered with no params (the
  // navbar "Library" link, in-page back buttons, or browser Back to a bare `/`).
  // One-shot: only on mount, and only when the URL carries nothing, so it never
  // fights a deliberate navigation that already specifies filters.
  const queryRestoredRef = useRef(false);
  useEffect(() => {
    if (queryRestoredRef.current) return;
    queryRestoredRef.current = true;
    if (searchParams.toString()) return; // arrived with explicit params — respect them
    const saved = sessionStorage.getItem(LIBRARY_QUERY_KEY);
    if (saved) setSearchParams(new URLSearchParams(saved), { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Remember the active filter set so the next entry can resume it; an empty set
  // (incl. "Clear all") drops the saved query so a deliberate reset stays reset.
  // The restore effect above runs first and, when it restores, re-renders with
  // the resumed querystring — which lands back here and re-saves it.
  useEffect(() => {
    if (!queryRestoredRef.current) return;
    if (currentQS) sessionStorage.setItem(LIBRARY_QUERY_KEY, currentQS);
    else sessionStorage.removeItem(LIBRARY_QUERY_KEY);
  }, [currentQS]);

  const applyPreset = (preset: FilterPreset) => {
    const p = new URLSearchParams(preset.qs);
    p.delete("page");
    setSearchParams(p);
  };

  const deletePreset = (name: string) => {
    void removePreset(name);
  };

  const confirmSavePreset = () => {
    const name = presetName.trim();
    if (!name) return;
    void upsertPreset({ name, qs: currentQS });
    setSavingPreset(false);
    setPresetName("");
  };

  // Anchor for shift-click range selection — the last card toggled without Shift.
  const selectAnchorRef = useRef<number | null>(null);

  const toggleSelect = useCallback((id: number, shiftKey: boolean) => {
    setSelection(prev => nextSelection(prev, models.map(m => m.id), selectAnchorRef.current, id, shiftKey));
    if (!shiftKey) selectAnchorRef.current = id;
  }, [models]);

  const selectAll = useCallback(() => {
    setSelection(new Set(models.map(m => m.id)));
  }, [models]);

  const clearSelection = useCallback(() => {
    setSelection(new Set());
    selectAnchorRef.current = null;
  }, []);

  // After a model is excluded/restored, drop it from the current grid right away
  // and refresh the count chips (its own fetch keeps totals correct on next load).
  const handleRemoved = useCallback((id: number) => {
    setModels((prev) => prev.filter((m) => m.id !== id));
    setTotal((t) => Math.max(0, t - 1));
    refreshStats();
  }, [refreshStats]);

  // --- Keyboard navigation (#169) --------------------------------------------
  // WASD/arrows move a focus ring between cards, Enter opens, "/" focuses
  // search, "?" toggles a shortcuts overlay, Esc steps back out.
  const [showShortcuts, setShowShortcuts] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);

  // Measure the responsive grid's column count (2→6 across breakpoints) so
  // up/down jumps a whole row: count cards sharing the first card's offsetTop.
  const getColumns = useCallback(() => {
    const grid = gridRef.current;
    if (!grid) return 1;
    const cards = Array.from(grid.children) as HTMLElement[];
    if (cards.length === 0) return 1;
    const top = cards[0].offsetTop;
    let cols = 0;
    for (const c of cards) {
      if (c.offsetTop === top) cols++;
      else break;
    }
    return cols || 1;
  }, []);

  const openModel = useCallback((index: number) => {
    const m = models[index];
    if (!m) return;
    sessionStorage.setItem("library_scroll", String(window.scrollY));
    navigate(modelLinkTo(m), { state: { from: location.pathname + location.search } });
  }, [models, navigate, location]);

  const focusSearch = useCallback(() => {
    const el = searchInputRef.current;
    if (el) { el.focus(); el.select(); }
  }, []);

  const { focusedIndex, setFocusedIndex } = useLibraryKeyboard({
    count: models.length,
    getColumns,
    onActivate: openModel,
    onFocusSearch: focusSearch,
    onToggleHelp: () => setShowShortcuts((o) => !o),
    onEscape: () => {
      if (showShortcuts) { setShowShortcuts(false); return; }
      const active = document.activeElement;
      if (active instanceof HTMLElement && active.tagName === "INPUT") { active.blur(); return; }
      setFocusedIndex(-1);
    },
  });

  // Reset the focus ring whenever the result set changes (new page, filter, or
  // search) so it never points past the end of a shorter list.
  useEffect(() => { setFocusedIndex(-1); }, [models, setFocusedIndex]);

  // --- Drag to group ---------------------------------------------------------
  // Variant grouping is only on in the default view (favorites/queue/printed/
  // excluded views show flat, ungrouped cards), so drag-to-group is too.
  const dndEnabled = !favParam && !printStatusParam && !excludedParam;
  const [draggingId, setDraggingId] = useState<number | null>(null);
  // A pending merge of two ungrouped models, awaiting a group name from the user.
  const [pendingMerge, setPendingMerge] = useState<{ draggedId: number; targetId: number } | null>(null);
  const [mergeName, setMergeName] = useState("");
  const [merging, setMerging] = useState(false);
  const dndSensors = useSensors(
    // Small threshold so a plain click on the grip still isn't treated as a drag,
    // and ordinary card clicks never start one.
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );
  const draggingModel = draggingId != null ? models.find((m) => m.id === draggingId) ?? null : null;

  const onDragStart = (e: DragStartEvent) => setDraggingId(Number(e.active.id));

  const onDragEnd = async (e: DragEndEvent) => {
    setDraggingId(null);
    const draggedId = Number(e.active.id);
    if (!e.over) return;
    const targetId = Number(e.over.id);
    if (targetId === draggedId) return;

    const dragged = models.find((m) => m.id === draggedId);
    const target = models.find((m) => m.id === targetId);
    if (!dragged || !target) return;

    if (dragged.creator_id !== target.creator_id) {
      toast("Models must be from the same creator to group them.", "error");
      return;
    }

    // Always prompt so the user can confirm or rename the group.
    // Pre-fill with the target's existing character name if it has one,
    // otherwise seed from the target's display name.
    setMergeName(target.character || target.title || target.name);
    setPendingMerge({ draggedId: dragged.id, targetId: target.id });
  };

  const confirmMerge = async () => {
    if (!pendingMerge || merging) return;
    const name = mergeName.trim();
    if (!name) return;
    setMerging(true);
    try {
      // Anchor first, then the dragged model — if the second call fails, the
      // anchor is just a harmless single-member group rather than a split pair.
      await api.models.setGroupOverride(pendingMerge.targetId, name);
      await api.models.setGroupOverride(pendingMerge.draggedId, name);
      toast(`Grouped under "${name}".`, "success");
      setPendingMerge(null);
      fetchModels();
    } catch (err: any) {
      toast(err?.message || "Couldn't group these models — try again.", "error");
    } finally {
      setMerging(false);
    }
  };

  return (
    <div className="p-6">
      {/* First-run onboarding: no scan folders configured yet */}
      {scanRootCount === 0 && (
        <div className="mb-6 rounded-xl border border-indigo-700/60 bg-indigo-950/40 p-5">
          <div className="flex items-start gap-4">
            <div className="rounded-lg bg-indigo-600/20 p-2.5 text-indigo-300 shrink-0">
              <FolderPlus size={22} />
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-semibold text-gray-100">Welcome to STL Library 👋</h2>
              <p className="text-sm text-gray-400 mt-1">
                No folders are set up yet. Tell the app where your STL files live, then run a
                scan to build your library.
              </p>
              <Link
                to="/settings"
                className="inline-flex items-center gap-1.5 mt-3 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors"
              >
                Add your STL folder in Settings
                <ArrowRight size={15} />
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-gray-100">
            Library
            <HelpLink section="library" label="How the Library works" />
          </h1>
          <div className="flex items-center gap-3 mt-0.5">
            <p className="text-sm text-gray-500">{total.toLocaleString()} models</p>
            {stats && stats.needs_review > 0 && (
              <button
                onClick={() => setParam("needs_review", needsReview ? "" : "1")}
                className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded transition-colors ${
                  needsReview
                    ? "bg-amber-500 text-amber-950 font-medium"
                    : "bg-amber-950/50 text-amber-400 hover:bg-amber-900/50"
                }`}
              >
                <AlertCircle size={11} />
                {stats.needs_review} need review
              </button>
            )}
            {stats && stats.favorites > 0 && (
              <button
                onClick={() => setParam("is_favorite", favParam ? "" : "1")}
                className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded transition-colors ${
                  favParam
                    ? "bg-yellow-500 text-yellow-950 font-medium"
                    : "bg-yellow-950/50 text-yellow-400 hover:bg-yellow-900/50"
                }`}
              >
                <Star size={11} fill="currentColor" />
                {stats.favorites} favorites
              </button>
            )}
            {/* Print-status lifecycle filters (#166). The active chip shows an
                X to clear; inactive chips show their count and filter on click. */}
            {(["queued", "printing", "printed"] as const).map((s) => (
              printStatusParam === s ? (
                <button
                  key={s}
                  onClick={() => setParam("print_status", "")}
                  className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded font-medium transition-colors ${
                    s === "queued" ? "bg-sky-500 text-sky-950" :
                    s === "printing" ? "bg-amber-500 text-amber-950" :
                    "bg-emerald-500 text-emerald-950"
                  }`}
                >
                  <Printer size={11} />
                  {PRINT_STATUS_LABELS[s]}
                  <X size={10} />
                </button>
              ) : (stats && stats[s] > 0) ? (
                <button
                  key={s}
                  onClick={() => setParam("print_status", s)}
                  title={`Show only ${PRINT_STATUS_LABELS[s]} models`}
                  className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded transition-colors ${
                    s === "queued" ? "bg-sky-950/50 text-sky-400 hover:bg-sky-900/50" :
                    s === "printing" ? "bg-amber-950/50 text-amber-400 hover:bg-amber-900/50" :
                    "bg-emerald-950/50 text-emerald-400 hover:bg-emerald-900/50"
                  }`}
                >
                  <Printer size={11} />
                  {stats[s]} {PRINT_STATUS_LABELS[s].toLowerCase()}
                </button>
              ) : null
            ))}
            <button
              onClick={() => setParam("added_days", addedDays ? "" : String(settings.recent_days))}
              title={`Models added in the last ${settings.recent_days} days, newest first`}
              className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded transition-colors ${
                addedDays
                  ? "bg-indigo-500 text-indigo-950 font-medium"
                  : "bg-indigo-950/50 text-indigo-400 hover:bg-indigo-900/50"
              }`}
            >
              <Sparkles size={11} />
              recently added
            </button>
            {stats && (stats.excluded > 0 || excludedParam) && (
              <button
                onClick={() => setParam("excluded", excludedParam ? "" : "1")}
                className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded transition-colors ${
                  excludedParam
                    ? "bg-gray-500 text-gray-950 font-medium"
                    : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                }`}
              >
                <EyeOff size={11} />
                {stats.excluded} excluded
              </button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-sm text-gray-400">
            Sort
            <select
              aria-label="Sort models"
              value={effectiveSort}
              disabled={!!addedDays}
              title={addedDays ? "Sorted by date added while the Recently added filter is on" : undefined}
              onChange={(e) => changeSort(e.target.value as LibrarySort)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200 disabled:opacity-50"
            >
              <option value="name">Name</option>
              <option value="added">Date added</option>
              <option value="creator">Creator</option>
              <option value="rating">Rating</option>
            </select>
          </label>
          <button
            onClick={() => setShowShortcuts(true)}
            title="Keyboard shortcuts ( ? )"
            aria-label="Keyboard shortcuts"
            className="p-1.5 rounded border border-gray-700 bg-gray-900 text-gray-400 hover:text-gray-100 hover:border-gray-500 transition-colors"
          >
            <Keyboard size={16} />
          </button>
          <ScanButton onScanComplete={fetchModels} />
        </div>
      </div>

      {/* Search + filter bar */}
      <div className="flex gap-2 mb-4 flex-wrap">
        <div className="relative flex-1 min-w-48">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            ref={searchInputRef}
            type="text"
            placeholder="Search models…  (press / )"
            value={searchInput}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded pl-9 pr-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
          />
        </div>

        {/* Active filter chips */}
        {activeTag && (
          <div className="flex items-center gap-1.5 px-3 py-2 rounded bg-indigo-950 border border-indigo-700 text-indigo-300 text-sm">
            <Tag size={13} />
            <span>{activeTag}</span>
            <button onClick={() => setParam("tag", "")} className="text-indigo-500 hover:text-indigo-200 transition-colors ml-0.5">
              <X size={13} />
            </button>
          </div>
        )}
        {excludeTag && (
          <div className="flex items-center gap-1.5 px-3 py-2 rounded bg-rose-950 border border-rose-700 text-rose-300 text-sm">
            <Tag size={13} />
            <span>≠ {excludeTag}</span>
            <button onClick={() => setParam("exclude_tag", "")} className="text-rose-500 hover:text-rose-200 transition-colors ml-0.5">
              <X size={13} />
            </button>
          </div>
        )}
        {nsfwParam && (
          <div className="flex items-center gap-1.5 px-3 py-2 rounded bg-red-950 border border-red-800 text-red-300 text-sm">
            <span>NSFW: {nsfwParam === "1" ? "Yes" : "No"}</span>
            <button onClick={() => setParam("nsfw", "")} className="text-red-500 hover:text-red-200 transition-colors">
              <X size={13} />
            </button>
          </div>
        )}
        {thumbParam && (
          <div className="flex items-center gap-1.5 px-3 py-2 rounded bg-gray-800 border border-gray-700 text-gray-300 text-sm">
            <span>Image: {thumbParam === "1" ? "Yes" : "No"}</span>
            <button onClick={() => setParam("has_thumbnail", "")} className="text-gray-500 hover:text-gray-200 transition-colors">
              <X size={13} />
            </button>
          </div>
        )}

        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1.5 px-3 py-2 rounded border text-sm transition-colors ${
            showFilters || hasFilters
              ? "bg-indigo-600 border-indigo-500 text-white"
              : "bg-gray-900 border-gray-700 text-gray-400 hover:text-gray-100"
          }`}
        >
          <SlidersHorizontal size={14} />
          Filters {hasFilters && !showFilters && "•"}
        </button>
      </div>

      {showFilters && (
        <div className="flex flex-col gap-3 mb-4 p-3 bg-gray-900 rounded border border-gray-800">

          {/* Saved presets */}
          {(presets.length > 0 || hasFilters) && (
            <div className="flex flex-wrap items-center gap-2 pb-3 border-b border-gray-800">
              <Bookmark size={13} className="text-gray-500 shrink-0" />
              {presets.map((p) => (
                <button
                  key={p.name}
                  onClick={() => applyPreset(p)}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-gray-800 border border-gray-700 text-xs text-gray-300 hover:border-indigo-500 hover:text-indigo-300 transition-colors"
                >
                  {p.name}
                  <span
                    role="button"
                    onClick={(e) => { e.stopPropagation(); deletePreset(p.name); }}
                    className="text-gray-600 hover:text-red-400 transition-colors ml-0.5"
                  >
                    <X size={11} />
                  </span>
                </button>
              ))}
              {hasFilters && !savingPreset && (
                <button
                  onClick={() => setSavingPreset(true)}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-gray-800 border border-dashed border-gray-600 text-xs text-gray-500 hover:text-indigo-300 hover:border-indigo-600 transition-colors"
                >
                  <BookmarkPlus size={11} />
                  Save preset
                </button>
              )}
              {savingPreset && (
                <form
                  onSubmit={(e) => { e.preventDefault(); confirmSavePreset(); }}
                  className="flex items-center gap-1"
                >
                  <input
                    ref={presetInputRef}
                    type="text"
                    placeholder="Preset name…"
                    value={presetName}
                    onChange={(e) => setPresetName(e.target.value)}
                    className="bg-gray-800 border border-indigo-600 rounded px-2 py-0.5 text-xs text-gray-100 placeholder-gray-600 focus:outline-none w-32"
                  />
                  <button type="submit" className="text-xs text-indigo-400 hover:text-indigo-200 px-1">Save</button>
                  <button type="button" onClick={() => { setSavingPreset(false); setPresetName(""); }} className="text-xs text-gray-600 hover:text-gray-300">
                    <X size={12} />
                  </button>
                </form>
              )}
            </div>
          )}

          {/* Dropdowns row */}
          <div className="flex flex-wrap gap-3 items-center">
            <select
              value={creatorId}
              onChange={(e) => setParams({ creator_id: e.target.value, exclude_creator_id: "" })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Creators</option>
              {creators.map((c) => (
                <option key={c.id} value={c.id}>{c.name} ({c.model_count})</option>
              ))}
            </select>
            <select
              value={excludeCreatorId}
              onChange={(e) => setParams({ exclude_creator_id: e.target.value, creator_id: "" })}
              title="Hide all models from one creator"
              className={`bg-gray-800 border rounded px-2 py-1.5 text-sm focus:outline-none focus:border-rose-500 ${
                excludeCreatorId ? "border-rose-700 text-rose-300" : "border-gray-700 text-gray-200"
              }`}
            >
              <option value="">Exclude creator…</option>
              {creators.map((c) => (
                <option key={c.id} value={c.id}>{c.name} ({c.model_count})</option>
              ))}
            </select>
            <select
              value={site}
              onChange={(e) => setParam("source_site", e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Sites</option>
              {SITES.map((s) => (
                <option key={s} value={s} className="capitalize">{s}</option>
              ))}
            </select>

            <TriToggle label="NSFW" value={nsfwParam} onChange={(v) => setParam("nsfw", v)} />
            <TriToggle label="Has image" value={thumbParam} onChange={(v) => setParam("has_thumbnail", v)} />

            <div className="flex items-center gap-1.5">
              <span className="text-xs text-gray-500">Min rating</span>
              <select
                value={minRating}
                onChange={(e) => setParam("min_rating", e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="">Any</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>{"★".repeat(n)}{n < 5 ? "+" : ""}</option>
                ))}
              </select>
            </div>

            <label className="flex items-center gap-1.5 text-sm text-gray-400 cursor-pointer">
              <input
                type="checkbox"
                checked={needsReview}
                onChange={(e) => setParam("needs_review", e.target.checked ? "1" : "")}
                className="accent-amber-400"
              />
              Needs review only
            </label>
            {hasFilters && (
              <button
                onClick={() => setSearchParams(searchInput ? { q: searchInput } : {})}
                className="text-xs text-gray-500 hover:text-gray-300 px-2 ml-auto"
              >
                Clear all
              </button>
            )}
          </div>

          {/* Tag picker */}
          {allTags.length > 0 && (
            <div className="border-t border-gray-800 pt-3">
              <div className="flex items-center gap-2 mb-2">
                <Tag size={13} className="text-gray-500" />
                <span className="text-xs text-gray-500 font-medium uppercase tracking-wide">Filter by tag</span>
                <div className="relative ml-auto">
                  <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input
                    type="text"
                    placeholder="Search tags…"
                    value={tagSearch}
                    onChange={(e) => setTagSearch(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded pl-6 pr-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-36"
                  />
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                {visibleTags.map(({ tag, count }) => {
                  // Three-state cycle: off → include (indigo) → exclude (rose) → off
                  const isInclude = activeTag === tag;
                  const isExclude = excludeTag === tag;
                  return (
                    <button
                      key={tag}
                      onClick={() => setParams(nextTagParams(tag, activeTag, excludeTag))}
                      title={isInclude ? "Click again to exclude this tag" : isExclude ? "Click to clear" : "Show only this tag"}
                      className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs transition-colors ${
                        isInclude
                          ? "bg-indigo-600 border border-indigo-500 text-white"
                          : isExclude
                          ? "bg-rose-700 border border-rose-600 text-white"
                          : "bg-gray-800 border border-gray-700 text-gray-300 hover:border-indigo-500 hover:text-indigo-300"
                      }`}
                    >
                      {isExclude && "≠ "}{tag}
                      <span className={isInclude ? "text-indigo-300" : isExclude ? "text-rose-300" : "text-gray-500"}>{count}</span>
                    </button>
                  );
                })}
                {visibleTags.length === 0 && (
                  <span className="text-xs text-gray-600">No tags match "{tagSearch}"</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Pagination (top) */}
      {totalPages > 1 && (
        <PaginationBar page={page} totalPages={totalPages} onPage={setPage} className="mb-6" />
      )}

      {/* Grid */}
      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {Array.from({ length: 24 }).map((_, i) => (
            <div key={i} className="aspect-square bg-gray-900 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : models.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-gray-600">
          <p className="text-lg">No models found</p>
          <p className="text-sm mt-1">Try scanning your library or adjusting filters</p>
        </div>
      ) : !dndEnabled ? (
        <div ref={gridRef} className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {models.map((m, i) => (
            <ModelCard
              key={m.id}
              model={m}
              selected={selection.has(m.id)}
              onSelect={toggleSelect}
              onMutate={refreshStats}
              excludedView={excludedParam}
              onRemoved={handleRemoved}
              hasGuide={guideModelIds.has(m.id)}
              allTagSuggestions={allTags}
              focused={focusedIndex === i}
            />
          ))}
        </div>
      ) : (
        <DndContext
          sensors={dndSensors}
          collisionDetection={pointerWithin}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onDragCancel={() => setDraggingId(null)}
        >
          <div ref={gridRef} className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {models.map((m, i) => (
              <DraggableCard key={m.id} model={m} draggingCreatorId={draggingModel?.creator_id ?? null}>
                <ModelCard
                  model={m}
                  selected={selection.has(m.id)}
                  onSelect={toggleSelect}
                  onMutate={refreshStats}
                  excludedView={excludedParam}
                  onRemoved={handleRemoved}
                  hasGuide={guideModelIds.has(m.id)}
                  allTagSuggestions={allTags}
                  focused={focusedIndex === i}
                />
              </DraggableCard>
            ))}
          </div>
          <DragOverlay dropAnimation={null}>
            {draggingModel ? (() => {
              const thumb = draggingModel.thumbnail_path
                ? api.fileUrl(draggingModel.thumbnail_path)
                : draggingModel.thumbnail_url;
              return (
                <div className="w-32 rounded-lg overflow-hidden border-2 border-indigo-400 bg-gray-900 shadow-2xl shadow-black/60 rotate-2">
                  <div className="aspect-square bg-gray-800">
                    {thumb ? (
                      <img src={thumb} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-gray-600">
                        <Package size={32} />
                      </div>
                    )}
                  </div>
                  <p className="p-1.5 text-xs font-medium truncate text-gray-100">
                    {draggingModel.title || draggingModel.name}
                  </p>
                </div>
              );
            })() : null}
          </DragOverlay>
        </DndContext>
      )}

      {selection.size > 0 && (
        <BulkTagBar
          selectedIds={Array.from(selection)}
          totalOnPage={models.length}
          onSelectAll={selectAll}
          onClear={clearSelection}
          onDone={fetchModels}
          collections={collections}
        />
      )}

      {/* Pagination (bottom) */}
      {totalPages > 1 && (
        <PaginationBar page={page} totalPages={totalPages} onPage={setPage} />
      )}

      {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />}

      {/* Name-the-group prompt when two ungrouped models are dragged together */}
      {pendingMerge && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => !merging && setPendingMerge(null)}
        >
          <div
            className="w-full max-w-sm rounded-xl border border-gray-700 bg-gray-900 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-3">
              <Layers size={18} className="text-indigo-400" />
              <h2 className="text-lg font-semibold text-gray-100">Group as variants</h2>
            </div>
            <p className="text-sm text-gray-400 mb-3">
              Name the variant group these two models will share. The grouping is
              saved and survives rescans.
            </p>
            <input
              autoFocus
              type="text"
              value={mergeName}
              onChange={(e) => setMergeName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") confirmMerge();
                if (e.key === "Escape" && !merging) setPendingMerge(null);
              }}
              placeholder="Group name"
              className="w-full px-3 py-2 rounded bg-gray-950 border border-gray-700 focus:border-indigo-500 text-sm text-gray-100 outline-none mb-4"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setPendingMerge(null)}
                disabled={merging}
                className="px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-sm text-gray-300 disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={confirmMerge}
                disabled={merging || !mergeName.trim()}
                className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-sm text-white disabled:opacity-40"
              >
                {merging ? "Grouping…" : "Group"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

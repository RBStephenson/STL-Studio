import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { AlertTriangle, FolderPlus, ArrowRight, Layers, Keyboard } from "lucide-react";
import {
  PointerSensor, KeyboardSensor, useSensor, useSensors,
  DragStartEvent, DragEndEvent, Announcements,
} from "@dnd-kit/core";
import { gridKeyboardCoordinates } from "../utils/gridKeyboardCoordinates";
import { api, Model, LibrarySort, ModelList } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import { queryKeys } from "../hooks/queries/keys";
import { useLibraryModels, useCreators, useModelStats, useAllTags } from "../hooks/queries/models";
import { useCollections } from "../hooks/queries/collections";
import { useScanRootCount, useUnavailableRoots } from "../hooks/queries/scan";
import { useGuideModelIds } from "../hooks/queries/guides";
import ScanButton from "../components/ScanButton";
import BulkTagBar from "../components/BulkTagBar";
import { useToast } from "../context/ToastContext";
import { nextSelection } from "../utils/selection";
import { modelLinkTo } from "../utils/modelLink";
import { measureGridColumns } from "../utils/libraryKeys";
import { resolveDragIntent, resolveGroupMergePayload } from "../utils/dragGroup";
import { useLibraryKeyboard } from "../hooks/useLibraryKeyboard";
import { useLibraryFilters } from "../hooks/useLibraryFilters";
import ShortcutsOverlay from "../components/ShortcutsOverlay";
import Sidebar, { useSidebarCollapsed } from "./library/Sidebar";
import ModelGrid from "./library/ModelGrid";
import PaginationBar from "./library/PaginationBar";
import { errMsg } from "../utils/err";

// Last applied Library filter querystring, remembered across navigation so that
// returning to the Library — via the navbar link, an in-page back, or browser
// Back — resumes the prior filter set instead of dropping to the unfiltered view
// (#288). "Clear all" removes this so an intentional reset stays reset.
const LIBRARY_QUERY_KEY = "library_query";

// Stable empty set so the guide-ids fallback doesn't produce a new reference
// each render (which would churn ModelCard memoization).
const EMPTY_GUIDE_IDS: Set<number> = new Set();

export default function Library() {
  const filters = useLibraryFilters();
  const {
    searchParams, setSearchParams,
    page, creatorId, excludeCreatorId, site, activeTag, excludeTag,
    needsReview, favParam, printStatusParam, excludePrinted,
    excludedParam, supportParam, addedDays, searchInputRef, searchInput,
    setPage, effectiveSort, changeSort, listParams,
  } = filters;
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();

  const queryClient = useQueryClient();
  const [collapsed, setCollapsed] = useSidebarCollapsed();
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const { settings } = useAppSettings();
  const pageSize = settings.library_page_size;

  const scrollRestoredRef = useRef(false);

  const modelsQuery = useLibraryModels(listParams);
  // Memoized so the array ref is stable across renders — several callbacks/effects
  // below depend on `models`, and a fresh `?? []` each render would churn them.
  const models = useMemo(() => modelsQuery.data?.items ?? [], [modelsQuery.data]);
  const total = modelsQuery.data?.total ?? 0;
  const loading = modelsQuery.isPending;
  const isError = modelsQuery.isError;

  const statsQuery = useModelStats();
  const stats = statsQuery.data ?? null;
  const creators = useCreators().data ?? [];
  const allTags = useAllTags().data ?? [];
  const collections = useCollections().data ?? [];
  const scanRootCount = useScanRootCount().data ?? null;
  const unavailableRoots = useUnavailableRoots().data ?? [];
  // Model ids that have a painting guide → "Guide" badge (#263). Only fetched
  // when the painting module is enabled.
  const guideModelIds = useGuideModelIds(settings.painting_guides_enabled).data ?? EMPTY_GUIDE_IDS;

  // Refetch the Library after a scan/merge/bulk op. Invalidates the whole models
  // namespace (list + stats + creators + tags) since any of those can change.
  const fetchModels = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: queryKeys.models.all });
  }, [queryClient]);

  const clearFilters = useCallback(() => {
    setSearchParams(searchInput ? { q: searchInput } : {});
  }, [setSearchParams, searchInput]);

  const scanLibrary = useCallback(() => {
    api.scan.start().then(fetchModels).catch((e) => toast(errMsg(e) || "Couldn't start the scan — try again.", "error"));
  }, [fetchModels, toast]);

  // Refresh just the count chips after a per-card mutation.
  const refreshStats = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: queryKeys.models.stats });
  }, [queryClient]);

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

  const totalPages = Math.ceil(total / pageSize);
  const hasFilters = !!(creatorId || excludeCreatorId || site || activeTag || excludeTag || needsReview || favParam || printStatusParam || excludePrinted || supportParam || addedDays);

  // Current URL params, remembered for filter stickiness (excluding page)
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
    queryClient.setQueryData<ModelList>(queryKeys.models.list(listParams), (prev) =>
      prev
        ? { ...prev, items: prev.items.filter((m) => m.id !== id), total: Math.max(0, prev.total - 1) }
        : prev,
    );
    refreshStats();
  }, [queryClient, listParams, refreshStats]);

  // --- Keyboard navigation (#169) --------------------------------------------
  // WASD/arrows move a focus ring between cards, Enter opens, "/" focuses
  // search, "?" toggles a shortcuts overlay, Esc steps back out.
  const [showShortcuts, setShowShortcuts] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);

  // Up/down jumps a whole row, so the move math needs the grid's live column
  // count (2→6 across breakpoints), measured from the DOM.
  const getColumns = useCallback(() => measureGridColumns(gridRef.current), []);

  const openModel = useCallback((index: number) => {
    const m = models[index];
    if (!m) return;
    sessionStorage.setItem("library_scroll", String(window.scrollY));
    navigate(modelLinkTo(m), { state: { from: location.pathname + location.search } });
  }, [models, navigate, location]);

  const focusSearch = useCallback(() => {
    const el = searchInputRef.current;
    if (el) { el.focus(); el.select(); }
  }, [searchInputRef]);

  // A drag is in progress (pointer or keyboard). Tracked here (above the keyboard
  // hook) so grid WASD/arrow nav pauses while a card is picked up — otherwise the
  // arrow keys would both walk the focus ring AND move the dragged card (#139).
  const [draggingId, setDraggingId] = useState<number | null>(null);

  const { focusedIndex, setFocusedIndex } = useLibraryKeyboard({
    count: models.length,
    getColumns,
    enabled: draggingId === null,
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
  // A pending group op awaiting a name: a set of source models that will join the
  // target. Used when the drop target is ungrouped (no character to inherit);
  // covers both single- and multi-card drags (#137).
  const [pendingMerge, setPendingMerge] = useState<{ sourceIds: number[]; targetId: number } | null>(null);
  // A pending whole-group merge (#136): drop group A onto target B. Held for a
  // confirmation step because it moves every member of A and loses A's name.
  const [pendingGroupMerge, setPendingGroupMerge] = useState<{ source: Model; target: Model } | null>(null);
  const [mergeName, setMergeName] = useState("");
  const [merging, setMerging] = useState(false);
  const dndSensors = useSensors(
    // Small threshold so a plain click on the grip still isn't treated as a drag,
    // and ordinary card clicks never start one.
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    // Keyboard parity (#139): focus a grip, Space to pick up, arrows to hop
    // between cards (free-draggable grid getter), Space/Enter to drop, Esc to
    // cancel. dnd-kit announces pickup/over/drop via `dndAnnouncements`.
    useSensor(KeyboardSensor, { coordinateGetter: gridKeyboardCoordinates }),
  );
  const draggingModel = draggingId != null ? models.find((m) => m.id === draggingId) ?? null : null;
  // How many cards a drag moves: the whole selection when the grabbed card is part
  // of it (#137), otherwise one. Drives the drag-overlay count badge.
  const dragCount =
    draggingId != null && selection.has(draggingId) && selection.size > 1 ? selection.size : 1;

  const mergeIntoDurableGroup = useCallback(
    async (ids: number[], groupId: number | null, label: string): Promise<boolean> => {
      try {
        await api.models.mergeGroup(ids, groupId ? { groupId, label } : { label });
        const noun = ids.length === 1 ? "model" : "models";
        toast(`${ids.length} ${noun} merged into "${label}".`, "success");
        return true;
      } catch (err) {
        toast(errMsg(err) || "Couldn't merge into this group - try again.", "error");
        return false;
      }
    },
    [toast],
  );

  const nameOfModel = (id: number) => {
    const m = models.find((x) => x.id === id);
    return m ? m.title || m.name : "this model";
  };

  // Screen-reader narration for the drag-to-group gesture (#139). Names come from
  // the loaded page, so announcements stay meaningful for keyboard/AT users.
  const dndAnnouncements: Announcements = {
    onDragStart: ({ active }) => {
      const name = nameOfModel(Number(active.id));
      return `Picked up ${name}. Use the arrow keys to move it onto another card, then press space or enter to group them. Press escape to cancel.`;
    },
    onDragOver: ({ active, over }) => {
      if (!over) return `${nameOfModel(Number(active.id))} is not over a card.`;
      return `${nameOfModel(Number(active.id))} is over ${nameOfModel(Number(over.id))}. Press space or enter to group them.`;
    },
    onDragEnd: ({ active, over }) => {
      if (!over) return `${nameOfModel(Number(active.id))} was dropped. No group change.`;
      return `Grouped ${nameOfModel(Number(active.id))} with ${nameOfModel(Number(over.id))}.`;
    },
    onDragCancel: ({ active }) => `Cancelled. ${nameOfModel(Number(active.id))} was not grouped.`,
  };

  const onDragStart = (e: DragStartEvent) => setDraggingId(Number(e.active.id));

  const onDragEnd = async (e: DragEndEvent) => {
    setDraggingId(null);
    if (!e.over) return;
    const draggedId = Number(e.active.id);
    const targetId = Number(e.over.id);
    const target = models.find((m) => m.id === targetId);

    const intent = resolveDragIntent(
      draggedId,
      targetId,
      (id) => models.find((m) => m.id === id),
      selection,
    );

    switch (intent.kind) {
      case "none":
        return;
      case "error":
        toast(intent.message, "error");
        return;
      case "group-merge":
        // #136 — defer to a confirm step; the member fetch happens on confirm.
        if (target) setPendingGroupMerge({ source: models.find((m) => m.id === draggedId)!, target });
        return;
      case "apply": {
        // #137 — target already grouped: inherit its name, write immediately.
        // An ungrouped target (character-only, no variant_group_id) starts a
        // brand-new durable group and must fold itself in as a member too —
        // same shape as the #136 group-merge payload, so reuse that helper.
        if (intent.skipped > 0) toast(`${intent.skipped} from another creator skipped.`, "info");
        if (!target) return;
        const { ids, groupId, label } = resolveGroupMergePayload(target, intent.sourceIds);
        if (await mergeIntoDurableGroup(ids, groupId, label)) {
          clearSelection();
          fetchModels();
        }
        return;
      }
      case "prompt":
        // Target is ungrouped: ask for a name; the target joins the new group too.
        if (intent.skipped > 0) toast(`${intent.skipped} from another creator skipped.`, "info");
        setMergeName(intent.suggestedName);
        setPendingMerge({ sourceIds: intent.sourceIds, targetId: intent.targetId });
        return;
    }
  };

  const confirmMerge = async () => {
    if (!pendingMerge || merging) return;
    const name = mergeName.trim();
    if (!name) return;
    setMerging(true);
    // The ungrouped target joins the group too, so include it with the sources.
    const ids = Array.from(new Set([...pendingMerge.sourceIds, pendingMerge.targetId]));
    const ok = await mergeIntoDurableGroup(ids, null, name);
    setMerging(false);
    if (ok) {
      setPendingMerge(null);
      clearSelection();
      fetchModels();
    }
  };

  const confirmGroupMerge = async () => {
    if (!pendingGroupMerge || merging) return;
    const { source, target } = pendingGroupMerge;
    setMerging(true);
    try {
      // The Library only holds the group's representative card, so resolve the
      // full membership before merging it into the durable target group.
      const members = await api.models.variants(
        source.creator_id!,
        source.character || "",
        source.variant_group_id,
      );
      const { ids, groupId, label } = resolveGroupMergePayload(
        target,
        members.items.map((m) => m.id),
      );
      const ok = await mergeIntoDurableGroup(ids, groupId, label);
      if (ok) {
        setPendingGroupMerge(null);
        clearSelection();
        fetchModels();
      }
    } catch (err) {
      toast(errMsg(err) || "Couldn't merge these groups — try again.", "error");
    } finally {
      setMerging(false);
    }
  };

  return (
    <div className="flex items-stretch min-h-[calc(100vh-56px)]">
      <Sidebar
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((c) => !c)}
        total={total}
        filters={filters}
        creators={creators}
        allTags={allTags}
        stats={stats}
        recentDays={settings.recent_days}
        hasFilters={hasFilters}
      />

      <div className="flex-1 min-w-0 p-6">
        {/* A configured drive is unavailable (unmounted/disconnected) — #304 */}
        {unavailableRoots.length > 0 && (
          <div className="mb-6 rounded-xl border border-amber-700/60 bg-amber-950/40 p-4" role="alert">
            <div className="flex items-start gap-3">
              <div className="rounded-lg bg-amber-600/20 p-2 text-amber-300 shrink-0">
                <AlertTriangle size={20} />
              </div>
              <div className="flex-1">
                <h2 className="text-sm font-semibold text-amber-100">
                  {unavailableRoots.length === 1 ? "A scan folder is unavailable" : "Some scan folders are unavailable"}
                </h2>
                <p className="text-sm text-amber-200/80 mt-1">
                  These folders couldn't be found — the drive may be disconnected or unmounted.
                  Models stored there won't load until it's reconnected.
                </p>
                <ul className="mt-2 space-y-0.5 text-xs font-mono text-amber-200/70">
                  {unavailableRoots.map((p) => <li key={p}>{p}</li>)}
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* First-run onboarding: no scan folders configured yet */}
        {scanRootCount === 0 && (
          <div className="mb-6 rounded-xl border border-accent-end/60 bg-indigo-950/40 p-5">
            <div className="flex items-start gap-4">
              <div className="rounded-lg bg-accent-end/20 p-2.5 text-indigo-300 shrink-0">
                <FolderPlus size={22} />
              </div>
              <div className="flex-1">
                <h2 className="text-lg font-semibold text-text-primary">Welcome to STL Studio 👋</h2>
                <p className="text-sm text-text-secondary mt-1">
                  No folders are set up yet. Tell the app where your STL files live, then run a
                  scan to build your library.
                </p>
                <Link
                  to="/settings"
                  className="btn-cta inline-flex items-center gap-1.5 mt-3 px-4 py-2 rounded-lg text-white text-sm font-medium"
                >
                  Add your STL folder in Settings
                  <ArrowRight size={15} />
                </Link>
              </div>
            </div>
          </div>
        )}

        {/* Toolbar */}
        <div className="flex items-center justify-end gap-2.5 mb-4.5">
          <label className="flex items-center gap-2 text-sm text-text-muted mr-auto sm:mr-0">
            Sort
            <select
              aria-label="Sort models"
              value={effectiveSort}
              disabled={!!addedDays}
              title={addedDays ? "Sorted by date added while the Recently added filter is on" : undefined}
              onChange={(e) => changeSort(e.target.value as LibrarySort)}
              className="bg-panel-inset border border-border-divider rounded-lg px-2.5 py-1.5 text-sm text-text-primary-alt2 disabled:opacity-50"
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
            className="p-2 rounded-lg border border-border-divider bg-panel-inset text-text-secondary hover:text-text-primary transition-colors"
          >
            <Keyboard size={16} />
          </button>
          <ScanButton onScanComplete={fetchModels} />
        </div>

        {/* Grid */}
        <ModelGrid
          loading={loading}
          isError={isError}
          onRetry={fetchModels}
          onClearFilters={clearFilters}
          onScanLibrary={scanLibrary}
          models={models}
          selection={selection}
          onSelect={toggleSelect}
          onMutate={refreshStats}
          excludedView={excludedParam}
          onRemoved={handleRemoved}
          guideModelIds={guideModelIds}
          allTagSuggestions={allTags}
          focusedIndex={focusedIndex}
          gridRef={gridRef}
          dndEnabled={dndEnabled}
          dndSensors={dndSensors}
          dndAnnouncements={dndAnnouncements}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onDragCancel={() => setDraggingId(null)}
          draggingModel={draggingModel}
          dragCount={dragCount}
        />

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

        {/* Floating pagination */}
        {totalPages > 1 && (
          <PaginationBar page={page} totalPages={totalPages} onPage={setPage} />
        )}
      </div>

      {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} showDragGroup={dndEnabled} />}

      {/* Name-the-group prompt when two ungrouped models are dragged together */}
      {pendingMerge && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => !merging && setPendingMerge(null)}
        >
          <div
            className="w-full max-w-sm rounded-xl border border-border bg-panel p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-3">
              <Layers size={18} className="text-accent-start" />
              <h2 className="text-lg font-semibold text-text-primary">Group as variants</h2>
            </div>
            <p className="text-sm text-text-secondary mb-3">
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
              className="w-full px-3 py-2 rounded bg-panel-inset border border-border focus:border-accent-start text-sm text-text-primary outline-none mb-4"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setPendingMerge(null)}
                disabled={merging}
                className="px-3 py-1.5 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-sm text-text-primary-alt2 disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={confirmMerge}
                disabled={merging || !mergeName.trim()}
                className="px-3 py-1.5 rounded bg-accent-end hover:bg-accent-start text-sm text-white disabled:opacity-40"
              >
                {merging ? "Grouping…" : "Group"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm merging one whole variant group into another (#136). */}
      {pendingGroupMerge && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => !merging && setPendingGroupMerge(null)}
        >
          <div
            className="w-full max-w-sm rounded-xl border border-border bg-panel p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-3">
              <Layers size={18} className="text-accent-start" />
              <h2 className="text-lg font-semibold text-text-primary">Merge variant groups</h2>
            </div>
            <p className="text-sm text-text-secondary mb-4">
              Move all{" "}
              <span className="font-semibold text-text-primary-alt">
                {pendingGroupMerge.source.variant_count ?? 1}
              </span>{" "}
              models from{" "}
              <span className="font-semibold text-text-primary-alt">
                "{pendingGroupMerge.source.character}"
              </span>{" "}
              into{" "}
              <span className="font-semibold text-text-primary-alt">
                "{pendingGroupMerge.target.character
                  || pendingGroupMerge.target.title
                  || pendingGroupMerge.target.name}"
              </span>
              ? The source group's name is discarded.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setPendingGroupMerge(null)}
                disabled={merging}
                className="px-3 py-1.5 rounded bg-panel-secondary hover:bg-panel-secondary border border-border text-sm text-text-primary-alt2 disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={confirmGroupMerge}
                disabled={merging}
                className="px-3 py-1.5 rounded bg-accent-end hover:bg-accent-start text-sm text-white disabled:opacity-40"
              >
                {merging ? "Merging…" : "Merge"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

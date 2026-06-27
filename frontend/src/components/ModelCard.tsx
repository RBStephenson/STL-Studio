import { memo, useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from "react";
import { Link, useLocation } from "react-router-dom";
import { Package, Star, AlertCircle, Check, Layers, Printer, EyeOff, RotateCcw, Sparkles, Paintbrush, MoreHorizontal, ChevronLeft, ChevronRight } from "lucide-react";
import { Model, PrintStatus, PRINT_STATUS_CYCLE, api } from "../api/client";
import { useNSFW } from "../context/NSFWContext";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
import { isRecentlyAdded } from "../utils/recentlyAdded";
import { modelLinkTo } from "../utils/modelLink";
import QuickAssignPopover from "./QuickAssignPopover";
import StarRating from "./StarRating";

interface Props {
  model: Model;
  selected?: boolean;
  onSelect?: (id: number, shiftKey: boolean) => void;
  backTo?: string;
  /** Called after a successful favorite/queue toggle so parents can refresh
   *  derived data (e.g. the Library's favorites/queued count chips). */
  onMutate?: () => void;
  /** When true, the card is shown in the Excluded view: the hide action becomes
   *  a Restore action. */
  excludedView?: boolean;
  /** Called after the model is excluded (or restored) so the parent can drop the
   *  card from the current list optimistically. */
  onRemoved?: (id: number) => void;
  /** True when a painting guide exists for this model — shows a "Guide" badge. */
  hasGuide?: boolean;
  /** All tags with counts for the quick-assign popover typeahead. */
  allTagSuggestions?: { tag: string; count: number }[];
  /** Keyboard-navigation focus (#169): draws a focus ring and scrolls into view. */
  focused?: boolean;
}

const SITE_LABELS: Record<string, string> = {
  thingiverse: "Thingiverse",
  printables: "Printables",
  myminifactory: "MyMiniFactory",
  cults3d: "Cults3D",
  thangs: "Thangs",
  makerworld: "MakerWorld",
  gumroad: "Gumroad",
  patreon: "Patreon",
  other: "Other",
};

const TAG_COLORS: Record<string, string> = {
  "pre-supported": "bg-emerald-900 text-emerald-300",
  "bust":          "bg-blue-900 text-blue-300",
  "statue":        "bg-purple-900 text-purple-300",
  "figure":        "bg-indigo-900 text-indigo-300",
};

// Memoized: the Library re-renders the whole grid on every selection / keyboard-
// focus / drag tick. Without memo, all N cards on the page re-render each time
// (per-keystroke during keyboard nav). Props are stable across those ticks —
// `model` refs survive, callbacks are useCallback'd, `allTagSuggestions` is stable
// state — so the default shallow compare re-renders only the card whose
// `selected`/`focused` actually changed (#382).
function ModelCard({ model, selected = false, onSelect, backTo, onMutate, excludedView = false, onRemoved, hasGuide = false, allTagSuggestions = [], focused = false }: Props) {
  const location = useLocation();
  const cardRef = useRef<HTMLDivElement>(null);

  // Keep the keyboard-focused card in view as the user moves with WASD (#169).
  useEffect(() => {
    if (focused) cardRef.current?.scrollIntoView({ block: "nearest" });
  }, [focused]);
  const { showNSFW } = useNSFW();
  const { settings } = useAppSettings();
  const { toast } = useToast();
  const [nsfw, setNsfw] = useState(model.nsfw);
  const isNew = isRecentlyAdded(model.created_at, settings.recent_days);

  const [favorite, setFavorite] = useState(model.is_favorite);
  const [printStatus, setPrintStatus] = useState<PrintStatus>(model.print_status ?? "none");
  const [localTags, setLocalTags] = useState<string[]>(model.tags ?? []);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [rating, setRating] = useState<number | null>(model.user_rating ?? null);
  const [imageCleared, setImageCleared] = useState(false);
  const [localTitle, setLocalTitle] = useState(model.title ?? "");
  const [localCharacter, setLocalCharacter] = useState(model.character ?? "");
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const nameInputRef = useRef<HTMLInputElement>(null);

  const variantCount = model.variant_count ?? 1;
  const isGroup = variantCount > 1;

  // Keep the optimistic name in sync if the parent reloads with fresh data.
  useEffect(() => { setLocalTitle(model.title ?? ""); }, [model.title]);
  useEffect(() => { setLocalCharacter(model.character ?? ""); }, [model.character]);
  useEffect(() => { if (editingName) nameInputRef.current?.select(); }, [editingName]);

  const startRename = () => {
    setNameDraft(isGroup ? localCharacter : (localTitle || model.name));
    setEditingName(true);
  };

  // Renaming a variant group rewrites the shared `character` on every member,
  // so the whole group follows; a plain model just updates its own title.
  const renameGroup = async (next: string) => {
    const prev = localCharacter;
    if (model.creator_id == null) {
      toast("Can't rename a group with no creator.", "error");
      return;
    }
    setLocalCharacter(next);
    try {
      const { items } = await api.models.variants(model.creator_id, prev);
      const res = await api.models.batchSetGroup(items.map((m) => m.id), next);
      if (res.missing?.length) {
        toast(`Renamed, but ${res.missing.length} variant(s) couldn't be updated.`, "error");
      }
      onMutate?.();
    } catch {
      setLocalCharacter(prev);  // revert on failure
      toast("Couldn't rename group — try again.", "error");
    }
  };

  const renameModel = async (next: string) => {
    const prev = localTitle;
    setLocalTitle(next);
    try {
      await api.models.update(model.id, { title: next });
      onMutate?.();
    } catch {
      setLocalTitle(prev);  // revert on failure
      toast("Couldn't rename — try again.", "error");
    }
  };

  const commitRename = async () => {
    const next = nameDraft.trim();
    setEditingName(false);
    const current = isGroup ? localCharacter : (localTitle || model.name);
    if (!next || next === current) return;
    await (isGroup ? renameGroup(next) : renameModel(next));
  };

  const changeRating = async (next: number | null) => {
    const prev = rating;
    setRating(next);
    try {
      await api.models.setRating(model.id, next);
      onMutate?.();
    } catch {
      setRating(prev);  // revert on failure
      toast("Couldn't update rating — try again.", "error");
    }
  };

  const toggleNSFW = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const next = !nsfw;
    setNsfw(next);
    try {
      await api.models.setNSFW(model.id, next);
    } catch {
      setNsfw(!next);  // revert on failure
      toast("Couldn't update NSFW flag — try again.", "error");
    }
  };

  const toggleFavorite = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const next = !favorite;
    setFavorite(next);
    try {
      await api.models.setFavorite(model.id, next);
      onMutate?.();
    } catch {
      setFavorite(!next);  // revert on failure
      toast("Couldn't update favorite — try again.", "error");
    }
  };

  const cyclePrintStatus = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const idx = PRINT_STATUS_CYCLE.indexOf(printStatus);
    const next = PRINT_STATUS_CYCLE[(idx + 1) % PRINT_STATUS_CYCLE.length];
    setPrintStatus(next);
    try {
      await api.models.setPrintStatus(model.id, next);
      onMutate?.();
    } catch {
      setPrintStatus(printStatus);  // revert on failure
      toast("Couldn't update print status — try again.", "error");
    }
  };

  const toggleExclude = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // In the normal library this hides the model; in the Excluded view it restores it.
    const next = !excludedView;
    try {
      await api.models.setExcluded(model.id, next);
      onRemoved?.(model.id);  // card leaves the current view
      onMutate?.();
      toast(next ? "Model excluded from the viewer." : "Model restored.", "success");
    } catch {
      toast(next ? "Couldn't exclude the model — try again." : "Couldn't restore the model — try again.", "error");
    }
  };

  const handleSelect = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onSelect?.(model.id, e.shiftKey);
  };

  const thumbnail = imageCleared
    ? null
    : model.thumbnail_path
    ? api.fileUrl(model.thumbnail_path, model.updated_at)
    : model.thumbnail_url ?? null;

  // Static card image: user-selected primary, else first gallery image, else nothing
  // (falls through to thumbnail below).
  const cardImageUrl = (() => {
    if (imageCleared) return null;
    const gallery = model.image_paths ?? [];
    // Between bulk-enrich and import-apply, image_paths can hold remote CDN URLs
    // (apply later swaps them for local paths). Serve those directly; only wrap
    // local filesystem paths through the file endpoint.
    const resolve = (p: string) => (/^https?:\/\//i.test(p) ? p : api.fileUrl(p));
    if (model.primary_image_path) return resolve(model.primary_image_path);
    if (gallery.length > 0) return resolve(gallery[0]);
    return null;
  })();

  const displayName = isGroup && localCharacter
    ? localCharacter
    : (localTitle || model.name);
  const removedAuto = new Set(model.removed_auto_tags ?? []);
  const visibleAutoTags = (model.auto_tags ?? []).filter((t) => !removedAuto.has(t));
  const allTagsDisplay = [...visibleAutoTags, ...localTags];
  const uniqueTags = [...new Set(allTagsDisplay)];

  const handleCardClick = () => {
    sessionStorage.setItem("library_scroll", String(window.scrollY));
  };

  const linkTo = modelLinkTo(model);

  return (
    <div ref={cardRef} className="relative">
    <Link
      to={linkTo}
      state={{ from: backTo ?? location.pathname + location.search }}
      onClick={handleCardClick}
      // Anchors are native drag sources: dragging the link drags its URL.
      // Without this, mouse-selecting text in the inline rename input starts a
      // link-drag and drops the URL into the field instead of selecting text.
      draggable={false}
      className={`group bg-gray-900 rounded-lg overflow-hidden border transition-colors flex flex-col ${
        selected
          ? "border-indigo-500 ring-1 ring-indigo-500/50"
          : focused
          ? "border-indigo-400 ring-2 ring-indigo-400"
          : "border-gray-800 hover:border-indigo-500"
      }`}
    >
      <div className="aspect-square bg-gray-800 relative overflow-hidden">
        {cardImageUrl ? (
          <img
            src={cardImageUrl}
            alt={displayName}
            className={`w-full h-full object-cover group-hover:scale-105 transition-transform duration-300 ${nsfw && !showNSFW ? "blur-xl" : ""}`}
            loading="lazy"
          />
        ) : thumbnail ? (
          <img
            src={thumbnail}
            alt={displayName}
            className={`w-full h-full object-cover group-hover:scale-105 transition-transform duration-300 ${
              nsfw && !showNSFW ? "blur-xl" : ""
            }`}
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-600">
            <Package size={48} />
          </div>
        )}

        {/* NSFW overlay */}
        {nsfw && !showNSFW && (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="bg-black/60 text-red-400 text-xs font-bold px-2 py-1 rounded border border-red-800 tracking-widest">
              NSFW
            </span>
          </div>
        )}
        {nsfw && showNSFW && (
          <span className="absolute bottom-2 left-2 bg-red-950/80 text-red-400 text-xs font-bold px-1.5 py-0.5 rounded border border-red-800">
            NSFW
          </span>
        )}

        {/* NSFW quick toggle */}
        <button
          onClick={toggleNSFW}
          title={nsfw ? "Mark as SFW" : "Mark as NSFW"}
          className="absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-black/70 hover:bg-black/90 text-xs px-2 py-0.5 rounded border border-gray-600 text-gray-300 hover:text-white"
        >
          {nsfw ? "SFW" : "NSFW"}
        </button>

        {/* Selection checkbox — hover-visible, always visible when selected */}
        {onSelect && (
          <div
            onClick={handleSelect}
            className={`absolute top-2 left-2 z-10 w-5 h-5 rounded border-2 flex items-center justify-center cursor-pointer transition-all ${
              selected
                ? "bg-indigo-500 border-indigo-400 opacity-100"
                : "bg-black/60 border-gray-400 opacity-0 group-hover:opacity-100"
            }`}
          >
            {selected && <Check size={11} className="text-white" strokeWidth={3} />}
          </div>
        )}

        {/* Badges — offset right of checkbox when selectable */}
        <div className={`absolute top-2 flex flex-col gap-1 ${onSelect ? "left-9" : "left-2"}`}>
          {isNew && (
            <span className="flex items-center gap-1 bg-indigo-500/90 text-white text-xs px-1.5 py-0.5 rounded font-medium">
              <Sparkles size={10} />
              New
            </span>
          )}
          {model.needs_review && (
            <span className="flex items-center gap-1 bg-amber-500/90 text-amber-950 text-xs px-1.5 py-0.5 rounded font-medium">
              <AlertCircle size={10} />
              Review
            </span>
          )}
          {isGroup && (
            <span className="flex items-center gap-1 bg-indigo-600/90 text-white text-xs px-1.5 py-0.5 rounded font-medium">
              <Layers size={10} />
              {variantCount} variants
            </span>
          )}
          {hasGuide && (
            <span
              title="Has a painting guide"
              className="flex items-center gap-1 bg-fuchsia-600/90 text-white text-xs px-1.5 py-0.5 rounded font-medium"
            >
              <Paintbrush size={10} />
              Guide
            </span>
          )}
        </div>

        <div className="absolute top-2 right-2 flex flex-col items-end gap-1">
          {model.source_site && (
            <span className="bg-black/70 text-xs px-1.5 py-0.5 rounded text-gray-300">
              {SITE_LABELS[model.source_site] ?? model.source_site}
            </span>
          )}
          {/* Print-status + favorite toggles. On a variant group these act on the
              representative variant (model.id) — flag the model for printing now,
              pick the specific variant later from the group page. The actions
              also remain available on each individual variant. */}
          <div className="flex gap-1">
            <button
              onClick={cyclePrintStatus}
              title={`Print status: ${printStatus} — click to advance`}
              aria-label={`Print status ${printStatus}`}
              className={`p-1 rounded bg-black/60 hover:bg-black/80 transition-all ${
                printStatus === "queued"
                  ? "text-sky-400 opacity-100"
                  : printStatus === "printing"
                  ? "text-amber-400 opacity-100"
                  : printStatus === "printed"
                  ? "text-emerald-400 opacity-100"
                  : "text-gray-400 opacity-0 group-hover:opacity-100"
              }`}
            >
              <Printer size={13} />
            </button>
            <button
              onClick={toggleFavorite}
              title={favorite ? "Remove from favorites" : "Add to favorites"}
              className={`p-1 rounded bg-black/60 hover:bg-black/80 transition-all ${
                favorite
                  ? "text-yellow-400 opacity-100"
                  : "text-gray-400 hover:text-yellow-300 opacity-0 group-hover:opacity-100"
              }`}
            >
              <Star size={13} fill={favorite ? "currentColor" : "none"} />
            </button>
            <button
              onClick={toggleExclude}
              title={excludedView ? "Restore to the viewer" : "Exclude from the viewer (files kept on disk)"}
              className={`p-1 rounded bg-black/60 hover:bg-black/80 transition-all ${
                excludedView
                  ? "text-emerald-400 opacity-100 hover:text-emerald-300"
                  : "text-gray-400 hover:text-red-300 opacity-0 group-hover:opacity-100"
              }`}
            >
              {excludedView ? <RotateCcw size={13} /> : <EyeOff size={13} />}
            </button>
          </div>
        </div>
      </div>

      <div className="p-3 flex flex-col gap-1.5 flex-1">
        {model.character && !isGroup && (
          <p className="text-xs text-indigo-400 truncate">{model.character}</p>
        )}
        {editingName ? (
          <input
            ref={nameInputRef}
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
            onDragStart={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              e.stopPropagation();  // keep WASD grid nav (#169) from eating keystrokes
              if (e.key === "Enter") { e.preventDefault(); commitRename(); }
              else if (e.key === "Escape") { e.preventDefault(); setEditingName(false); }
            }}
            onBlur={commitRename}
            aria-label={isGroup ? "Rename group" : "Rename model"}
            className="text-sm font-medium bg-gray-800 border border-indigo-500 rounded px-1 py-0.5 text-gray-100 focus:outline-none"
          />
        ) : (
          <p
            className="text-sm font-medium truncate text-gray-100"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
            onDoubleClick={(e) => { e.preventDefault(); e.stopPropagation(); startRename(); }}
            title={isGroup ? "Double-click to rename this group" : "Double-click to rename"}
          >
            {displayName}
          </p>
        )}

        {uniqueTags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {uniqueTags.slice(0, 4).map((tag) => (
              <span
                key={tag}
                className={`text-xs px-1.5 py-0.5 rounded ${
                  TAG_COLORS[tag] ?? "bg-gray-800 text-gray-400"
                }`}
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        <div className="mt-auto flex items-center justify-between pt-1">
          {/* User star rating — hidden until hover when unrated, to keep the grid calm */}
          <div className={`-ml-0.5 transition-opacity ${rating != null ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-within:opacity-100"}`}>
            <StarRating value={rating} onChange={changeRating} size={13} />
          </div>
          <div className="flex items-center gap-1.5 ml-auto">
            {model.rating != null && (
              <span title="Rating from the source site" className="flex items-center gap-0.5 text-xs text-gray-500">
                <Star size={11} fill="currentColor" />
                {model.rating.toFixed(1)}
              </span>
            )}
            <button
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setPopoverOpen((o) => !o); }}
              onFocus={(e) => e.stopPropagation()}
              title="Quick assign tags / collections"
              aria-label="Quick assign tags and collections"
              className={`p-1 rounded transition-all ${
                popoverOpen
                  ? "text-indigo-400 bg-indigo-900/40 opacity-100"
                  : "text-gray-600 hover:text-gray-300 opacity-0 group-hover:opacity-100 focus:opacity-100"
              }`}
            >
              <MoreHorizontal size={13} />
            </button>
          </div>
        </div>
      </div>
    </Link>

    {popoverOpen && (
      <QuickAssignPopover
        modelId={model.id}
        initialTags={localTags}
        allTags={allTagSuggestions}
        onTagsChange={(next) => setLocalTags(next)}
        hasImage={!!thumbnail}
        onImageCleared={() => { setImageCleared(true); onMutate?.(); }}
        onRename={startRename}
        onClose={() => setPopoverOpen(false)}
      />
    )}
    </div>
  );
}

export interface GalleryRotatorHandle {
  goTo: (idx: number) => void;
}

export const GalleryRotator = forwardRef<
  GalleryRotatorHandle,
  { paths: string[]; alt: string; blur: boolean; onIndexChange?: (idx: number) => void }
>(function GalleryRotatorInner({ paths, alt, blur, onIndexChange }, ref) {
  const [broken, setBroken] = useState<Set<number>>(new Set());
  const [idx, setIdx] = useState(0);
  const [fade, setFade] = useState(true);
  const [showLabel, setShowLabel] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const labelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const urls = paths.map((p) => api.fileUrl(p));
  const validCount = paths.length - broken.size;
  const filename = paths[idx]?.replace(/\\/g, "/").split("/").pop() ?? "";

  const nextValid = useCallback((from: number, step: 1 | -1, brokenSet: Set<number>) => {
    for (let i = 1; i <= paths.length; i++) {
      const n = ((from + step * i) % paths.length + paths.length) % paths.length;
      if (!brokenSet.has(n)) return n;
    }
    return from;
  }, [paths.length]);

  const go = useCallback((next: number) => {
    setFade(false);
    if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
    fadeTimerRef.current = setTimeout(() => { setIdx(next); setFade(true); }, 150);
  }, []);

  // Clear any pending fade timer on unmount so it can't setState after teardown.
  useEffect(() => () => { if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current); }, []);

  useImperativeHandle(ref, () => ({ goTo: go }), [go]);

  // Notify parent of index changes so it can track the current image.
  useEffect(() => { onIndexChange?.(idx); }, [idx, onIndexChange]);

  // Timer just advances by 1 — the broken-skip effect handles jumping over bad images.
  const resetTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setIdx((i) => (i + 1) % paths.length);
    }, 10000);
  }, [paths.length]);

  useEffect(() => {
    if (validCount > 1) resetTimer();
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [validCount, resetTimer]);

  // Auto-skip when the current image turns broken (onError fired or initial broken).
  useEffect(() => {
    if (broken.has(idx) && validCount > 0) {
      const next = nextValid(idx, 1, broken);
      if (next !== idx) go(next);
    }
  }, [broken, idx, nextValid, go, validCount]);

  const prev = (e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation();
    go(nextValid(idx, -1, broken));
    resetTimer();
  };
  const next = (e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation();
    go(nextValid(idx, 1, broken));
    resetTimer();
  };

  const handleMouseEnter = () => {
    labelTimerRef.current = setTimeout(() => setShowLabel(true), 4000);
  };
  const handleMouseLeave = () => {
    if (labelTimerRef.current) clearTimeout(labelTimerRef.current);
    setShowLabel(false);
  };

  return (
    <div
      className="relative w-full h-full group/rot"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <img
        src={urls[idx]}
        alt={alt}
        onError={() => setBroken((prev) => new Set([...prev, idx]))}
        className={`w-full h-full object-cover transition-opacity duration-150 ${fade ? "opacity-100" : "opacity-0"} ${blur ? "blur-xl" : ""}`}
        loading="lazy"
      />
      {/* Filename label — appears after 4 s of hover, hides immediately on leave */}
      {showLabel && filename && (
        <div className="absolute bottom-0 left-0 right-0 px-2 py-1 bg-black/70 text-white text-xs truncate pointer-events-none">
          {filename}
        </div>
      )}
      {validCount > 1 && (
        <>
          <button
            onClick={prev}
            className="absolute left-1 top-1/2 -translate-y-1/2 opacity-0 group-hover/rot:opacity-100 transition-opacity bg-black/60 hover:bg-black/80 rounded-full p-0.5 text-white"
          >
            <ChevronLeft size={14} />
          </button>
          <button
            onClick={next}
            className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover/rot:opacity-100 transition-opacity bg-black/60 hover:bg-black/80 rounded-full p-0.5 text-white"
          >
            <ChevronRight size={14} />
          </button>
          <div className="absolute bottom-1 left-1/2 -translate-x-1/2 flex gap-1 opacity-0 group-hover/rot:opacity-100 transition-opacity">
            {paths.map((_, i) => broken.has(i) ? null : (
              <button
                key={i}
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); go(i); resetTimer(); }}
                className={`w-1.5 h-1.5 rounded-full transition-colors ${i === idx ? "bg-white" : "bg-white/40"}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
});

export default memo(ModelCard);

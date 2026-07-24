import { memo, useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { Package, Star, Heart, AlertCircle, Check, Layers, Printer, EyeOff, RotateCcw, Sparkles, Paintbrush, MoreHorizontal, ChevronLeft, ChevronRight, Lock } from "lucide-react";
import { Model, PrintStatus, PRINT_STATUS_CYCLE, api } from "../api/client";
import { useNSFW } from "../context/NSFWContext";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
import { isRecentlyAdded } from "../utils/recentlyAdded";
import { modelLinkTo } from "../utils/modelLink";
import { tagClass, visibleTags } from "../utils/modelTags";
import QuickAssignPopover from "./QuickAssignPopover";
import StarRating from "./StarRating";
import { invalidateModelViews } from "../hooks/queries/invalidation";
import { useStorageRecoverySignal, withStorageRecoverySignal } from "../hooks/useStorageRecoverySignal";

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
  /** Variant-group side panel (STUDIO-350). Return true to consume the click —
   *  the card stays a <Link> so Enter still activates it and ctrl/middle-click
   *  still opens the full group page, but a plain click opens the panel. */
  onOpenGroup?: (model: Model) => boolean;
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

// Scanner-detected variant attributes (#609). Support status is the most useful
// at-a-glance signal for printing, so it gets distinct, colour-coded styling.
const SUPPORT_STATUS_STYLE: Record<string, string> = {
  "unsupported":   "bg-rose-900 text-rose-300",
  "pre-supported": "bg-emerald-900 text-emerald-300",
  "supported":     "bg-emerald-900 text-emerald-300",
};

const SUPPORT_STATUS_LABEL: Record<string, string> = {
  "unsupported":   "Unsupported",
  "pre-supported": "Pre-supported",
  "supported":     "Supported",
};

// Memoized: the Library re-renders the whole grid on every selection / keyboard-
// focus / drag tick. Without memo, all N cards on the page re-render each time
// (per-keystroke during keyboard nav). Props are stable across those ticks —
// `model` refs survive, callbacks are useCallback'd, `allTagSuggestions` is stable
// state — so the default shallow compare re-renders only the card whose
// `selected`/`focused` actually changed (#382).
function ModelCard({ model, selected = false, onSelect, backTo, onMutate, excludedView = false, onRemoved, hasGuide = false, allTagSuggestions = [], focused = false, onOpenGroup }: Props) {
  const storageRecoverySignal = useStorageRecoverySignal();
  const [cardImageFailed, setCardImageFailed] = useState(false);
  const location = useLocation();
  const cardRef = useRef<HTMLDivElement>(null);

  // Keep the keyboard-focused card in view as the user moves with WASD (#169).
  useEffect(() => {
    if (focused) cardRef.current?.scrollIntoView({ block: "nearest" });
  }, [focused]);
  const { showNSFW } = useNSFW();
  const { settings } = useAppSettings();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [nsfw, setNsfw] = useState(model.nsfw);
  const isNew = isRecentlyAdded(model.created_at, settings.recent_days);

  const [favorite, setFavorite] = useState(model.is_favorite);
  const [locked, setLocked] = useState(model.locked);
  const [excluding, setExcluding] = useState(false);
  const [printStatus, setPrintStatus] = useState<PrintStatus>(model.print_status ?? "none");
  const [localTags, setLocalTags] = useState<string[]>(model.tags ?? []);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [rating, setRating] = useState<number | null>(model.user_rating ?? null);
  const [imageCleared, setImageCleared] = useState(false);
  const [localTitle, setLocalTitle] = useState(model.title ?? "");
  // Group display name: the durable VariantGroup's label is authoritative
  // (#678 Phase 5) — model.character is a scanner-derived attribute the next
  // rescan can silently change, and merge/patch no longer mirror the group
  // label onto it. Fall back to character for the (should-be-rare) case of a
  // group with no label yet.
  const [localGroupLabel, setLocalGroupLabel] = useState(model.variant_group?.label ?? model.character ?? "");
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const nameInputRef = useRef<HTMLInputElement>(null);

  const variantCount = model.variant_count ?? 1;
  const isGroup = variantCount > 1;

  // Explain why this group exists (#617): manual vs the scanner's reason/confidence.
  const groupExplain = (() => {
    const g = model.variant_group;
    if (!g) return `${variantCount} variants`;
    if (g.source === "manual") return "Grouped manually";
    const pct = g.confidence != null ? ` (${Math.round(g.confidence * 100)}%)` : "";
    return g.reason ? `Auto-grouped — ${g.reason}${pct}` : "Auto-grouped";
  })();

  // Keep the optimistic name in sync if the parent reloads with fresh data.
  useEffect(() => { setLocalTitle(model.title ?? ""); }, [model.title]);
  useEffect(() => {
    setLocalGroupLabel(model.variant_group?.label ?? model.character ?? "");
  }, [model.variant_group?.label, model.character]);
  useEffect(() => { if (editingName) nameInputRef.current?.select(); }, [editingName]);

  const startRename = () => {
    setNameDraft(isGroup ? localGroupLabel : (localTitle || model.name));
    setEditingName(true);
  };

  // Renaming a variant group relabels the durable VariantGroup row, so every
  // member follows; a plain model just updates its own title. Post-#678 every
  // isGroup card carries a variant_group_id — the ch:-fallback (character with
  // no durable group) no longer groups anything.
  const renameGroup = async (next: string) => {
    const prev = localGroupLabel;
    if (model.variant_group_id == null) {
      toast("Can't rename a group with no durable group id.", "error");
      return;
    }
    setLocalGroupLabel(next);
    try {
      await api.models.patchGroup(model.variant_group_id, { label: next });
      invalidateModelViews(queryClient, { modelId: model.id });
      onMutate?.();
    } catch {
      setLocalGroupLabel(prev);  // revert on failure
      toast("Couldn't rename group — try again.", "error");
    }
  };

  const renameModel = async (next: string) => {
    const prev = localTitle;
    setLocalTitle(next);
    try {
      await api.models.update(model.id, { title: next });
      invalidateModelViews(queryClient, { modelId: model.id });
      onMutate?.();
    } catch {
      setLocalTitle(prev);  // revert on failure
      toast("Couldn't rename — try again.", "error");
    }
  };

  const commitRename = async () => {
    const next = nameDraft.trim();
    setEditingName(false);
    const current = isGroup ? localGroupLabel : (localTitle || model.name);
    if (!next || next === current) return;
    await (isGroup ? renameGroup(next) : renameModel(next));
  };

  const changeRating = async (next: number | null) => {
    const prev = rating;
    setRating(next);
    try {
      await api.models.setRating(model.id, next);
      invalidateModelViews(queryClient, { modelId: model.id, includeVariants: false });
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
      invalidateModelViews(queryClient, { modelId: model.id, includeVariants: false });
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
      invalidateModelViews(queryClient, { modelId: model.id, includeVariants: false });
      onMutate?.();
    } catch {
      setFavorite(!next);  // revert on failure
      toast("Couldn't update favorite — try again.", "error");
    }
  };

  const toggleLocked = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const next = !locked;
    setLocked(next);
    try {
      await api.models.setLocked(model.id, next);
      invalidateModelViews(queryClient, { modelId: model.id, includeVariants: false });
      onMutate?.();
    } catch {
      setLocked(!next);  // revert on failure
      toast("Couldn't update lock — try again.", "error");
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
      invalidateModelViews(queryClient, { modelId: model.id, includeVariants: false });
      onMutate?.();
    } catch {
      setPrintStatus(printStatus);  // revert on failure
      toast("Couldn't update print status — try again.", "error");
    }
  };

  const toggleExclude = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (excluding) return;  // already in flight — ignore repeat clicks (STUDIO-167)
    // In the normal library this hides the model; in the Excluded view it restores it.
    const next = !excludedView;
    setExcluding(true);
    try {
      await api.models.setExcluded(model.id, next);
      invalidateModelViews(queryClient, { modelId: model.id, includeVariants: false });
      onRemoved?.(model.id);  // card leaves the current view
      onMutate?.();
      toast(next ? "Model excluded from the viewer." : "Model restored.", "success");
    } catch {
      toast(next ? "Couldn't exclude the model — try again." : "Couldn't restore the model — try again.", "error");
    } finally {
      setExcluding(false);
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

  // Static card image: explicit Library image, else selected thumbnail, else first gallery image.
  // Gallery images remain a fallback, but shouldn't hide thumbnail changes.
  const baseCardImageUrl = (() => {
    if (imageCleared) return null;
    const gallery = model.image_paths ?? [];
    // Between bulk-enrich and import-apply, image_paths can hold remote CDN URLs
    // (apply later swaps them for local paths). Serve those directly; only wrap
    // local filesystem paths through the file endpoint.
    const resolve = (p: string) => (/^https?:\/\//i.test(p) ? p : api.fileUrl(p));
    if (model.primary_image_path) return resolve(model.primary_image_path);
    if (thumbnail) return thumbnail;
    if (gallery.length > 0) return resolve(gallery[0]);
    return null;
  })();
  const cardImageUrl = baseCardImageUrl && cardImageFailed
    ? withStorageRecoverySignal(baseCardImageUrl, storageRecoverySignal)
    : baseCardImageUrl;

  // An explicit VariantGroup.label (set via rename or a manual merge) is the
  // group's real identity and must always win — falling back to the rep
  // model's own `title` field made a rename via renameGroup() appear to
  // silently fail, since that field belongs to whichever model happens to be
  // the rep, not the group (#1062). But when there's no explicit label yet
  // (localGroupLabel is only the raw scanner-derived `character` slug, e.g.
  // "1.Firestar-Regular-stls"), the rep's enriched title is still a better
  // display name than the slug — so that preference only applies there.
  const hasExplicitGroupLabel = Boolean(model.variant_group?.label);
  const displayName = isGroup
    ? (hasExplicitGroupLabel ? localGroupLabel : (localTitle || localGroupLabel))
    : (localTitle || model.name);
  const uniqueTags = visibleTags(model, localTags);

  // Scanner-detected variant attributes (#609): support status leads (printing-
  // relevant), then cut/slicer/version as neutral chips.
  const attrs = model.parsed_attributes ?? {};
  const secondaryAttrs = [attrs.cut_status, attrs.slicer, attrs.version].filter(Boolean) as string[];

  const handleCardClick = (e: React.MouseEvent) => {
    // Let the browser handle "open in a new tab/window" untouched.
    const wantsNewTab = e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1;
    if (!wantsNewTab && onOpenGroup?.(model)) {
      e.preventDefault();
      return;
    }
    sessionStorage.setItem("library_scroll", String(window.scrollY));
  };

  const linkTo = modelLinkTo(model);

  return (
    <div ref={cardRef} className="relative h-full">
    <Link
      to={linkTo}
      state={{ from: backTo ?? location.pathname + location.search }}
      onClick={handleCardClick}
      // Anchors are native drag sources: dragging the link drags its URL.
      // Without this, mouse-selecting text in the inline rename input starts a
      // link-drag and drops the URL into the field instead of selecting text.
      draggable={false}
      className={`group bg-panel rounded-lg overflow-hidden border transition-colors flex flex-col h-full ${
        selected
          ? "border-accent-start ring-1 ring-indigo-500/50"
          : focused
          ? "border-indigo-400 ring-2 ring-indigo-400"
          : "border-border-subtle hover:border-accent-start"
      }`}
    >
      <div className="aspect-square bg-panel-secondary relative overflow-hidden">
        {cardImageUrl ? (
          <img
            src={cardImageUrl}
            alt={displayName}
            className={`w-full h-full object-cover group-hover:scale-105 transition-transform duration-300 ${nsfw && !showNSFW ? "blur-xl" : ""}`}
            loading="lazy"
            onError={() => setCardImageFailed(true)}
            onLoad={() => setCardImageFailed(false)}
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
          // Same treatment as the empty state on Model Detail's image panel
          // (ImageColumn.tsx) — one placeholder look across the app.
          <div className="w-full h-full bg-panel flex items-center justify-center text-text-muted-alt">
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
          className="absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-black/70 hover:bg-black/90 text-xs px-2 py-0.5 rounded border border-border-divider text-text-primary-alt2 hover:text-white"
        >
          {nsfw ? "SFW" : "NSFW"}
        </button>

        {/* Selection checkbox — hover-visible, always visible when selected */}
        {onSelect && (
          <div
            onClick={handleSelect}
            className={`absolute top-2 left-2 z-10 w-5 h-5 rounded border-2 flex items-center justify-center cursor-pointer transition-all ${
              selected
                ? "bg-accent-start border-indigo-400 opacity-100"
                : "bg-black/60 border-gray-400 opacity-0 group-hover:opacity-100"
            }`}
          >
            {selected && <Check size={11} className="text-white" strokeWidth={3} />}
          </div>
        )}

        {/* Badges — offset right of checkbox when selectable */}
        <div className={`absolute top-2 flex flex-col gap-1 ${onSelect ? "left-9" : "left-2"}`}>
          {isNew && (
            <span className="flex items-center gap-1 bg-accent-start/90 text-white text-xs px-1.5 py-0.5 rounded font-medium">
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
            <span
              title={groupExplain}
              className="flex items-center gap-1 bg-accent-end/90 text-white text-xs px-1.5 py-0.5 rounded font-medium"
            >
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
            <span className="bg-black/70 text-xs px-1.5 py-0.5 rounded text-text-primary-alt2">
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
                  : "text-text-secondary opacity-0 group-hover:opacity-100"
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
                  : "text-text-secondary hover:text-yellow-300 opacity-0 group-hover:opacity-100"
              }`}
            >
              <Star size={13} fill={favorite ? "currentColor" : "none"} />
            </button>
            <button
              onClick={toggleLocked}
              title={locked ? "Locked — unlock to allow file/category/name changes" : "Lock: block file, category, and part-name changes"}
              className={`p-1 rounded bg-black/60 hover:bg-black/80 transition-all ${
                locked
                  ? "text-cyan-400 opacity-100"
                  : "text-text-secondary hover:text-cyan-300 opacity-0 group-hover:opacity-100"
              }`}
            >
              <Lock size={13} fill={locked ? "currentColor" : "none"} />
            </button>
            <button
              onClick={toggleExclude}
              disabled={excluding}
              aria-busy={excluding}
              title={excludedView ? "Restore to the viewer" : "Exclude from the viewer (files kept on disk)"}
              className={`p-1 rounded bg-black/60 hover:bg-black/80 transition-all ${
                excluding
                  ? "text-text-secondary opacity-100 cursor-wait"
                  : excludedView
                  ? "text-emerald-400 opacity-100 hover:text-emerald-300"
                  : "text-text-secondary hover:text-red-300 opacity-0 group-hover:opacity-100"
              }`}
            >
              {excluding
                ? <span className="block w-[13px] h-[13px] rounded-full border-2 border-current border-t-transparent animate-spin" />
                : excludedView ? <RotateCcw size={13} /> : <EyeOff size={13} />}
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
            className="text-sm font-medium bg-panel-secondary border border-accent-start rounded px-1 py-0.5 text-text-primary focus:outline-none"
          />
        ) : (
          <p
            className="text-sm font-medium truncate text-text-primary"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
            onDoubleClick={(e) => { e.preventDefault(); e.stopPropagation(); startRename(); }}
            title={isGroup ? "Double-click to rename this group" : "Double-click to rename"}
          >
            {displayName}
          </p>
        )}

        {(attrs.support_status || secondaryAttrs.length > 0) && (
          <div className="flex flex-wrap gap-1">
            {attrs.support_status && (
              <span
                title="Print-support status"
                className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                  SUPPORT_STATUS_STYLE[attrs.support_status] ?? "bg-panel-secondary text-text-secondary"
                }`}
              >
                {SUPPORT_STATUS_LABEL[attrs.support_status] ?? attrs.support_status}
              </span>
            )}
            {secondaryAttrs.map((a) => (
              <span key={a} className="text-xs px-1.5 py-0.5 rounded bg-panel-secondary text-text-secondary capitalize">
                {a}
              </span>
            ))}
          </div>
        )}

        {uniqueTags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {uniqueTags.slice(0, 4).map((tag) => (
              <span
                key={tag}
                className={`text-xs px-1.5 py-0.5 rounded ${tagClass(tag)}`}
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
            {model.like_count != null && (
              <span title="Likes on the source site" className="flex items-center gap-0.5 text-xs text-text-secondary-alt">
                <Heart size={11} fill="currentColor" />
                {model.like_count.toLocaleString()}
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
                  : "text-text-muted hover:text-text-primary-alt2 opacity-0 group-hover:opacity-100 focus:opacity-100"
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
  {
    paths: string[];
    alt: string;
    blur: boolean;
    autoRotate?: boolean;
    rotationMs?: number;
    onIndexChange?: (idx: number) => void;
  }
>(function GalleryRotatorInner({
  paths,
  alt,
  blur,
  autoRotate = true,
  rotationMs = 10000,
  onIndexChange,
}, ref) {
  const storageRecoverySignal = useStorageRecoverySignal();
  const [broken, setBroken] = useState<Set<number>>(new Set());
  const [idx, setIdx] = useState(0);
  const [fade, setFade] = useState(true);
  const [showLabel, setShowLabel] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const labelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const urls = paths.map((p, imageIndex) => withStorageRecoverySignal(
    api.fileUrl(p),
    broken.has(imageIndex) ? storageRecoverySignal : 0,
  ));
  const validCount = paths.length - broken.size;
  const filename = paths[idx]?.replace(/\\/g, "/").split("/").pop() ?? "";

  // Reset to a known-good state whenever the actual set of images changes —
  // e.g. a new upload adds paths, or the parent stays mounted across model
  // navigation (no remount). Without this, idx/broken carry over from the
  // previous paths array: idx can point past the end of a shorter list, or
  // sit on an index this array never actually failed at, rendering a blank
  // image with no way to recover (goTo() just re-sets the same stale idx).
  const pathsKey = paths.join("|");
  useEffect(() => {
    setIdx(0);
    setBroken(new Set());
  }, [pathsKey]);

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

  // Clear any pending fade/label timer on unmount so it can't setState after
  // teardown — labelTimerRef was previously only cleared on mouse-leave, so a
  // card unmounted while hovered (before the 4s label delay) leaked the timer.
  useEffect(() => () => {
    if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
    if (labelTimerRef.current) clearTimeout(labelTimerRef.current);
  }, []);

  useImperativeHandle(ref, () => ({ goTo: go }), [go]);

  // Notify parent of index changes so it can track the current image.
  useEffect(() => { onIndexChange?.(idx); }, [idx, onIndexChange]);

  // Timer just advances by 1 — the broken-skip effect handles jumping over bad images.
  const resetTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (!autoRotate || paths.length <= 1) {
      timerRef.current = null;
      return;
    }
    timerRef.current = setInterval(() => {
      setIdx((i) => (i + 1) % paths.length);
    }, rotationMs);
  }, [autoRotate, paths.length, rotationMs]);

  useEffect(() => {
    if (validCount > 1 && autoRotate) resetTimer();
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [autoRotate, validCount, resetTimer]);

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
        onLoad={() => setBroken((prev) => {
          if (!prev.has(idx)) return prev;
          const next = new Set(prev);
          next.delete(idx);
          return next;
        })}
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

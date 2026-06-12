import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Package, Star, AlertCircle, Check, Layers, Printer, EyeOff, RotateCcw, Sparkles, Paintbrush, MoreHorizontal } from "lucide-react";
import { Model, PrintStatus, PRINT_STATUS_CYCLE, api } from "../api/client";
import { useNSFW } from "../context/NSFWContext";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
import { isRecentlyAdded } from "../utils/recentlyAdded";
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

export default function ModelCard({ model, selected = false, onSelect, backTo, onMutate, excludedView = false, onRemoved, hasGuide = false, allTagSuggestions = [] }: Props) {
  const location = useLocation();
  const { showNSFW } = useNSFW();
  const { settings } = useAppSettings();
  const { toast } = useToast();
  const [nsfw, setNsfw] = useState(model.nsfw);
  const isNew = isRecentlyAdded(model.created_at, settings.recent_days);

  const [favorite, setFavorite] = useState(model.is_favorite);
  const [queued, setQueued] = useState(model.in_queue);
  const [printStatus, setPrintStatus] = useState<PrintStatus>(model.print_status ?? "none");
  const [localTags, setLocalTags] = useState<string[]>(model.tags ?? []);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [rating, setRating] = useState<number | null>(model.user_rating ?? null);

  const variantCount = model.variant_count ?? 1;
  const isGroup = variantCount > 1;

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

  const toggleQueue = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const next = !queued;
    setQueued(next);
    try {
      await api.models.setQueue(model.id, next);
      onMutate?.();
    } catch {
      setQueued(!next);  // revert on failure
      toast("Couldn't update the print queue — try again.", "error");
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

  const thumbnail = model.thumbnail_path
    ? api.fileUrl(model.thumbnail_path)
    : model.thumbnail_url ?? null;

  const displayName = isGroup && model.character
    ? model.character
    : (model.title || model.name);
  const allTagsDisplay = [...(model.auto_tags ?? []), ...localTags];
  const uniqueTags = [...new Set(allTagsDisplay)];

  const handleCardClick = () => {
    sessionStorage.setItem("library_scroll", String(window.scrollY));
  };

  const linkTo = isGroup && model.creator_id && model.character
    ? `/groups/${model.creator_id}/${encodeURIComponent(model.character)}`
    : `/models/${model.id}`;

  return (
    <div className="relative">
    <Link
      to={linkTo}
      state={{ from: backTo ?? location.pathname + location.search }}
      onClick={handleCardClick}
      className={`group bg-gray-900 rounded-lg overflow-hidden border transition-colors flex flex-col ${
        selected
          ? "border-indigo-500 ring-1 ring-indigo-500/50"
          : "border-gray-800 hover:border-indigo-500"
      }`}
    >
      <div className="aspect-square bg-gray-800 relative overflow-hidden">
        {thumbnail ? (
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
          {/* Favorite + queue toggles. On a variant group these act on the
              representative variant (model.id) — flag the model for printing now,
              pick the specific variant later from the group page. The actions
              also remain available on each individual variant. */}
          <div className="flex gap-1">
            <button
              onClick={toggleQueue}
              title={
                isGroup
                  ? queued ? "Remove model from print queue" : "Add model to print queue (pick variant later)"
                  : queued ? "Remove from print queue" : "Add to print queue"
              }
              className={`p-1 rounded bg-black/60 hover:bg-black/80 transition-all ${
                queued
                  ? "text-sky-400 opacity-100"
                  : "text-gray-400 hover:text-sky-300 opacity-0 group-hover:opacity-100"
              }`}
            >
              <Printer size={13} />
            </button>
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
        <p className="text-sm font-medium truncate text-gray-100">{displayName}</p>

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
        onClose={() => setPopoverOpen(false)}
      />
    )}
    </div>
  );
}

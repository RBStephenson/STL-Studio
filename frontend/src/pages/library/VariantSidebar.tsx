// Docked right-side panel showing one variant group's members, opened from a
// Library card badged "N variants" instead of navigating away to the Variant
// Group page (STUDIO-350, design ADDENDUM §8).
//
// The open/closed state is a URL query param (`?group=<id>`) owned by
// Library.tsx, not local state — that keeps Back, deep links, and reload
// working. This component only renders what the param resolves to.

import { useCallback, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Boxes, X, ArrowRight, RefreshCw } from "lucide-react";
import { api, Model } from "../../api/client";
import { tagClass, visibleTags } from "../../utils/modelTags";

export const PANEL_DEFAULT_WIDTH = 380;
export const PANEL_MIN_WIDTH = 300;

/** Hard ceiling plus a share-of-window ceiling. Without the second one a wide
 *  panel starves the model grid — the same cramped-column problem the grid's
 *  own breakpoints had. */
export function maxPanelWidth(windowWidth: number): number {
  return Math.max(PANEL_MIN_WIDTH, Math.min(720, Math.round(windowWidth * 0.45)));
}

export function clampPanelWidth(width: number, windowWidth: number): number {
  return Math.min(Math.max(width, PANEL_MIN_WIDTH), maxPanelWidth(windowWidth));
}

/** Row density steps with the panel's own width, not the viewport's — the point
 *  of dragging it wider is that the rows use the space. */
export function rowDensity(width: number): { thumb: number; tags: number; title: string } {
  if (width >= 600) return { thumb: 80, tags: 5, title: "text-sm" };
  if (width >= 460) return { thumb: 68, tags: 4, title: "text-[13.5px]" };
  return { thumb: 56, tags: 3, title: "text-[13px]" };
}

interface Props {
  groupId: number;
  /** Shown in the header until the fetch resolves, so the panel is never
   *  anonymous while loading — the card that opened it already knows the name. */
  fallbackLabel: string;
  /** Route to the full Variant Group page for this group. */
  fullViewTo: string;
  onClose: () => void;
  /** Current panel width; owned by Library so it can persist across opens. */
  width: number;
  onWidthChange: (width: number) => void;
}

export default function VariantSidebar({
  groupId, fallbackLabel, fullViewTo, onClose, width, onWidthChange,
}: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const density = rowDensity(width);

  // Drag the left edge. Pointer capture keeps the drag alive when the cursor
  // outruns the 6px handle, which it always does.
  const onHandlePointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    const onMove = (ev: PointerEvent) => {
      // Panel is docked right, so its width is the gap from cursor to the edge.
      onWidthChange(clampPanelWidth(window.innerWidth - ev.clientX, window.innerWidth));
    };
    const onUp = () => {
      handle.releasePointerCapture(e.pointerId);
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
  }, [onWidthChange]);

  // A drag-only handle is unusable without a mouse, so mirror it on the keyboard.
  const onHandleKeyDown = useCallback((e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 64 : 16;
    const w = window.innerWidth;
    if (e.key === "ArrowLeft") { e.preventDefault(); onWidthChange(clampPanelWidth(width + step, w)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); onWidthChange(clampPanelWidth(width - step, w)); }
    else if (e.key === "Home") { e.preventDefault(); onWidthChange(maxPanelWidth(w)); }
    else if (e.key === "End") { e.preventDefault(); onWidthChange(PANEL_MIN_WIDTH); }
  }, [width, onWidthChange]);

  // Shrinking the window must not leave the panel wider than its share.
  useEffect(() => {
    const onResize = () => onWidthChange(clampPanelWidth(width, window.innerWidth));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [width, onWidthChange]);

  const { data, isPending, isError, refetch, isFetching } = useQuery({
    queryKey: ["variant-group", groupId],
    // creator/character are ignored by the API when a group id is supplied.
    queryFn: () => api.models.variants(0, "", groupId),
  });

  // Move focus into the panel when it opens so keyboard users land here rather
  // than continuing through the grid behind it.
  useEffect(() => {
    closeRef.current?.focus();
  }, [groupId]);

  // Escape closes, matching every other dismissible surface in the app.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const items: Model[] = data?.items ?? [];
  const label = items.find((m) => m.variant_group?.label)?.variant_group?.label || fallbackLabel;

  return (
    <aside
      aria-label={`Variants of ${label}`}
      style={{ width }}
      className="relative shrink-0 border-l border-border-subtle bg-panel flex flex-col
                 max-lg:fixed max-lg:right-0 max-lg:top-14 max-lg:bottom-0 max-lg:z-30 max-lg:shadow-2xl"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize variants panel"
        aria-valuenow={width}
        aria-valuemin={PANEL_MIN_WIDTH}
        aria-valuemax={maxPanelWidth(typeof window === "undefined" ? width : window.innerWidth)}
        tabIndex={0}
        title="Drag to resize — double-click to reset"
        onPointerDown={onHandlePointerDown}
        onKeyDown={onHandleKeyDown}
        onDoubleClick={() => onWidthChange(PANEL_DEFAULT_WIDTH)}
        className="absolute left-0 top-0 bottom-0 w-1.5 -ml-0.5 z-10 cursor-col-resize
                   hover:bg-accent-start/60 focus-visible:bg-accent-start
                   outline-none transition-colors"
      />

      <div className="flex items-center gap-2.5 px-5 pt-5 pb-4 border-b border-border-subtle">
        <Boxes size={18} className="text-indigo-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-[15px] font-bold text-text-primary truncate">{label}</p>
          <p className="text-xs text-text-muted mt-0.5">
            {isPending ? "Loading…" : `${items.length} variant${items.length === 1 ? "" : "s"}`}
          </p>
        </div>
        <button
          ref={closeRef}
          onClick={onClose}
          title="Close"
          aria-label="Close variants panel"
          className="shrink-0 p-1.5 rounded bg-panel-secondary border border-border-subtle
                     text-text-muted hover:text-text-primary transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {isPending && (
          <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading variants">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 p-2">
                <div
                  style={{ width: density.thumb, height: density.thumb }}
                  className="shrink-0 rounded-[9px] bg-panel-secondary animate-pulse"
                />
                <div className="flex-1 flex flex-col gap-1.5">
                  <div className="h-3 w-2/3 rounded bg-panel-secondary animate-pulse" />
                  <div className="h-2.5 w-1/3 rounded bg-panel-secondary animate-pulse" />
                </div>
              </div>
            ))}
          </div>
        )}

        {isError && (
          <div className="text-center py-8">
            <p className="text-sm text-text-muted mb-3">Could not load this group's variants.</p>
            <button
              onClick={() => void refetch()}
              disabled={isFetching}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-panel-secondary
                         border border-border text-sm text-text-primary-alt2 disabled:opacity-60"
            >
              <RefreshCw size={13} className={isFetching ? "animate-spin" : ""} /> Try again
            </button>
          </div>
        )}

        {!isPending && !isError && items.length === 0 && (
          <p className="text-sm text-text-muted text-center py-8">
            This group has no models in it.
          </p>
        )}

        {!isPending && !isError && items.length > 0 && (
          <div className="flex flex-col gap-2">
            {items.map((m) => (
              <Link
                key={m.id}
                to={`/models/${m.id}`}
                className="flex items-center gap-3 p-2 rounded-[10px] bg-panel-secondary
                           border border-border-subtle hover:border-accent-start
                           transition-colors outline-none
                           focus-visible:ring-2 focus-visible:ring-accent-start"
              >
                <div
                  style={{ width: density.thumb, height: density.thumb }}
                  className="relative shrink-0 rounded-[9px] border border-border-subtle
                             bg-panel overflow-hidden flex items-center justify-center"
                >
                  {m.thumbnail_path || m.thumbnail_url ? (
                    <img
                      src={m.thumbnail_path
                        ? api.fileUrl(m.thumbnail_path, m.updated_at)
                        : m.thumbnail_url ?? ""}
                      alt=""
                      loading="lazy"
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <Boxes size={Math.round(density.thumb * 0.4)} className="text-border" />
                  )}
                  {m.is_group_rep && (
                    <span className="absolute -bottom-0.5 -right-0.5 px-1 py-0.5 rounded
                                     bg-accent-end/90 text-white text-[7.5px] font-bold leading-none">
                      REP
                    </span>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`${density.title} font-semibold text-text-primary truncate`}>
                    {m.title || m.name}
                  </p>
                  {visibleTags(m).length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {/* Chip count follows the panel width — see rowDensity. */}
                      {visibleTags(m).slice(0, density.tags).map((tag) => (
                        <span
                          key={tag}
                          className={`text-[10px] px-1.5 py-0.5 rounded ${tagClass(tag)}`}
                        >
                          {tag}
                        </span>
                      ))}
                      {visibleTags(m).length > density.tags && (
                        <span className="text-[10px] px-1 py-0.5 text-text-muted">
                          +{visibleTags(m).length - density.tags}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      <div className="px-5 py-3.5 border-t border-border-subtle">
        <Link
          to={fullViewTo}
          className="flex items-center justify-center gap-1.5 py-2 rounded bg-panel-secondary
                     border border-border text-[12.5px] text-text-primary-alt2
                     hover:text-text-primary transition-colors"
        >
          Open full view <ArrowRight size={12} />
        </Link>
      </div>
    </aside>
  );
}

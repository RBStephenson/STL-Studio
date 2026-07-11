// Library results grid: loading skeleton, empty state, and the card grid —
// with optional drag-to-group DnD context and drag overlay. Extracted from
// Library.tsx (STUDIO-63 P4) — behavior-preserving; markup moved verbatim.
//
// The DnD state and drag handlers live in the page shell (they open the
// merge-confirm modals) and are passed in; this component only renders.

import { useCallback } from "react";
import {
  DndContext, DragOverlay, pointerWithin,
  useDraggable, useDroppable,
  DragStartEvent, DragEndEvent, Announcements,
} from "@dnd-kit/core";
import type { SensorDescriptor, SensorOptions } from "@dnd-kit/core";
import { Package, GripVertical, Search, RefreshCw } from "lucide-react";
import { api, Model } from "../../api/client";
import ModelCard from "../../components/ModelCard";
import EmptyState from "../../components/EmptyState";
import ErrorState from "../../components/ErrorState";

/** Wraps a library card so it can be dragged onto another card to form a variant
 *  group. The drag listeners live on a small hover grip (bottom-left) so plain
 *  clicks still navigate and the card's other hover controls keep working.
 *  Group cards (variant_count > 1) are draggable too — dropping one group onto
 *  another merges the whole set (#136). */
function DraggableCard({ model, draggingCreatorId, children }: {
  model: Model;
  draggingCreatorId: number | null;
  children: React.ReactNode;
}) {
  const isGroup = (model.variant_count ?? 1) > 1;
  const { setNodeRef: dragRef, listeners, attributes, isDragging } =
    useDraggable({ id: model.id });
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
        validTarget ? "ring-2 ring-accent-start" : ""
      }`}
    >
      <button
        {...listeners}
        {...attributes}
        title={isGroup
          ? "Drag onto another card to merge these groups"
          : "Drag onto another model to group them as variants"}
        aria-label={isGroup ? "Drag to merge group" : "Drag to group"}
        className="absolute bottom-2 left-2 z-20 p-1 rounded bg-black/60 hover:bg-black/90 text-text-primary-alt2 hover:text-white cursor-grab active:cursor-grabbing touch-none opacity-0 group-hover/drag:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent-start outline-none transition-opacity"
      >
        <GripVertical size={14} />
      </button>
      {children}
    </div>
  );
}

interface ModelGridProps {
  loading: boolean;
  isError: boolean;
  onRetry: () => void;
  onClearFilters: () => void;
  onScanLibrary: () => void;
  models: Model[];
  selection: Set<number>;
  onSelect: (id: number, shiftKey: boolean) => void;
  onMutate: () => void;
  excludedView: boolean;
  onRemoved: (id: number) => void;
  guideModelIds: Set<number>;
  allTagSuggestions: { tag: string; count: number }[];
  focusedIndex: number;
  gridRef: React.RefObject<HTMLDivElement | null>;
  dndEnabled: boolean;
  dndSensors: SensorDescriptor<SensorOptions>[];
  dndAnnouncements: Announcements;
  onDragStart: (e: DragStartEvent) => void;
  onDragEnd: (e: DragEndEvent) => void;
  onDragCancel: () => void;
  draggingModel: Model | null;
  dragCount: number;
}

function CardGrid({
  models, selection, onSelect, onMutate, excludedView, onRemoved,
  guideModelIds, allTagSuggestions, focusedIndex,
}: Pick<ModelGridProps, "models" | "selection" | "onSelect" | "onMutate" | "excludedView" | "onRemoved" | "guideModelIds" | "allTagSuggestions" | "focusedIndex">) {
  return (
    <>
      {models.map((m, i) => (
        <ModelCard
          key={m.id}
          model={m}
          selected={selection.has(m.id)}
          onSelect={onSelect}
          onMutate={onMutate}
          excludedView={excludedView}
          onRemoved={onRemoved}
          hasGuide={guideModelIds.has(m.id)}
          allTagSuggestions={allTagSuggestions}
          focused={focusedIndex === i}
        />
      ))}
    </>
  );
}

export default function ModelGrid(props: ModelGridProps) {
  const {
    loading, isError, onRetry, onClearFilters, onScanLibrary,
    models, gridRef, dndEnabled, dndSensors, dndAnnouncements,
    onDragStart, onDragEnd, onDragCancel, draggingModel, dragCount,
  } = props;

  if (isError) {
    return (
      <ErrorState
        title="Couldn't load your library"
        message="The library index couldn't be read. It may be missing, corrupted, or on a drive that's currently unavailable."
        onRetry={onRetry}
        padding="72px 32px"
      />
    );
  }

  if (loading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
        {Array.from({ length: 10 }).map((_, i) => (
          <div
            key={i}
            className="relative aspect-square overflow-hidden rounded-[13px]"
            style={{ background: "#141519", border: "1px solid #1a1b21" }}
          >
            <div className="stl-shimmer-overlay" />
          </div>
        ))}
      </div>
    );
  }

  if (models.length === 0) {
    return (
      <EmptyState
        icon={Search}
        heading="No models found"
        body="Nothing matches your current filters. Adjust your search, or scan your library folders for new models."
        padding="72px 32px"
        secondaryAction={{ label: "Clear filters", onClick: onClearFilters }}
        primaryAction={{ label: "Scan library", onClick: onScanLibrary, icon: RefreshCw }}
      />
    );
  }

  if (!dndEnabled) {
    return (
      <div ref={gridRef} className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
        <CardGrid {...props} />
      </div>
    );
  }

  return (
    <DndContext
      sensors={dndSensors}
      collisionDetection={pointerWithin}
      accessibility={{ announcements: dndAnnouncements }}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={onDragCancel}
    >
      <div ref={gridRef} className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
        {models.map((m, i) => (
          <DraggableCard key={m.id} model={m} draggingCreatorId={draggingModel?.creator_id ?? null}>
            <ModelCard
              model={m}
              selected={props.selection.has(m.id)}
              onSelect={props.onSelect}
              onMutate={props.onMutate}
              excludedView={props.excludedView}
              onRemoved={props.onRemoved}
              hasGuide={props.guideModelIds.has(m.id)}
              allTagSuggestions={props.allTagSuggestions}
              focused={props.focusedIndex === i}
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
            <div className="relative w-32 rounded-lg overflow-hidden border-2 border-accent-start bg-panel shadow-2xl shadow-black/60 rotate-2">
              {dragCount > 1 && (
                <div className="absolute -top-2 -right-2 z-10 min-w-[1.5rem] px-1.5 py-0.5 rounded-full bg-accent-start text-white text-xs font-semibold text-center shadow-lg">
                  {dragCount}
                </div>
              )}
              <div className="aspect-square bg-panel-secondary">
                {thumb ? (
                  <img src={thumb} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-text-muted">
                    <Package size={32} />
                  </div>
                )}
              </div>
              <p className="p-1.5 text-xs font-medium truncate text-text-primary">
                {dragCount > 1
                  ? `Grouping ${dragCount} models…`
                  : draggingModel.title || draggingModel.name}
              </p>
            </div>
          );
        })() : null}
      </DragOverlay>
    </DndContext>
  );
}

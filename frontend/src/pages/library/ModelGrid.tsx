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
import { Package, GripVertical } from "lucide-react";
import { api, Model } from "../../api/client";
import ModelCard from "../../components/ModelCard";

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
        validTarget ? "ring-2 ring-indigo-400" : ""
      }`}
    >
      <button
        {...listeners}
        {...attributes}
        title={isGroup
          ? "Drag onto another card to merge these groups"
          : "Drag onto another model to group them as variants"}
        aria-label={isGroup ? "Drag to merge group" : "Drag to group"}
        className="absolute bottom-2 left-2 z-20 p-1 rounded bg-black/60 hover:bg-black/90 text-gray-300 hover:text-white cursor-grab active:cursor-grabbing touch-none opacity-0 group-hover/drag:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-indigo-400 outline-none transition-opacity"
      >
        <GripVertical size={14} />
      </button>
      {children}
    </div>
  );
}

interface ModelGridProps {
  loading: boolean;
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
    loading, models, gridRef, dndEnabled, dndSensors, dndAnnouncements,
    onDragStart, onDragEnd, onDragCancel, draggingModel, dragCount,
  } = props;

  if (loading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
        {Array.from({ length: 24 }).map((_, i) => (
          <div key={i} className="aspect-square bg-gray-900 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (models.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-gray-600">
        <p className="text-lg">No models found</p>
        <p className="text-sm mt-1">Try scanning your library or adjusting filters</p>
      </div>
    );
  }

  if (!dndEnabled) {
    return (
      <div ref={gridRef} className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
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
      <div ref={gridRef} className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
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
            <div className="relative w-32 rounded-lg overflow-hidden border-2 border-indigo-400 bg-gray-900 shadow-2xl shadow-black/60 rotate-2">
              {dragCount > 1 && (
                <div className="absolute -top-2 -right-2 z-10 min-w-[1.5rem] px-1.5 py-0.5 rounded-full bg-indigo-500 text-white text-xs font-semibold text-center shadow-lg">
                  {dragCount}
                </div>
              )}
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

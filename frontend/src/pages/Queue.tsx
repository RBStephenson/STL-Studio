import { useState, useEffect, useCallback } from "react";
import { Printer, Check, History, GripVertical } from "lucide-react";
import {
  DndContext, closestCenter, PointerSensor, KeyboardSensor,
  useSensor, useSensors, DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext, arrayMove, rectSortingStrategy,
  useSortable, sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { api, Model, Collection } from "../api/client";
import ModelCard from "../components/ModelCard";
import BulkTagBar from "../components/BulkTagBar";
import { useToast } from "../context/ToastContext";

/** A queued card wrapped so it can be dragged to reorder. The drag handle lives
 *  in the bottom-left corner so it doesn't clash with the card's favorite/queue
 *  toggles (top-right) or badges (top-left); the rest of the card stays a link. */
function SortableCard({ model, onMutate, selected, onSelect }: {
  model: Model;
  onMutate: () => void;
  selected?: boolean;
  onSelect?: (id: number) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: model.id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    zIndex: isDragging ? 10 : undefined,
  };
  return (
    <div ref={setNodeRef} style={style} className="relative group/drag">
      <button
        {...attributes}
        {...listeners}
        title="Drag to reorder"
        aria-label="Drag to reorder"
        className="absolute bottom-2 left-2 z-20 p-1 rounded bg-black/60 hover:bg-black/90 text-gray-300 hover:text-white cursor-grab active:cursor-grabbing touch-none opacity-0 group-hover/drag:opacity-100 transition-opacity"
      >
        <GripVertical size={14} />
      </button>
      <ModelCard model={model} backTo="/queue" onMutate={onMutate} selected={selected} onSelect={onSelect} />
    </div>
  );
}

export default function Queue() {
  const [queued, setQueued] = useState<Model[]>([]);
  const [printed, setPrinted] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [collections, setCollections] = useState<Collection[]>([]);
  const { toast } = useToast();

  const toggleSelect = useCallback((id: number) => {
    setSelection(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelection(new Set(queued.map(m => m.id)));
  }, [queued]);

  const clearSelection = useCallback(() => setSelection(new Set()), []);

  const sensors = useSensors(
    // A small movement threshold lets a plain click still open the card.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [q, p] = await Promise.all([
        api.models.list({ in_queue: true, sort: "queue", group_variants: false, page_size: 200 }),
        api.models.list({ printed: true, sort: "printed_at", group_variants: false, page_size: 60 }),
      ]);
      setQueued(q.items);
      setPrinted(p.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.collections.list().then(setCollections).catch(() => {}); }, []);

  const onDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = queued.findIndex((m) => m.id === active.id);
    const newIndex = queued.findIndex((m) => m.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const next = arrayMove(queued, oldIndex, newIndex);
    setQueued(next);   // optimistic
    try {
      await api.models.reorderQueue(next.map((m) => m.id));
    } catch {
      toast("Couldn't save the new order — reloading.", "error");
      load();
    }
  };

  return (
    <div className="p-6">
      <div className="flex items-center gap-2 mb-2">
        <Printer size={20} className="text-sky-400" />
        <h1 className="text-2xl font-bold text-gray-100">Print Queue</h1>
        <span className="text-sm text-gray-500 ml-1">({queued.length})</span>
      </div>
      {queued.length > 1 && (
        <p className="text-xs text-gray-500 mb-6">
          Drag the handle to set your print order. Favorites always stay on top.
        </p>
      )}

      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="aspect-square bg-gray-900 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : queued.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-600">
          <Printer size={40} className="mb-3 opacity-40" />
          <p className="text-lg">Nothing queued to print</p>
          <p className="text-sm mt-1">Add models to the queue from any model's card or detail page</p>
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={queued.map((m) => m.id)} strategy={rectSortingStrategy}>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
              {queued.map((m) => (
                <SortableCard key={m.id} model={m} onMutate={load} selected={selection.has(m.id)} onSelect={toggleSelect} />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      {selection.size > 0 && (
        <BulkTagBar
          selectedIds={Array.from(selection)}
          totalOnPage={queued.length}
          onSelectAll={selectAll}
          onClear={clearSelection}
          onDone={load}
          collections={collections}
        />
      )}

      {/* Recently printed */}
      {printed.length > 0 && (
        <div className="mt-12">
          <div className="flex items-center gap-2 mb-4 pb-2 border-b border-gray-800">
            <History size={16} className="text-emerald-400" />
            <h2 className="text-lg font-semibold text-gray-200">Recently Printed</h2>
            <span className="text-sm text-gray-500">({printed.length})</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4 opacity-75">
            {printed.map((m) => (
              <div key={m.id} className="relative">
                <ModelCard model={m} backTo="/queue" />
                {m.printed_at && (
                  <span className="absolute top-2 left-2 z-10 flex items-center gap-1 bg-emerald-900/90 text-emerald-300 text-xs px-1.5 py-0.5 rounded font-medium">
                    <Check size={10} />
                    {new Date(m.printed_at).toLocaleDateString()}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

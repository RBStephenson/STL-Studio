import { useState, useEffect, useCallback, useRef } from "react";
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
import { api, Model } from "../api/client";
import ModelCard from "../components/ModelCard";
import { useToast } from "../context/ToastContext";

/** A queued card wrapped so the whole card can be dragged to reorder. We attach
 *  the drag listeners to the wrapper (not a small handle) because users expect to
 *  grab the card itself. A grip icon in the bottom-left is a visual affordance
 *  only. The PointerSensor's distance constraint keeps a plain click opening the
 *  card; the onClickCapture guard suppresses the trailing click after a real drag
 *  so dropping a card never also navigates into it. */
function SortableCard({ model, onMutate }: { model: Model; onMutate: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: model.id });

  // isDragging is already false by the time the trailing click fires, so latch it
  // while the drag is active and consume the next click in the capture phase.
  const draggedRef = useRef(false);
  useEffect(() => {
    if (isDragging) draggedRef.current = true;
  }, [isDragging]);
  const suppressClickAfterDrag = (e: React.MouseEvent) => {
    if (draggedRef.current) {
      e.preventDefault();
      e.stopPropagation();
      draggedRef.current = false;
    }
  };

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    zIndex: isDragging ? 10 : undefined,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClickCapture={suppressClickAfterDrag}
      className="relative group/drag cursor-grab active:cursor-grabbing"
    >
      {/* Visual affordance only — the whole card is the drag target. */}
      <div className="absolute bottom-2 left-2 z-20 p-1 rounded bg-black/60 text-gray-300 opacity-0 group-hover/drag:opacity-100 transition-opacity pointer-events-none">
        <GripVertical size={14} />
      </div>
      <ModelCard model={model} backTo="/queue" onMutate={onMutate} />
    </div>
  );
}

export default function Queue() {
  const [queued, setQueued] = useState<Model[]>([]);
  const [printed, setPrinted] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

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
          Drag a card to set your print order. Favorites always stay on top.
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
                <SortableCard key={m.id} model={m} onMutate={load} />
              ))}
            </div>
          </SortableContext>
        </DndContext>
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

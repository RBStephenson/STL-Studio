import { useEffect, useState } from "react";
import { ChevronUp, ChevronDown, Trash2, Plus, GripVertical } from "lucide-react";
import {
  DndContext, PointerSensor, KeyboardSensor, useSensor, useSensors,
  closestCenter, DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext, useSortable, verticalListSortingStrategy,
  sortableKeyboardCoordinates, arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { ReactNode } from "react";
import {
  GuideTab,
  GuidePhase,
  GuideStep,
  GuideSwatch,
  GuideMixComponent,
  StepTechnique,
  TabInput,
} from "../../api/client";
import PaintPicker, { PickedPaint } from "./PaintPicker";

// --- Draft model (client-side `_key` for stable React keys) -----------------

const TECHNIQUES: StepTechnique[] = ["airbrush", "brush", "wash", "finish", "effects", "filter"];

let _seq = 0;
const nextKey = () => `k${++_seq}`;

// `name` preserves an unresolved (name-only) swatch from import (#477): no
// PaintPicker, just passed through on save so editing the guide can't drop it.
interface DraftSwatch { _key: string; paint: PickedPaint | null; name: string | null; value_pct: string; role_label: string; }
// A mix component (#504): one paint (or a preserved name-only component, #425)
// plus its `parts` share of the blend, e.g. Red + Orange (4:1).
interface DraftMixComp { _key: string; paint: PickedPaint | null; name: string | null; parts: string; }
interface DraftStep {
  _key: string; title: string; technique_tag: StepTechnique | ""; technique_label: string;
  body: string; value_intent: string; tip: string; warning: string; ratio_box: string;
  swatches: DraftSwatch[]; mix: DraftMixComp[];
}
interface DraftPhase { _key: string; label: string; steps: DraftStep[]; }
interface DraftTab { _key: string; name: string; dom_id: string; heading: string; intro: string; phases: DraftPhase[]; }

function toDraft(tabs: GuideTab[]): DraftTab[] {
  return tabs.map((t) => ({
    _key: nextKey(),
    name: t.name,
    dom_id: t.dom_id ?? "",
    heading: t.section?.heading ?? "",
    intro: t.section?.intro ?? "",
    phases: t.phases.map((p) => ({
      _key: nextKey(),
      label: p.label,
      steps: p.steps.map((s) => ({
        _key: nextKey(),
        title: s.title,
        technique_tag: (s.technique_tag as StepTechnique) ?? "",
        technique_label: s.technique_label ?? "",
        body: s.body ?? "",
        value_intent: s.value_intent ?? "",
        tip: s.tip ?? "",
        warning: s.warning ?? "",
        ratio_box: s.ratio_box ?? "",
        swatches: s.swatches.map((w) => ({
          _key: nextKey(),
          paint: w.paint && w.paint_id != null
            ? { id: w.paint_id, name: w.paint.name, code: w.paint.code, hex: w.paint.hex }
            : null,
          name: w.name ?? null,
          value_pct: w.value_pct == null ? "" : String(w.value_pct),
          role_label: w.role_label ?? "",
        })),
        mix: (s.mix_components ?? []).map((m) => ({
          _key: nextKey(),
          paint: m.paint && m.paint_id != null
            ? { id: m.paint_id, name: m.paint.name, code: m.paint.code, hex: m.paint.hex }
            : null,
          name: m.name ?? null,
          parts: String(m.parts),
        })),
      })),
    })),
  }));
}

const orNull = (s: string) => (s.trim() === "" ? null : s.trim());

function serialize(tabs: DraftTab[]): TabInput[] {
  return tabs.map((t, ti) => ({
    name: t.name.trim(),
    dom_id: orNull(t.dom_id),
    sort_order: ti,
    section: t.heading.trim() ? { heading: t.heading.trim(), intro: orNull(t.intro) } : null,
    phases: t.phases.map((p, pi) => ({
      label: p.label.trim(),
      sort_order: pi,
      steps: p.steps.map((s, si) => ({
        title: s.title.trim(),
        technique_tag: s.technique_tag === "" ? null : s.technique_tag,
        technique_label: orNull(s.technique_label),
        body: orNull(s.body),
        value_intent: orNull(s.value_intent),
        tip: orNull(s.tip),
        warning: orNull(s.warning),
        ratio_box: orNull(s.ratio_box),
        sort_order: si,
        swatches: s.swatches
          // Keep paint-backed swatches and preserved name-only ones (#477).
          .filter((w) => w.paint || (w.name && w.name.trim()))
          .map((w, wi) => ({
            paint_id: w.paint ? w.paint.id : null,
            name: w.paint ? null : w.name,
            value_pct: w.value_pct.trim() === "" ? null : Number(w.value_pct),
            role_label: orNull(w.role_label),
            sort_order: wi,
          })),
        // Mix components (#504): paint-backed or preserved name-only (#425),
        // each carrying its `parts` share (defaults to 1 when left blank).
        mix_components: s.mix
          .filter((m) => m.paint || (m.name && m.name.trim()))
          .map((m, mi) => ({
            paint_id: m.paint ? m.paint.id : null,
            name: m.paint ? null : m.name,
            parts: m.parts.trim() === "" ? 1 : Number(m.parts),
            sort_order: mi,
          })),
      })),
    })),
  }));
}

// Map the live draft to the read-shape GuideReader consumes, so the editor can
// render a faithful preview without a server round-trip (#488). The draft already
// carries each picked paint's name/code/hex (PickedPaint), so swatches resolve;
// `brand` isn't held on the draft, so it's left blank in the preview. Synthetic
// ids are render-local (stable React keys only). Mix components aren't authorable
// yet (#504), so each step previews with single-paint swatches and no mixes.
function draftToPreviewTabs(tabs: DraftTab[]): GuideTab[] {
  let id = 0;
  const nid = () => ++id;
  return tabs.map((t, ti): GuideTab => ({
    id: nid(),
    name: t.name,
    dom_id: orNull(t.dom_id),
    sort_order: ti,
    has_expert_subtab: false,
    section: t.heading.trim() ? { heading: t.heading.trim(), intro: orNull(t.intro) } : null,
    value_map: null,
    subtabs: [],
    callouts: [],
    raw_blocks: [],
    method_block: null,
    phases: t.phases.map((p, pi): GuidePhase => ({
      id: nid(),
      label: p.label,
      subtab_key: null,
      sort_order: pi,
      steps: p.steps.map((s, si): GuideStep => ({
        id: nid(),
        title: s.title,
        technique_tag: s.technique_tag === "" ? null : s.technique_tag,
        technique_label: orNull(s.technique_label),
        body: orNull(s.body),
        value_intent: orNull(s.value_intent),
        tip: orNull(s.tip),
        warning: orNull(s.warning),
        ratio_box: orNull(s.ratio_box),
        sort_order: si,
        swatches: s.swatches
          .filter((w) => w.paint || (w.name && w.name.trim()))
          .map((w, wi): GuideSwatch => ({
            id: nid(),
            paint_id: w.paint ? w.paint.id : null,
            name: w.paint ? null : w.name,
            value_pct: w.value_pct.trim() === "" ? null : Number(w.value_pct),
            role_label: orNull(w.role_label),
            sort_order: wi,
            paint: w.paint
              ? { name: w.paint.name, code: w.paint.code, brand: "", hex: w.paint.hex }
              : null,
          })),
        mix_components: s.mix
          .filter((m) => m.paint || (m.name && m.name.trim()))
          .map((m, mi): GuideMixComponent => ({
            id: nid(),
            paint_id: m.paint ? m.paint.id : null,
            name: m.paint ? null : m.name,
            parts: m.parts.trim() === "" ? 1 : Number(m.parts),
            sort_order: mi,
            paint: m.paint
              ? { name: m.paint.name, code: m.paint.code, brand: "", hex: m.paint.hex }
              : null,
          })),
      })),
    })),
  }));
}

/** Backend requires every tab a name and every step a title. */
function validate(tabs: DraftTab[]): string | null {
  for (const t of tabs) {
    if (t.name.trim() === "") return "Every tab needs a name.";
    for (const p of t.phases) {
      for (const s of p.steps) {
        if (s.title.trim() === "") return "Every step needs a title.";
      }
    }
  }
  return null;
}

// --- Small array helpers ----------------------------------------------------

function move<T>(arr: T[], i: number, dir: -1 | 1): T[] {
  const j = i + dir;
  if (j < 0 || j >= arr.length) return arr;
  const next = [...arr];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}
const removeAt = <T,>(arr: T[], i: number) => arr.filter((_, idx) => idx !== i);
const replaceAt = <T,>(arr: T[], i: number, v: T) => arr.map((x, idx) => (idx === i ? v : x));

const field = "w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none";
const labelCls = "block text-[11px] font-medium text-gray-500 mb-0.5";
const gripCls = "cursor-grab active:cursor-grabbing text-gray-600 hover:text-gray-400 touch-none flex-shrink-0 p-0.5";

interface RowControls { onUp: () => void; onDown: () => void; onRemove: () => void; removeLabel: string; }

function RowButtons({ onUp, onDown, onRemove, removeLabel }: RowControls) {
  return (
    <div className="flex items-center gap-1">
      <button type="button" aria-label="Move up" onClick={onUp} className="text-gray-500 hover:text-gray-200"><ChevronUp size={15} /></button>
      <button type="button" aria-label="Move down" onClick={onDown} className="text-gray-500 hover:text-gray-200"><ChevronDown size={15} /></button>
      <button type="button" aria-label={removeLabel} onClick={onRemove} className="text-gray-500 hover:text-rose-400"><Trash2 size={14} /></button>
    </div>
  );
}

// Sortable wrapper — applies dnd-kit transform/transition to the container and
// provides a grip-handle button to the child via render prop. Keep up/down
// RowButtons as the keyboard a11y path (#503).
function SortableItem({ id, children }: { id: string; children: (handle: ReactNode) => ReactNode }) {
  const { setNodeRef, transform, transition, isDragging, listeners, attributes } = useSortable({ id });
  const handle = (
    <button
      type="button"
      {...listeners}
      {...attributes}
      aria-label="Drag to reorder"
      className={gripCls}
    >
      <GripVertical size={14} />
    </button>
  );
  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
      }}
    >
      {children(handle)}
    </div>
  );
}

// --- Swatch / Step / Phase / Tab editors (module scope, not nested) ---------

function SwatchRow({ value, onChange, dragHandle, ...ctl }: { value: DraftSwatch; onChange: (v: DraftSwatch) => void; dragHandle?: ReactNode } & RowControls) {
  // A name-only swatch (unresolved import, #477) has no shelf paint to pick —
  // show its name read-only so editing preserves rather than drops it.
  const nameOnly = !value.paint && !!value.name;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {dragHandle}
      {nameOnly ? (
        <span
          className="px-2 py-1 text-xs rounded bg-gray-800 border border-gray-700 text-gray-300"
          title="Unresolved paint — preserved by name"
        >
          {value.name} <span className="text-gray-500">(unresolved)</span>
        </span>
      ) : (
        <PaintPicker value={value.paint} onChange={(p) => onChange({ ...value, paint: p })} />
      )}
      <input
        aria-label="Value %" type="number" min={0} max={100} placeholder="val%"
        className="w-16 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 focus:border-indigo-600 focus:outline-none"
        value={value.value_pct} onChange={(e) => onChange({ ...value, value_pct: e.target.value })}
      />
      <input
        aria-label="Role label" placeholder="role (e.g. base, highlight)"
        className="flex-1 min-w-[8rem] bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 focus:border-indigo-600 focus:outline-none"
        value={value.role_label} onChange={(e) => onChange({ ...value, role_label: e.target.value })}
      />
      <RowButtons {...ctl} />
    </div>
  );
}

// One component of a mix swatch (#504): a paint (or preserved name-only) plus
// its `parts`. No drag/reorder — order is set by add order and the up/down arrows.
function MixCompRow({ value, onChange, onRemove }: { value: DraftMixComp; onChange: (v: DraftMixComp) => void; onRemove: () => void }) {
  const nameOnly = !value.paint && !!value.name;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {nameOnly ? (
        <span
          className="px-2 py-1 text-xs rounded bg-gray-800 border border-gray-700 text-gray-300"
          title="Unresolved paint — preserved by name"
        >
          {value.name} <span className="text-gray-500">(unresolved)</span>
        </span>
      ) : (
        <PaintPicker value={value.paint} onChange={(p) => onChange({ ...value, paint: p })} />
      )}
      <input
        aria-label="Parts" type="number" min={1} step="any" placeholder="parts"
        className="w-16 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 focus:border-indigo-600 focus:outline-none"
        value={value.parts} onChange={(e) => onChange({ ...value, parts: e.target.value })}
      />
      <button type="button" aria-label="Remove mix component" onClick={onRemove} className="text-gray-500 hover:text-rose-400"><Trash2 size={14} /></button>
    </div>
  );
}

// Optional mix section on a step (#504). Components blend in `parts` ratio,
// e.g. Red(4) + Orange(1) → "4:1". The reader renders them as one blended chip.
function MixEditor({ value, onChange }: { value: DraftMixComp[]; onChange: (v: DraftMixComp[]) => void }) {
  const ratio = value
    .filter((m) => m.paint || (m.name && m.name.trim()))
    .map((m) => (m.parts.trim() === "" ? "1" : m.parts.trim()))
    .join(":");
  return (
    <div className="space-y-1.5">
      <label className={labelCls}>
        Mix {value.length >= 2 && ratio && <span className="text-gray-600">(ratio {ratio})</span>}
      </label>
      {value.map((m, i) => (
        <MixCompRow
          key={m._key}
          value={m}
          onChange={(v) => onChange(replaceAt(value, i, v))}
          onRemove={() => onChange(removeAt(value, i))}
        />
      ))}
      <button
        type="button"
        onClick={() => onChange([...value, { _key: nextKey(), paint: null, name: null, parts: "1" }])}
        className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300"
      >
        <Plus size={12} /> Add mix component
      </button>
    </div>
  );
}

function StepEditor({ value, onChange, anchorId, dragHandle, ...ctl }: { value: DraftStep; onChange: (v: DraftStep) => void; anchorId: string; dragHandle?: ReactNode } & RowControls) {
  const set = (patch: Partial<DraftStep>) => onChange({ ...value, ...patch });

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const onSwatchDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIdx = value.swatches.findIndex((w) => w._key === String(active.id));
    const newIdx = value.swatches.findIndex((w) => w._key === String(over.id));
    if (oldIdx !== -1 && newIdx !== -1) set({ swatches: arrayMove(value.swatches, oldIdx, newIdx) });
  };

  return (
    // `id` is the jump-to-node target for validation flags (#489).
    <div id={anchorId} className="border border-gray-800 rounded p-3 bg-gray-950/40 space-y-2 scroll-mt-6">
      <div className="flex items-start gap-2">
        {dragHandle}
        <input aria-label="Step title" placeholder="Step title *" className={field} value={value.title} onChange={(e) => set({ title: e.target.value })} />
        <RowButtons {...ctl} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div>
          <label className={labelCls}>Technique</label>
          <select className={field} value={value.technique_tag} onChange={(e) => set({ technique_tag: e.target.value as StepTechnique | "" })}>
            <option value="">—</option>
            {TECHNIQUES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className={labelCls}>Technique label</label>
          <input className={field} value={value.technique_label} onChange={(e) => set({ technique_label: e.target.value })} />
        </div>
      </div>
      <div>
        <label className={labelCls}>Body</label>
        <textarea rows={2} className={field} value={value.body} onChange={(e) => set({ body: e.target.value })} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div><label className={labelCls}>Value intent</label><input className={field} value={value.value_intent} onChange={(e) => set({ value_intent: e.target.value })} /></div>
        <div><label className={labelCls}>Ratio box</label><input className={field} value={value.ratio_box} onChange={(e) => set({ ratio_box: e.target.value })} /></div>
        <div><label className={labelCls}>Tip</label><input className={field} value={value.tip} onChange={(e) => set({ tip: e.target.value })} /></div>
        <div><label className={labelCls}>Warning</label><input className={field} value={value.warning} onChange={(e) => set({ warning: e.target.value })} /></div>
      </div>
      <div className="space-y-1.5">
        <label className={labelCls}>Swatches</label>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onSwatchDragEnd}>
          <SortableContext items={value.swatches.map((w) => w._key)} strategy={verticalListSortingStrategy}>
            {value.swatches.map((w, i) => (
              <SortableItem key={w._key} id={w._key}>
                {(handle) => (
                  <SwatchRow
                    value={w}
                    dragHandle={handle}
                    onChange={(v) => set({ swatches: replaceAt(value.swatches, i, v) })}
                    onUp={() => set({ swatches: move(value.swatches, i, -1) })}
                    onDown={() => set({ swatches: move(value.swatches, i, 1) })}
                    onRemove={() => set({ swatches: removeAt(value.swatches, i) })}
                    removeLabel="Remove swatch"
                  />
                )}
              </SortableItem>
            ))}
          </SortableContext>
        </DndContext>
        <button type="button" onClick={() => set({ swatches: [...value.swatches, { _key: nextKey(), paint: null, name: null, value_pct: "", role_label: "" }] })}
          className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300">
          <Plus size={12} /> Add swatch
        </button>
      </div>
      <MixEditor value={value.mix} onChange={(mix) => set({ mix })} />
    </div>
  );
}

function PhaseEditor({ value, onChange, tabIndex, phaseIndex, dragHandle, ...ctl }: { value: DraftPhase; onChange: (v: DraftPhase) => void; tabIndex: number; phaseIndex: number; dragHandle?: ReactNode } & RowControls) {
  const set = (patch: Partial<DraftPhase>) => onChange({ ...value, ...patch });

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const onStepDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIdx = value.steps.findIndex((s) => s._key === String(active.id));
    const newIdx = value.steps.findIndex((s) => s._key === String(over.id));
    if (oldIdx !== -1 && newIdx !== -1) set({ steps: arrayMove(value.steps, oldIdx, newIdx) });
  };

  return (
    <div className="border border-gray-800 rounded p-3 bg-gray-900/40 space-y-2">
      <div className="flex items-center gap-2">
        {dragHandle}
        <input aria-label="Phase label" placeholder="Phase label (optional)" className={field} value={value.label} onChange={(e) => set({ label: e.target.value })} />
        <RowButtons {...ctl} />
      </div>
      <div className="space-y-2 pl-2 border-l border-gray-800">
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onStepDragEnd}>
          <SortableContext items={value.steps.map((s) => s._key)} strategy={verticalListSortingStrategy}>
            {value.steps.map((s, i) => (
              <SortableItem key={s._key} id={s._key}>
                {(handle) => (
                  <StepEditor
                    value={s}
                    dragHandle={handle}
                    anchorId={`guide-step-${tabIndex}-${phaseIndex}-${i}`}
                    onChange={(v) => set({ steps: replaceAt(value.steps, i, v) })}
                    onUp={() => set({ steps: move(value.steps, i, -1) })}
                    onDown={() => set({ steps: move(value.steps, i, 1) })}
                    onRemove={() => set({ steps: removeAt(value.steps, i) })}
                    removeLabel="Remove step"
                  />
                )}
              </SortableItem>
            ))}
          </SortableContext>
        </DndContext>
        <button type="button" onClick={() => set({ steps: [...value.steps, { _key: nextKey(), title: "", technique_tag: "", technique_label: "", body: "", value_intent: "", tip: "", warning: "", ratio_box: "", swatches: [], mix: [] }] })}
          className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300">
          <Plus size={12} /> Add step
        </button>
      </div>
    </div>
  );
}

function TabEditor({ value, onChange, tabIndex, dragHandle, ...ctl }: { value: DraftTab; onChange: (v: DraftTab) => void; tabIndex: number; dragHandle?: ReactNode } & RowControls) {
  const set = (patch: Partial<DraftTab>) => onChange({ ...value, ...patch });

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const onPhaseDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIdx = value.phases.findIndex((p) => p._key === String(active.id));
    const newIdx = value.phases.findIndex((p) => p._key === String(over.id));
    if (oldIdx !== -1 && newIdx !== -1) set({ phases: arrayMove(value.phases, oldIdx, newIdx) });
  };

  return (
    <div className="border border-gray-700 rounded-lg p-3 bg-gray-900 space-y-3">
      <div className="flex items-center gap-2">
        {dragHandle}
        <input aria-label="Tab name" placeholder="Tab name *" className={`${field} font-medium`} value={value.name} onChange={(e) => set({ name: e.target.value })} />
        <RowButtons {...ctl} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div><label className={labelCls}>Section heading</label><input className={field} value={value.heading} onChange={(e) => set({ heading: e.target.value })} /></div>
        <div><label className={labelCls}>Section intro</label><input className={field} value={value.intro} onChange={(e) => set({ intro: e.target.value })} /></div>
      </div>
      <div className="space-y-2 pl-2 border-l border-gray-700">
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onPhaseDragEnd}>
          <SortableContext items={value.phases.map((p) => p._key)} strategy={verticalListSortingStrategy}>
            {value.phases.map((p, i) => (
              <SortableItem key={p._key} id={p._key}>
                {(handle) => (
                  <PhaseEditor
                    value={p}
                    dragHandle={handle}
                    tabIndex={tabIndex} phaseIndex={i}
                    onChange={(v) => set({ phases: replaceAt(value.phases, i, v) })}
                    onUp={() => set({ phases: move(value.phases, i, -1) })}
                    onDown={() => set({ phases: move(value.phases, i, 1) })}
                    onRemove={() => set({ phases: removeAt(value.phases, i) })}
                    removeLabel="Remove phase"
                  />
                )}
              </SortableItem>
            ))}
          </SortableContext>
        </DndContext>
        <button type="button" onClick={() => set({ phases: [...value.phases, { _key: nextKey(), label: "", steps: [] }] })}
          className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300">
          <Plus size={12} /> Add phase
        </button>
      </div>
    </div>
  );
}

// --- Top-level editor -------------------------------------------------------

interface Props {
  initialTabs: GuideTab[];
  busy?: boolean;
  error?: string | null;
  onSave: (tabs: TabInput[]) => void;
  onCancel: () => void;
  // Live draft → read-shape, emitted on every edit so a parent can render a
  // preview (#488). Pass a stable callback (e.g. a setState setter).
  onPreviewChange?: (tabs: GuideTab[]) => void;
}

export default function GuideSpineEditor({ initialTabs, busy, error, onSave, onCancel, onPreviewChange }: Props) {
  const [tabs, setTabs] = useState<DraftTab[]>(() => toDraft(initialTabs));
  const [localError, setLocalError] = useState<string | null>(null);

  // Push the live preview projection whenever the draft changes (and on mount).
  useEffect(() => {
    onPreviewChange?.(draftToPreviewTabs(tabs));
    // onPreviewChange is expected to be a stable setter; tracking `tabs` alone
    // keeps this from re-firing on unrelated parent re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabs]);

  const save = () => {
    const err = validate(tabs);
    if (err) { setLocalError(err); return; }
    setLocalError(null);
    onSave(serialize(tabs));
  };

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const onTabDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setTabs((cur) => {
      const oldIdx = cur.findIndex((t) => t._key === String(active.id));
      const newIdx = cur.findIndex((t) => t._key === String(over.id));
      if (oldIdx === -1 || newIdx === -1) return cur;
      return arrayMove(cur, oldIdx, newIdx);
    });
  };

  const shown = localError || error;

  return (
    <div className="space-y-4">
      {shown && (
        <p role="alert" className="text-sm text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded px-3 py-2">{shown}</p>
      )}

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onTabDragEnd}>
        <SortableContext items={tabs.map((t) => t._key)} strategy={verticalListSortingStrategy}>
          {tabs.map((t, i) => (
            <SortableItem key={t._key} id={t._key}>
              {(handle) => (
                <TabEditor
                  value={t} tabIndex={i}
                  dragHandle={handle}
                  onChange={(v) => setTabs((cur) => replaceAt(cur, i, v))}
                  onUp={() => setTabs((cur) => move(cur, i, -1))}
                  onDown={() => setTabs((cur) => move(cur, i, 1))}
                  onRemove={() => setTabs((cur) => removeAt(cur, i))}
                  removeLabel="Remove tab"
                />
              )}
            </SortableItem>
          ))}
        </SortableContext>
      </DndContext>

      <button
        type="button"
        onClick={() => setTabs((cur) => [...cur, { _key: nextKey(), name: "", dom_id: "", heading: "", intro: "", phases: [] }])}
        className="inline-flex items-center gap-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm px-3 py-1.5 rounded transition-colors"
      >
        <Plus size={15} /> Add tab
      </button>

      <div className="flex items-center gap-2 pt-2">
        <button type="button" onClick={save} disabled={busy}
          className="inline-flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm px-4 py-2 rounded transition-colors disabled:opacity-50">
          Save content
        </button>
        <button type="button" onClick={onCancel} disabled={busy} className="text-sm text-gray-400 hover:text-gray-200 px-3 py-2">Cancel</button>
      </div>
    </div>
  );
}

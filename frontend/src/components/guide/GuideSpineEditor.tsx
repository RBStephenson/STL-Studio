import { useState } from "react";
import { ChevronUp, ChevronDown, Trash2, Plus } from "lucide-react";
import {
  GuideTab,
  StepTechnique,
  TabInput,
} from "../../api/client";
import PaintPicker, { PickedPaint } from "./PaintPicker";

// --- Draft model (client-side `_key` for stable React keys) -----------------

const TECHNIQUES: StepTechnique[] = ["airbrush", "brush", "wash", "finish", "effects", "filter"];

let _seq = 0;
const nextKey = () => `k${++_seq}`;

interface DraftSwatch { _key: string; paint: PickedPaint | null; value_pct: string; role_label: string; }
interface DraftStep {
  _key: string; title: string; technique_tag: StepTechnique | ""; technique_label: string;
  body: string; value_intent: string; tip: string; warning: string; ratio_box: string;
  swatches: DraftSwatch[];
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
          paint: w.paint
            ? { id: w.paint_id, name: w.paint.name, code: w.paint.code, hex: w.paint.hex }
            : null,
          value_pct: w.value_pct == null ? "" : String(w.value_pct),
          role_label: w.role_label ?? "",
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
          .filter((w) => w.paint)
          .map((w, wi) => ({
            paint_id: w.paint!.id,
            value_pct: w.value_pct.trim() === "" ? null : Number(w.value_pct),
            role_label: orNull(w.role_label),
            sort_order: wi,
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

// --- Swatch / Step / Phase / Tab editors (module scope, not nested) ---------

function SwatchRow({ value, onChange, ...ctl }: { value: DraftSwatch; onChange: (v: DraftSwatch) => void } & RowControls) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <PaintPicker value={value.paint} onChange={(p) => onChange({ ...value, paint: p })} />
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

function StepEditor({ value, onChange, ...ctl }: { value: DraftStep; onChange: (v: DraftStep) => void } & RowControls) {
  const set = (patch: Partial<DraftStep>) => onChange({ ...value, ...patch });
  return (
    <div className="border border-gray-800 rounded p-3 bg-gray-950/40 space-y-2">
      <div className="flex items-start gap-2">
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
        {value.swatches.map((w, i) => (
          <SwatchRow
            key={w._key} value={w}
            onChange={(v) => set({ swatches: replaceAt(value.swatches, i, v) })}
            onUp={() => set({ swatches: move(value.swatches, i, -1) })}
            onDown={() => set({ swatches: move(value.swatches, i, 1) })}
            onRemove={() => set({ swatches: removeAt(value.swatches, i) })}
            removeLabel="Remove swatch"
          />
        ))}
        <button type="button" onClick={() => set({ swatches: [...value.swatches, { _key: nextKey(), paint: null, value_pct: "", role_label: "" }] })}
          className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300">
          <Plus size={12} /> Add swatch
        </button>
      </div>
    </div>
  );
}

function PhaseEditor({ value, onChange, ...ctl }: { value: DraftPhase; onChange: (v: DraftPhase) => void } & RowControls) {
  const set = (patch: Partial<DraftPhase>) => onChange({ ...value, ...patch });
  return (
    <div className="border border-gray-800 rounded p-3 bg-gray-900/40 space-y-2">
      <div className="flex items-center gap-2">
        <input aria-label="Phase label" placeholder="Phase label (optional)" className={field} value={value.label} onChange={(e) => set({ label: e.target.value })} />
        <RowButtons {...ctl} />
      </div>
      <div className="space-y-2 pl-2 border-l border-gray-800">
        {value.steps.map((s, i) => (
          <StepEditor
            key={s._key} value={s}
            onChange={(v) => set({ steps: replaceAt(value.steps, i, v) })}
            onUp={() => set({ steps: move(value.steps, i, -1) })}
            onDown={() => set({ steps: move(value.steps, i, 1) })}
            onRemove={() => set({ steps: removeAt(value.steps, i) })}
            removeLabel="Remove step"
          />
        ))}
        <button type="button" onClick={() => set({ steps: [...value.steps, { _key: nextKey(), title: "", technique_tag: "", technique_label: "", body: "", value_intent: "", tip: "", warning: "", ratio_box: "", swatches: [] }] })}
          className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300">
          <Plus size={12} /> Add step
        </button>
      </div>
    </div>
  );
}

function TabEditor({ value, onChange, ...ctl }: { value: DraftTab; onChange: (v: DraftTab) => void } & RowControls) {
  const set = (patch: Partial<DraftTab>) => onChange({ ...value, ...patch });
  return (
    <div className="border border-gray-700 rounded-lg p-3 bg-gray-900 space-y-3">
      <div className="flex items-center gap-2">
        <input aria-label="Tab name" placeholder="Tab name *" className={`${field} font-medium`} value={value.name} onChange={(e) => set({ name: e.target.value })} />
        <RowButtons {...ctl} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div><label className={labelCls}>Section heading</label><input className={field} value={value.heading} onChange={(e) => set({ heading: e.target.value })} /></div>
        <div><label className={labelCls}>Section intro</label><input className={field} value={value.intro} onChange={(e) => set({ intro: e.target.value })} /></div>
      </div>
      <div className="space-y-2 pl-2 border-l border-gray-700">
        {value.phases.map((p, i) => (
          <PhaseEditor
            key={p._key} value={p}
            onChange={(v) => set({ phases: replaceAt(value.phases, i, v) })}
            onUp={() => set({ phases: move(value.phases, i, -1) })}
            onDown={() => set({ phases: move(value.phases, i, 1) })}
            onRemove={() => set({ phases: removeAt(value.phases, i) })}
            removeLabel="Remove phase"
          />
        ))}
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
}

export default function GuideSpineEditor({ initialTabs, busy, error, onSave, onCancel }: Props) {
  const [tabs, setTabs] = useState<DraftTab[]>(() => toDraft(initialTabs));
  const [localError, setLocalError] = useState<string | null>(null);

  const save = () => {
    const err = validate(tabs);
    if (err) { setLocalError(err); return; }
    setLocalError(null);
    onSave(serialize(tabs));
  };

  const shown = localError || error;

  return (
    <div className="space-y-4">
      {shown && (
        <p role="alert" className="text-sm text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded px-3 py-2">{shown}</p>
      )}

      {tabs.map((t, i) => (
        <TabEditor
          key={t._key} value={t}
          onChange={(v) => setTabs((cur) => replaceAt(cur, i, v))}
          onUp={() => setTabs((cur) => move(cur, i, -1))}
          onDown={() => setTabs((cur) => move(cur, i, 1))}
          onRemove={() => setTabs((cur) => removeAt(cur, i))}
          removeLabel="Remove tab"
        />
      ))}

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

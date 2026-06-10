import { useState, useEffect, useCallback, useRef, FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Palette, Plus, Search, Pencil, Trash2, X } from "lucide-react";
import {
  api, Paint, PaintBrand, PaintCreate, PaintFinish, PAINT_FINISHES,
} from "../api/client";
import { useToast } from "../context/ToastContext";

const PAGE_SIZE = 48;

/** Small color swatch; gray slash placeholder when the paint has no hex. */
export function ColorChip({ hex, size = 20 }: { hex: string | null; size?: number }) {
  if (!hex) {
    return (
      <span
        data-testid="color-chip-empty"
        className="inline-block rounded border border-gray-700 bg-gray-800 relative overflow-hidden"
        style={{ width: size, height: size }}
        title="No swatch color"
      >
        <span className="absolute inset-0 bg-[linear-gradient(135deg,transparent_45%,#4b5563_45%,#4b5563_55%,transparent_55%)]" />
      </span>
    );
  }
  return (
    <span
      data-testid="color-chip"
      className="inline-block rounded border border-gray-600"
      style={{ width: size, height: size, backgroundColor: hex }}
      title={hex}
    />
  );
}

interface PaintFormState {
  paint_line_id: string;
  code: string;
  name: string;
  hex: string;
  finish: PaintFinish;
  owned: boolean;
  notes: string;
}

const EMPTY_FORM: PaintFormState = {
  paint_line_id: "", code: "", name: "", hex: "", finish: "matte", owned: true, notes: "",
};

function PaintForm({ brands, initial, onSubmit, onCancel, busy }: {
  brands: PaintBrand[];
  initial: PaintFormState;
  onSubmit: (form: PaintFormState) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const [form, setForm] = useState<PaintFormState>(initial);
  const set = (patch: Partial<PaintFormState>) => setForm((f) => ({ ...f, ...patch }));

  const lineOptions = brands.flatMap((b) =>
    b.lines.map((l) => ({ id: l.id, label: `${b.name} — ${l.name}` }))
  );

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit(form);
  };

  const inputCls = "bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-indigo-500";

  return (
    <form onSubmit={submit} className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-4 flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Line
        <select
          required
          aria-label="Paint line"
          value={form.paint_line_id}
          onChange={(e) => set({ paint_line_id: e.target.value })}
          className={inputCls}
        >
          <option value="">Select a line…</option>
          {lineOptions.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Code
        <input required value={form.code} onChange={(e) => set({ code: e.target.value })} placeholder="002" className={`${inputCls} w-24`} />
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Name
        <input required value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder="Coal Black" className={`${inputCls} w-48`} />
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Color
        <div className="flex items-center gap-1.5">
          <input
            type="color"
            value={/^#[0-9a-fA-F]{6}$/.test(form.hex) ? form.hex : "#808080"}
            onChange={(e) => set({ hex: e.target.value })}
            className="h-8 w-9 bg-gray-900 border border-gray-700 rounded cursor-pointer p-0.5"
            title="Pick swatch color"
          />
          <input value={form.hex} onChange={(e) => set({ hex: e.target.value })} placeholder="#2A2A2A" className={`${inputCls} w-24 font-mono`} />
        </div>
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Finish
        <select value={form.finish} onChange={(e) => set({ finish: e.target.value as PaintFinish })} className={inputCls}>
          {PAINT_FINISHES.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm text-gray-300 pb-1.5">
        <input type="checkbox" checked={form.owned} onChange={(e) => set({ owned: e.target.checked })} className="h-4 w-4 accent-indigo-500" />
        Owned
      </label>
      <div className="flex items-center gap-2 ml-auto">
        <button type="button" onClick={onCancel} className="text-sm text-gray-500 hover:text-gray-300 px-2 py-1.5">
          Cancel
        </button>
        <button
          type="submit"
          disabled={busy}
          className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm px-4 py-1.5 rounded transition-colors"
        >
          Save
        </button>
      </div>
    </form>
  );
}

export default function PaintShelfPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { toast } = useToast();

  // Filter state lives in the URL, mirroring the Library's conventions.
  const page = Number(searchParams.get("page") ?? 1);
  const q = searchParams.get("q") ?? "";
  const brandId = searchParams.get("brand_id") ?? "";
  const lineId = searchParams.get("line_id") ?? "";
  const finish = searchParams.get("finish") ?? "";
  const ownedParam = searchParams.get("owned") ?? ""; // "" | "1" | "0"

  const setParam = (key: string, value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value); else next.delete(key);
      if (key !== "page") next.delete("page");
      return next;
    });
  };

  const [paints, setPaints] = useState<Paint[]>([]);
  const [total, setTotal] = useState(0);
  const [brands, setBrands] = useState<PaintBrand[]>([]);
  const [loading, setLoading] = useState(false);
  const [formMode, setFormMode] = useState<"hidden" | "add" | number>("hidden"); // number = editing that paint id
  const [busy, setBusy] = useState(false);
  const fetchIdRef = useRef(0);

  const loadBrands = useCallback(() => {
    api.painting.brands.list().then(setBrands).catch(() => {});
  }, []);
  useEffect(loadBrands, [loadBrands]);

  const fetchPaints = useCallback(async () => {
    const fetchId = ++fetchIdRef.current;
    setLoading(true);
    try {
      const params: Record<string, string | number | boolean> = { page, page_size: PAGE_SIZE };
      if (q) params.q = q;
      if (brandId) params.brand_id = brandId;
      if (lineId) params.line_id = lineId;
      if (finish) params.finish = finish;
      if (ownedParam) params.owned = ownedParam === "1";
      const data = await api.painting.paints.list(params);
      if (fetchId !== fetchIdRef.current) return; // stale response
      setPaints(data.items);
      setTotal(data.total);
    } finally {
      if (fetchId === fetchIdRef.current) setLoading(false);
    }
  }, [page, q, brandId, lineId, finish, ownedParam]);
  useEffect(() => { fetchPaints(); }, [fetchPaints]);

  const lineById = new Map(
    brands.flatMap((b) => b.lines.map((l) => [l.id, { brand: b.name, line: l.name }] as const))
  );

  const submitForm = async (form: PaintFormState) => {
    const body: PaintCreate = {
      paint_line_id: Number(form.paint_line_id),
      code: form.code.trim(),
      name: form.name.trim(),
      hex: form.hex.trim() || null,
      finish: form.finish,
      owned: form.owned,
      notes: form.notes.trim() || null,
      source: "manual",
    };
    setBusy(true);
    try {
      if (formMode === "add") {
        await api.painting.paints.create(body);
        toast("Paint added to the shelf.", "success");
      } else if (typeof formMode === "number") {
        await api.painting.paints.update(formMode, body);
        toast("Paint updated.", "success");
      }
      setFormMode("hidden");
      fetchPaints();
    } catch (e: any) {
      toast(e?.message || "Could not save the paint.", "error");
    } finally {
      setBusy(false);
    }
  };

  const deletePaint = async (paint: Paint) => {
    if (!window.confirm(`Delete ${paint.name} (${paint.code})?`)) return;
    try {
      await api.painting.paints.delete(paint.id);
      toast("Paint deleted.", "success");
      fetchPaints();
    } catch (e: any) {
      toast(e?.message || "Could not delete the paint.", "error");
    }
  };

  const editingPaint = typeof formMode === "number" ? paints.find((p) => p.id === formMode) : undefined;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const selectCls = "bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-indigo-500";

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-1">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <Palette size={22} className="text-indigo-400" />
          Paint Shelf
        </h1>
        <button
          onClick={() => setFormMode(formMode === "add" ? "hidden" : "add")}
          className="flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm px-3 py-1.5 rounded transition-colors"
        >
          <Plus size={15} /> Add paint
        </button>
      </div>
      <p className="text-sm text-gray-500 mb-6">
        {total.toLocaleString()} paints — guides will only ever reference paints from your shelf.
      </p>

      {formMode === "add" && (
        <PaintForm brands={brands} initial={EMPTY_FORM} onSubmit={submitForm} onCancel={() => setFormMode("hidden")} busy={busy} />
      )}
      {editingPaint && (
        <PaintForm
          key={editingPaint.id}
          brands={brands}
          initial={{
            paint_line_id: String(editingPaint.paint_line_id),
            code: editingPaint.code,
            name: editingPaint.name,
            hex: editingPaint.hex ?? "",
            finish: editingPaint.finish as PaintFinish,
            owned: editingPaint.owned,
            notes: editingPaint.notes ?? "",
          }}
          onSubmit={submitForm}
          onCancel={() => setFormMode("hidden")}
          busy={busy}
        />
      )}

      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 mb-4">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-600" />
          <input
            value={q}
            onChange={(e) => setParam("q", e.target.value)}
            placeholder="Search name or code…"
            className="bg-gray-900 border border-gray-700 rounded pl-8 pr-3 py-1.5 text-sm text-white focus:outline-none focus:border-indigo-500 w-56"
          />
        </div>
        <select aria-label="Brand" value={brandId} onChange={(e) => setParam("brand_id", e.target.value)} className={selectCls}>
          <option value="">All brands</option>
          {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <select aria-label="Line" value={lineId} onChange={(e) => setParam("line_id", e.target.value)} className={selectCls}>
          <option value="">All lines</option>
          {brands.flatMap((b) => b.lines).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        <select aria-label="Finish" value={finish} onChange={(e) => setParam("finish", e.target.value)} className={selectCls}>
          <option value="">All finishes</option>
          {PAINT_FINISHES.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        <select aria-label="Owned" value={ownedParam} onChange={(e) => setParam("owned", e.target.value)} className={selectCls}>
          <option value="">Owned + wishlist</option>
          <option value="1">Owned</option>
          <option value="0">Not owned</option>
        </select>
        {(q || brandId || lineId || finish || ownedParam) && (
          <button
            onClick={() => setSearchParams(new URLSearchParams())}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 px-2"
          >
            <X size={12} /> Clear
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
              <th className="px-4 py-2.5 w-10"></th>
              <th className="px-2 py-2.5">Code</th>
              <th className="px-2 py-2.5">Name</th>
              <th className="px-2 py-2.5">Line</th>
              <th className="px-2 py-2.5">Finish</th>
              <th className="px-2 py-2.5">Owned</th>
              <th className="px-2 py-2.5 w-20"></th>
            </tr>
          </thead>
          <tbody>
            {paints.map((p) => {
              const lineInfo = lineById.get(p.paint_line_id);
              return (
                <tr key={p.id} className="border-b border-gray-850 last:border-0 hover:bg-gray-850/50 group">
                  <td className="px-4 py-2"><ColorChip hex={p.hex} /></td>
                  <td className="px-2 py-2 font-mono text-xs text-gray-400">{p.code}</td>
                  <td className="px-2 py-2 text-gray-100">{p.name}</td>
                  <td className="px-2 py-2 text-gray-500 text-xs">
                    {lineInfo ? `${lineInfo.brand} — ${lineInfo.line}` : "—"}
                  </td>
                  <td className="px-2 py-2">
                    <span className="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{p.finish}</span>
                  </td>
                  <td className="px-2 py-2 text-xs">{p.owned ? <span className="text-emerald-400">yes</span> : <span className="text-gray-600">no</span>}</td>
                  <td className="px-2 py-2">
                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => setFormMode(p.id)} title="Edit" className="p-1 rounded text-gray-400 hover:text-indigo-300 hover:bg-gray-800">
                        <Pencil size={13} />
                      </button>
                      <button onClick={() => deletePaint(p)} title="Delete" className="p-1 rounded text-gray-400 hover:text-red-300 hover:bg-gray-800">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {!loading && paints.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-sm text-gray-600">
                  {total === 0 && !q && !brandId && !lineId && !finish && !ownedParam
                    ? "Your shelf is empty — add a paint, or import your PaintRack CSV (coming next)."
                    : "No paints match the current filters."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-5 text-sm text-gray-400">
          <button
            onClick={() => setParam("page", String(page - 1))}
            disabled={page <= 1}
            className="px-3 py-1.5 rounded bg-gray-900 border border-gray-700 disabled:opacity-40 hover:border-gray-500 transition-colors"
          >
            Prev
          </button>
          <span>{page} / {totalPages}</span>
          <button
            onClick={() => setParam("page", String(page + 1))}
            disabled={page >= totalPages}
            className="px-3 py-1.5 rounded bg-gray-900 border border-gray-700 disabled:opacity-40 hover:border-gray-500 transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

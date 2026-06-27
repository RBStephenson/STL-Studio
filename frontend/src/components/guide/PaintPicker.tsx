import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { api, Paint } from "../../api/client";

export interface PickedPaint {
  id: number;
  name: string;
  code: string;
  hex: string | null;
}

interface Props {
  value: PickedPaint | null;
  onChange: (paint: PickedPaint | null) => void;
  defaultSearch?: string;
}

/**
 * Searchable paint-shelf picker. Stores a paint_id on the swatch; the spine
 * itself only references paints, so the chosen paint's name/code/hex is held in
 * the swatch row for display. Mix components ("A + B") are out of scope (#339).
 */
export default function PaintPicker({ value, onChange, defaultSearch }: Props) {
  const [open, setOpen] = useState(false);
  const [seeded, setSeeded] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Paint[]>([]);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // Seed search with defaultSearch on first open (unresolved name-only swatches).
  useEffect(() => {
    if (open && !seeded && defaultSearch) {
      setQ(defaultSearch);
      setSeeded(true);
    }
  }, [open, seeded, defaultSearch]);

  // Debounced search; only runs while the dropdown is open.
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      setLoading(true);
      api.painting.paints
        .list({ q, page_size: 20, owned: true })
        .then((d) => setResults(d.items))
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(t);
  }, [q, open]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const pick = (p: Paint) => {
    onChange({ id: p.id, name: p.name, code: p.code, hex: p.hex });
    setOpen(false);
    setQ("");
  };

  return (
    <div className="relative" ref={boxRef}>
      {value ? (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center gap-1.5 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 hover:border-indigo-600"
        >
          <span
            className="inline-block w-3 h-3 rounded-sm border border-gray-600"
            style={{ backgroundColor: value.hex ?? "transparent" }}
          />
          <span>{value.name}</span>
          <span className="text-gray-500">{value.code}</span>
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center gap-1.5 bg-gray-900 border border-dashed border-gray-700 rounded px-2 py-1 text-xs text-gray-400 hover:border-indigo-600"
        >
          <Search size={12} /> Choose paint
        </button>
      )}
      {value && (
        <button
          type="button"
          aria-label="Clear paint"
          onClick={() => onChange(null)}
          className="ml-1 text-gray-500 hover:text-rose-400 align-middle"
        >
          <X size={12} />
        </button>
      )}

      {open && (
        <div className="absolute z-20 mt-1 w-64 bg-gray-900 border border-gray-700 rounded shadow-lg p-2">
          <input
            autoFocus
            aria-label="Search paints"
            className="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 focus:border-indigo-600 focus:outline-none mb-2"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search your shelf…"
          />
          <ul className="max-h-56 overflow-y-auto">
            {loading && <li className="text-xs text-gray-500 px-1 py-1">Searching…</li>}
            {!loading && results.length === 0 && (
              <li className="text-xs text-gray-500 px-1 py-1">No matching paints.</li>
            )}
            {results.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => pick(p)}
                  className="w-full flex items-center gap-2 text-left px-1 py-1 rounded hover:bg-gray-800 text-xs text-gray-200"
                >
                  <span
                    className="inline-block w-3 h-3 rounded-sm border border-gray-600 shrink-0"
                    style={{ backgroundColor: p.hex ?? "transparent" }}
                  />
                  <span className="truncate">{p.name}</span>
                  <span className="text-gray-500 ml-auto shrink-0">{p.code}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

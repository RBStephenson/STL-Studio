import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { api, Model } from "../../api/client";

interface Props {
  value: Model | null;
  onChange: (model: Model | null) => void;
}

export default function ModelSearchPicker({ value, onChange }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Model[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const q = query.trim();
    if (q.length < 2) { setResults([]); setOpen(false); return; }
    timer.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await api.models.list({ q, page_size: 10 });
        setResults(data.items);
        setOpen(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [query]);

  if (value) {
    return (
      <div className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded px-3 py-2">
        <span className="flex-1 text-sm text-gray-100">{value.title || value.name}</span>
        {value.character && (
          <span className="text-xs text-gray-500">{value.character}</span>
        )}
        <button
          type="button"
          aria-label="Clear model link"
          onClick={() => onChange(null)}
          className="text-gray-500 hover:text-rose-400"
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
        <input
          type="text"
          aria-label="Search models"
          placeholder="Search by name or title…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full bg-gray-900 border border-gray-700 rounded pl-8 pr-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
        />
        {loading && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-500">…</span>
        )}
      </div>
      {open && results.length > 0 && (
        <ul
          role="listbox"
          className="absolute z-20 w-full mt-1 bg-gray-800 border border-gray-700 rounded shadow-lg max-h-56 overflow-y-auto"
        >
          {results.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                className="w-full text-left px-3 py-2 text-sm hover:bg-gray-700 text-gray-100"
                onClick={() => { onChange(m); setQuery(""); setOpen(false); }}
              >
                <span className="font-medium">{m.title || m.name}</span>
                {m.character && (
                  <span className="text-gray-400 ml-1.5 text-xs">— {m.character}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && results.length === 0 && !loading && (
        <div className="absolute z-20 w-full mt-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-500">
          No models found.
        </div>
      )}
    </div>
  );
}

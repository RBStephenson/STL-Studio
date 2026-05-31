import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Users, Zap, X, RefreshCw, Loader2 } from "lucide-react";
import { api, Creator } from "../api/client";
import StorefrontEnrich from "../components/StorefrontEnrich";

export default function Creators() {
  const [creators, setCreators] = useState<Creator[]>([]);
  const [enriching, setEnriching] = useState<Creator | null>(null);
  const [search, setSearch] = useState("");
  const [scanningId, setScanningId] = useState<number | null>(null);

  const loadCreators = () => api.models.creators().then(setCreators).catch(() => {});
  useEffect(() => { loadCreators(); }, []);

  const rescan = async (c: Creator) => {
    if (scanningId !== null) return;  // a scan is already running
    setScanningId(c.id);
    try {
      await api.scan.startCreator(c.id);
      // Poll until the scan finishes, then refresh the model counts.
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500));
        const s = await api.scan.status();
        if (!s.running) break;
      }
      await loadCreators();
    } catch {
      /* ignore — e.g. another scan started elsewhere */
    } finally {
      setScanningId(null);
    }
  };

  const filtered = search
    ? creators.filter((c) => c.name.toLowerCase().includes(search.toLowerCase()))
    : creators;

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Users size={20} className="text-indigo-400" />
          <h1 className="text-2xl font-bold text-gray-100">Creators</h1>
          <span className="text-sm text-gray-500 ml-1">({creators.length})</span>
        </div>
        <input
          type="text"
          placeholder="Search creators…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-48"
        />
      </div>

      {/* Storefront enrich panel */}
      {enriching && (
        <div className="mb-6">
          <StorefrontEnrich
            creatorId={enriching.id}
            creatorName={enriching.name}
            onDone={() => setEnriching(null)}
          />
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
        {filtered.map((c) => (
          <div
            key={c.id}
            className={`group bg-gray-900 border rounded-lg overflow-hidden flex flex-col transition-colors ${
              enriching?.id === c.id ? "border-indigo-500" : "border-gray-800 hover:border-indigo-500"
            }`}
          >
            <Link
              to={`/?creator_id=${c.id}`}
              className="flex-1 p-4 flex flex-col gap-1 hover:bg-gray-800/50 transition-colors"
              title={`Browse ${c.name}'s models`}
            >
              <span className="font-medium text-gray-100 truncate group-hover:text-indigo-300 transition-colors">
                {c.name}
              </span>
              <span className="text-xs text-gray-500">{c.model_count} models →</span>
            </Link>
            <div className="flex border-t border-gray-800 divide-x divide-gray-800">
              <button
                onClick={() => rescan(c)}
                disabled={scanningId !== null}
                title={scanningId !== null ? "A scan is already running" : `Rescan ${c.name}`}
                className="flex-1 flex items-center justify-center gap-1 text-xs text-gray-600 hover:text-emerald-400 transition-colors px-2 py-2 hover:bg-gray-800/30 disabled:opacity-40 disabled:hover:text-gray-600 disabled:hover:bg-transparent"
              >
                {scanningId === c.id
                  ? <><Loader2 size={11} className="animate-spin" /> Scanning…</>
                  : <><RefreshCw size={11} /> Rescan</>
                }
              </button>
              <button
                onClick={() => setEnriching(enriching?.id === c.id ? null : c)}
                className="flex-1 flex items-center justify-center gap-1 text-xs text-gray-600 hover:text-indigo-400 transition-colors px-2 py-2 hover:bg-gray-800/30"
              >
                {enriching?.id === c.id
                  ? <><X size={11} /> Close</>
                  : <><Zap size={11} /> Enrich</>
                }
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

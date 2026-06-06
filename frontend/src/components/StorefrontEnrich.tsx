import { useState } from "react";
import { Search, Check, X, ChevronDown, ChevronUp, Loader2, Zap } from "lucide-react";

interface Product {
  title: string;
  source_url: string;
  source_site: string;
  external_id: string | null;
  thumbnail_url: string | null;
}

interface MatchResult {
  local_model_id: number;
  local_name: string;
  local_folder: string;
  score: number;
  confidence: "high" | "medium" | "low";
  product: Product;
}

interface Props {
  creatorId: number;
  creatorName: string;
  onDone: () => void;
}

const CONFIDENCE_STYLES = {
  high:   "bg-emerald-900/60 text-emerald-400 border-emerald-800",
  medium: "bg-yellow-900/60 text-yellow-400 border-yellow-800",
  low:    "bg-gray-800 text-gray-500 border-gray-700",
};

interface MatchCardProps {
  m: MatchResult;
  selected: Set<number>;
  toggle: (id: number) => void;
}

function MatchCard({ m, selected, toggle }: MatchCardProps) {
  return (
    <div
      onClick={() => toggle(m.local_model_id)}
      className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
        selected.has(m.local_model_id)
          ? "border-indigo-500 bg-indigo-950/30"
          : "border-gray-800 bg-gray-900 hover:border-gray-600"
      }`}
    >
      {/* Checkbox */}
      <div className={`w-5 h-5 rounded border-2 shrink-0 flex items-center justify-center transition-colors ${
        selected.has(m.local_model_id) ? "bg-indigo-600 border-indigo-600" : "border-gray-600"
      }`}>
        {selected.has(m.local_model_id) && <Check size={12} />}
      </div>

      {/* Scraped thumbnail */}
      <div className="w-12 h-12 rounded bg-gray-800 overflow-hidden shrink-0">
        {m.product.thumbnail_url
          ? <img src={m.product.thumbnail_url} alt="" className="w-full h-full object-cover" />
          : <div className="w-full h-full bg-gray-800" />
        }
      </div>

      {/* Names */}
      <div className="flex-1 min-w-0">
        <p className="text-xs text-gray-500 truncate" title={m.local_folder}>
          Local: <span className="text-gray-300">{m.local_name}</span>
        </p>
        <p className="text-xs text-gray-500 truncate">
          Match: <span className="text-gray-300">{m.product.title}</span>
        </p>
      </div>

      {/* Score */}
      <div className={`text-xs px-2 py-0.5 rounded border shrink-0 ${CONFIDENCE_STYLES[m.confidence]}`}>
        {Math.round(m.score * 100)}%
      </div>
    </div>
  );
}

export default function StorefrontEnrich({ creatorId, creatorName, onDone }: Props) {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [matches, setMatches] = useState<MatchResult[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [showLow, setShowLow] = useState(false);

  const runMatch = async () => {
    if (!url.trim()) return;
    setLoading(true); setError(null); setMatches([]); setSelected(new Set()); setDone(false);
    try {
      const r = await fetch(
        `/api/enrich/storefront/match?url=${encodeURIComponent(url.trim())}&creator_id=${creatorId}`
      );
      if (!r.ok) {
        const e = await r.json();
        throw new Error(e.detail ?? "Match failed");
      }
      const data: MatchResult[] = await r.json();
      setMatches(data);
      // Auto-select high + medium confidence
      setSelected(new Set(
        data
          .filter((m) => m.confidence !== "low")
          .map((m) => m.local_model_id)
      ));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const selectAll = (confidence: "high" | "medium" | "low") =>
    setSelected((prev) => {
      const next = new Set(prev);
      matches.filter((m) => m.confidence === confidence).forEach((m) => next.add(m.local_model_id));
      return next;
    });

  const apply = async () => {
    setApplying(true);
    try {
      const items = matches
        .filter((m) => selected.has(m.local_model_id))
        .map((m) => ({
          model_id: m.local_model_id,
          source_url: m.product.source_url,
          source_site: m.product.source_site,
          external_id: m.product.external_id,
          thumbnail_url: m.product.thumbnail_url,
          title: m.product.title,
        }));

      const r = await fetch("/api/enrich/storefront/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      if (!r.ok) throw new Error("Apply failed");
      const result = await r.json();
      setDone(true);
      setTimeout(onDone, 1500);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setApplying(false);
    }
  };

  const high   = matches.filter((m) => m.confidence === "high");
  const medium = matches.filter((m) => m.confidence === "medium");
  const low    = matches.filter((m) => m.confidence === "low");

  return (
    <div className="flex flex-col gap-4 bg-gray-900 border border-gray-800 rounded-xl p-5">
      <div className="flex items-center gap-2">
        <Zap size={16} className="text-indigo-400" />
        <h3 className="font-semibold text-gray-200">Enrich from Storefront</h3>
      </div>
      <p className="text-xs text-gray-500">
        Paste {creatorName}'s profile URL from MyMiniFactory, Gumroad, or Cults3D.
        We'll match their products to your local models and pull thumbnails + metadata in bulk.
      </p>

      <div className="flex gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && runMatch()}
          placeholder="https://www.myminifactory.com/users/…"
          className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
        />
        <button
          onClick={runMatch}
          disabled={loading || !url.trim()}
          className="flex items-center gap-1.5 px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm transition-colors"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          Match
        </button>
      </div>

      {error && (
        <p className="text-sm text-red-400 bg-red-950/40 border border-red-800 rounded px-3 py-2">{error}</p>
      )}

      {done && (
        <p className="text-sm text-emerald-400 bg-emerald-950/40 border border-emerald-800 rounded px-3 py-2 flex items-center gap-2">
          <Check size={14} /> Applied! Models updated.
        </p>
      )}

      {matches.length > 0 && (
        <>
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>{matches.length} matches found · {selected.size} selected</span>
            <div className="flex gap-2">
              <button onClick={() => setSelected(new Set(matches.map((m) => m.local_model_id)))}
                className="hover:text-gray-300">Select all</button>
              <button onClick={() => setSelected(new Set())} className="hover:text-gray-300">None</button>
            </div>
          </div>

          <div className="flex flex-col gap-4 max-h-[60vh] overflow-y-auto pr-1">
            {high.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-medium text-emerald-400">High confidence ({high.length})</p>
                  <button onClick={() => selectAll("high")} className="text-xs text-gray-600 hover:text-gray-400">Select all</button>
                </div>
                <div className="flex flex-col gap-2">{high.map((m) => <MatchCard key={m.local_model_id} m={m} selected={selected} toggle={toggle} />)}</div>
              </div>
            )}
            {medium.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-medium text-yellow-400">Medium confidence ({medium.length})</p>
                  <button onClick={() => selectAll("medium")} className="text-xs text-gray-600 hover:text-gray-400">Select all</button>
                </div>
                <div className="flex flex-col gap-2">{medium.map((m) => <MatchCard key={m.local_model_id} m={m} selected={selected} toggle={toggle} />)}</div>
              </div>
            )}
            {low.length > 0 && (
              <div>
                <button
                  onClick={() => setShowLow(!showLow)}
                  className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 mb-2"
                >
                  {showLow ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  Low confidence ({low.length}) — review carefully
                </button>
                {showLow && (
                  <div className="flex flex-col gap-2">{low.map((m) => <MatchCard key={m.local_model_id} m={m} selected={selected} toggle={toggle} />)}</div>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-800">
            <span className="text-xs text-gray-600 mr-auto">{selected.size} models will be updated</span>
            <button onClick={onDone} className="px-4 py-2 rounded bg-gray-800 hover:bg-gray-700 text-sm text-gray-300">
              Cancel
            </button>
            <button
              onClick={apply}
              disabled={applying || selected.size === 0}
              className="flex items-center gap-1.5 px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm transition-colors"
            >
              {applying ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
              Apply {selected.size} matches
            </button>
          </div>
        </>
      )}
    </div>
  );
}

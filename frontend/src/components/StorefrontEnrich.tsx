import { useState } from "react";
import { Search, Check, ChevronDown, ChevronUp, Loader2, Zap } from "lucide-react";
import RefreshEnrich from "./RefreshEnrich";

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

interface ApplyResult {
  applied: number;
  enriched_deep: number;
  fallback_shallow: number;
}

// Deep fields previewed on demand from /scrape/fetch (a subset of ScrapePreview).
interface DeepDetail {
  description: string | null;
  tags: string[];
  category: string | null;
  license: string | null;
}

type DetailState = DeepDetail | "loading" | "error";

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
  expanded: boolean;
  onToggleExpand: () => void;
  detail: DetailState | undefined;
}

function MatchCard({ m, selected, toggle, expanded, onToggleExpand, detail }: MatchCardProps) {
  const isSelected = selected.has(m.local_model_id);
  return (
    <div
      className={`flex flex-col rounded-lg border overflow-hidden transition-colors ${
        isSelected ? "border-indigo-500 bg-indigo-950/30" : "border-gray-800 bg-gray-900 hover:border-gray-600"
      }`}
    >
      <div onClick={() => toggle(m.local_model_id)} className="cursor-pointer">
        {/* Scraped thumbnail with selection + score overlaid. */}
        <div className="relative aspect-square bg-gray-800">
          {m.product.thumbnail_url
            ? <img src={m.product.thumbnail_url} alt="" className="w-full h-full object-cover" />
            : <div className="w-full h-full flex items-center justify-center text-gray-700"><Zap size={16} /></div>
          }
          {/* Checkbox */}
          <div className={`absolute top-1 left-1 w-4 h-4 rounded border flex items-center justify-center transition-colors ${
            isSelected ? "bg-indigo-600 border-indigo-600" : "border-gray-400 bg-gray-900/70"
          }`}>
            {isSelected && <Check size={10} />}
          </div>
          {/* Score */}
          <div className={`absolute top-1 right-1 text-[10px] leading-none px-1 py-0.5 rounded border ${CONFIDENCE_STYLES[m.confidence]}`}>
            {Math.round(m.score * 100)}%
          </div>
        </div>

        {/* Names */}
        <div className="px-1.5 py-1">
          <p className="text-[11px] leading-tight text-gray-400 truncate" title={`Local: ${m.local_folder}`}>
            {m.local_name}
          </p>
          <p className="text-[10px] leading-tight text-gray-600 truncate" title={`Match: ${m.product.title}`}>
            {m.product.title}
          </p>
        </div>
      </div>

      {/* Expand toggle — preview the metadata this match would apply. */}
      <button
        type="button"
        aria-label={expanded ? "Hide details" : "Preview details"}
        aria-expanded={expanded}
        onClick={(e) => { e.stopPropagation(); onToggleExpand(); }}
        className="flex items-center justify-center px-1 py-0.5 text-gray-600 hover:text-gray-300 hover:bg-gray-800/40 border-t border-gray-800/70 transition-colors"
      >
        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-2 border-t border-gray-800/70 text-xs">
          {detail === undefined || detail === "loading" ? (
            <p className="text-gray-500 flex items-center gap-1.5">
              <Loader2 size={12} className="animate-spin" /> Loading details…
            </p>
          ) : detail === "error" ? (
            <p className="text-rose-400">Couldn't load details for this product.</p>
          ) : (
            <div className="flex flex-col gap-2 text-gray-400">
              {detail.description && (
                <p className="line-clamp-3 whitespace-pre-wrap">{detail.description}</p>
              )}
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {detail.category && <span>Category: <span className="text-gray-300">{detail.category}</span></span>}
                {detail.license && <span>License: <span className="text-gray-300">{detail.license}</span></span>}
              </div>
              {detail.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {detail.tags.map((t) => (
                    <span key={t} className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{t}</span>
                  ))}
                </div>
              )}
              {!detail.description && !detail.category && !detail.license && detail.tags.length === 0 && (
                <p className="text-gray-600">No extra metadata available for this product.</p>
              )}
            </div>
          )}
        </div>
      )}
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
  const [result, setResult] = useState<ApplyResult | null>(null);
  const [showLow, setShowLow] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  // Deep-detail cache keyed by product URL so variants sharing a listing fetch once.
  const [details, setDetails] = useState<Record<string, DetailState>>({});

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

  const fetchDetail = async (sourceUrl: string) => {
    if (details[sourceUrl]) return;  // cached (incl. an in-flight "loading")
    setDetails((prev) => ({ ...prev, [sourceUrl]: "loading" }));
    try {
      const r = await fetch(`/api/scrape/fetch?url=${encodeURIComponent(sourceUrl)}`);
      if (!r.ok) throw new Error("fetch failed");
      const d = await r.json();
      setDetails((prev) => ({
        ...prev,
        [sourceUrl]: {
          description: d.description ?? null,
          tags: d.tags ?? [],
          category: d.category ?? null,
          license: d.license ?? null,
        },
      }));
    } catch {
      setDetails((prev) => ({ ...prev, [sourceUrl]: "error" }));
    }
  };

  const toggleExpand = (m: MatchResult) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(m.local_model_id)) {
        next.delete(m.local_model_id);
      } else {
        next.add(m.local_model_id);
        fetchDetail(m.product.source_url);  // lazy; cached after first open
      }
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
      setResult(await r.json());
      setDone(true);
      // A shallow fallback is worth seeing, so linger longer when some occurred.
      setTimeout(onDone, 2500);
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
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Zap size={16} className="text-indigo-400" />
          <h3 className="font-semibold text-gray-200">Enrich from Storefront</h3>
        </div>
        {/* Re-enrich models already matched to a listing — no URL needed. */}
        <RefreshEnrich creatorId={creatorId} scopeLabel={creatorName} compact />
      </div>
      <p className="text-xs text-gray-500">
        Paste {creatorName}'s profile URL from MyMiniFactory, Gumroad, or Cults3D.
        We'll match their products to your local models and pull full metadata in bulk —
        descriptions, tags, category, license, and thumbnails — including across variant groups.
        Already matched some? Use <span className="text-gray-400">Refresh</span> to re-pull the
        latest listing data without re-matching.
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
          <Check size={14} />
          {result
            ? <span>
                Applied to {result.applied} model{result.applied === 1 ? "" : "s"} —{" "}
                {result.enriched_deep} fully enriched
                {result.fallback_shallow > 0 && (
                  <>, {result.fallback_shallow} basic <span className="text-emerald-600">(couldn't fetch full detail)</span></>
                )}.
              </span>
            : <span>Applied! Models updated.</span>}
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
                <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2 items-start">{high.map((m) => <MatchCard key={m.local_model_id} m={m} selected={selected} toggle={toggle} expanded={expanded.has(m.local_model_id)} onToggleExpand={() => toggleExpand(m)} detail={details[m.product.source_url]} />)}</div>
              </div>
            )}
            {medium.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-medium text-yellow-400">Medium confidence ({medium.length})</p>
                  <button onClick={() => selectAll("medium")} className="text-xs text-gray-600 hover:text-gray-400">Select all</button>
                </div>
                <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2 items-start">{medium.map((m) => <MatchCard key={m.local_model_id} m={m} selected={selected} toggle={toggle} expanded={expanded.has(m.local_model_id)} onToggleExpand={() => toggleExpand(m)} detail={details[m.product.source_url]} />)}</div>
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
                  <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2 items-start">{low.map((m) => <MatchCard key={m.local_model_id} m={m} selected={selected} toggle={toggle} expanded={expanded.has(m.local_model_id)} onToggleExpand={() => toggleExpand(m)} detail={details[m.product.source_url]} />)}</div>
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

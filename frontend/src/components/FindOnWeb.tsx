import { useState } from "react";
import { Search, Link2, X, Check, ExternalLink, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { errMsg } from "../utils/err";

interface ScrapePreview {
  title: string | null;
  description: string | null;
  source_url: string | null;
  source_site: string | null;
  external_id: string | null;
  creator_name: string | null;
  thumbnail_url: string | null;
  image_urls: string[];
  tags: string[];
  category: string | null;
  license: string | null;
  like_count: number | null;
  download_count: number | null;
}

interface SearchResult {
  title: string;
  source_url: string;
  source_site: string;
  creator_name: string | null;
  thumbnail_url: string | null;
  like_count: number | null;
}

interface Props {
  modelId: number;
  modelName: string;
  onApplied: () => void;
  onClose: () => void;
}

const SITES = [
  { id: "myminifactory",  label: "MyMiniFactory", searchable: true },
  { id: "gumroad",        label: "Gumroad",        searchable: true },
  { id: "cults3d",        label: "Cults3D",        searchable: true },
  { id: "loot-studios",   label: "Loot Studios",   searchable: false },
  { id: "anvilrage",      label: "Anvilrage",      searchable: false },
];

type Tab = "url" | "search";

export default function FindOnWeb({ modelId, modelName, onApplied, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("url");
  const [site, setSite] = useState("myminifactory");
  const [urlInput, setUrlInput] = useState("");
  const [searchQuery, setSearchQuery] = useState(modelName);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ScrapePreview | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [applying, setApplying] = useState(false);
  const [showFullDesc, setShowFullDesc] = useState(false);

  const fetchUrl = async () => {
    if (!urlInput.trim()) return;
    setLoading(true); setError(null); setPreview(null);
    try {
      const r = await fetch(`/api/scrape/fetch?url=${encodeURIComponent(urlInput.trim())}`);
      if (!r.ok) {
        const e = await r.json();
        throw new Error(e.detail ?? "Fetch failed");
      }
      setPreview(await r.json());
    } catch (e) {
      setError(errMsg(e) ?? null);
    } finally {
      setLoading(false);
    }
  };

  const doSearch = async () => {
    if (!searchQuery.trim()) return;
    setLoading(true); setError(null); setSearchResults([]); setPreview(null);
    try {
      const r = await fetch(`/api/scrape/search?site=${site}&q=${encodeURIComponent(searchQuery.trim())}`);
      if (!r.ok) throw new Error("Search failed");
      setSearchResults(await r.json());
    } catch (e) {
      setError(errMsg(e) ?? null);
    } finally {
      setLoading(false);
    }
  };

  const selectResult = async (result: SearchResult) => {
    setLoading(true); setError(null); setPreview(null);
    try {
      const r = await fetch(`/api/scrape/fetch?url=${encodeURIComponent(result.source_url)}`);
      if (!r.ok) throw new Error("Could not fetch details");
      setPreview(await r.json());
      setTab("url");
    } catch (e) {
      setError(errMsg(e) ?? null);
    } finally {
      setLoading(false);
    }
  };

  const apply = async () => {
    if (!preview) return;
    setApplying(true);
    try {
      const r = await fetch(`/api/scrape/apply/${modelId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(preview),
      });
      if (!r.ok) throw new Error("Apply failed");
      onApplied();
    } catch (e) {
      setError(errMsg(e) ?? null);
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h2 className="font-semibold text-gray-100 flex items-center gap-2">
            <Search size={16} className="text-indigo-400" />
            Find on Web
          </h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-800">
          {(["url", "search"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-5 py-2.5 text-sm flex items-center gap-1.5 transition-colors border-b-2 -mb-px ${
                tab === t
                  ? "border-indigo-500 text-indigo-400"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}
            >
              {t === "url" ? <><Link2 size={13} /> Paste URL</> : <><Search size={13} /> Search</>}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4">

          {/* URL tab */}
          {tab === "url" && (
            <div className="flex gap-2">
              <input
                type="url"
                placeholder="https://www.myminifactory.com/object/… or app.lootstudios.com/bundle/…"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && fetchUrl()}
                className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
              />
              <button
                onClick={fetchUrl}
                disabled={loading || !urlInput.trim()}
                className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm flex items-center gap-1.5 transition-colors"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                Fetch
              </button>
            </div>
          )}

          {/* Search tab */}
          {tab === "search" && (
            <>
              <div className="flex gap-2">
                <select
                  value={site}
                  onChange={(e) => setSite(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-2 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
                >
                  {SITES.map((s) => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
                {SITES.find((s) => s.id === site)?.searchable ? (
                  <>
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && doSearch()}
                      className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-indigo-500"
                    />
                    <button
                      onClick={doSearch}
                      disabled={loading || !searchQuery.trim()}
                      className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm flex items-center gap-1.5"
                    >
                      {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                      Search
                    </button>
                  </>
                ) : (
                  <p className="flex-1 text-sm text-gray-400 self-center px-1">
                    {SITES.find((s) => s.id === site)?.label} doesn't support search —
                    use the <button className="text-indigo-400 hover:text-indigo-300 underline" onClick={() => setTab("url")}>Paste URL</button> tab instead.
                  </p>
                )}
              </div>

              {searchResults.length > 0 && (
                <div className="flex flex-col gap-2">
                  {searchResults.map((r) => (
                    <button
                      key={r.source_url}
                      onClick={() => selectResult(r)}
                      className="flex items-center gap-3 p-2.5 rounded-lg bg-gray-800 hover:bg-gray-750 border border-gray-700 hover:border-indigo-500 text-left transition-colors"
                    >
                      {r.thumbnail_url && (
                        <img src={r.thumbnail_url} alt="" className="w-12 h-12 rounded object-cover shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-100 truncate">{r.title}</p>
                        {r.creator_name && <p className="text-xs text-gray-500">by {r.creator_name}</p>}
                      </div>
                      {r.like_count != null && (
                        <span className="text-xs text-gray-500 shrink-0">♥ {r.like_count}</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {error && (
            <p className="text-sm text-red-400 bg-red-950/40 border border-red-800 rounded px-3 py-2">{error}</p>
          )}

          {/* Preview */}
          {preview && (
            <div className="border border-gray-700 rounded-xl overflow-hidden">
              <div className="bg-gray-800/50 px-4 py-3 flex items-center justify-between">
                <span className="text-sm font-medium text-gray-300">Preview — confirm before saving</span>
                {preview.source_url && (
                  <a href={preview.source_url} target="_blank" rel="noopener noreferrer"
                    className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
                    <ExternalLink size={11} /> View source
                  </a>
                )}
              </div>
              <div className="p-4 flex gap-4">
                {preview.thumbnail_url && (
                  <img src={preview.thumbnail_url} alt="" className="w-24 h-24 rounded-lg object-cover shrink-0" />
                )}
                <div className="flex-1 min-w-0 flex flex-col gap-2">
                  <p className="font-semibold text-gray-100">{preview.title}</p>
                  {preview.creator_name && <p className="text-xs text-gray-400">by {preview.creator_name}</p>}
                  <div className="flex flex-wrap gap-1.5">
                    {preview.source_site && (
                      <span className="text-xs bg-indigo-900/60 text-indigo-300 px-2 py-0.5 rounded capitalize">
                        {preview.source_site}
                      </span>
                    )}
                    {preview.license && (
                      <span className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded">{preview.license}</span>
                    )}
                    {preview.tags.slice(0, 5).map((t) => (
                      <span key={t} className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded">{t}</span>
                    ))}
                  </div>
                  {preview.description && (
                    <div>
                      <p className={`text-xs text-gray-500 leading-relaxed ${showFullDesc ? "" : "line-clamp-3"}`}>
                        {preview.description}
                      </p>
                      {preview.description.length > 200 && (
                        <button
                          onClick={() => setShowFullDesc(!showFullDesc)}
                          className="text-xs text-gray-600 hover:text-gray-400 flex items-center gap-0.5 mt-1"
                        >
                          {showFullDesc ? <><ChevronUp size={11} /> less</> : <><ChevronDown size={11} /> more</>}
                        </button>
                      )}
                    </div>
                  )}
                  {preview.image_urls.length > 1 && (
                    <p className="text-xs text-gray-600">
                      {preview.image_urls.length} images found — added to this model's gallery on Apply
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-800">
          <button onClick={onClose} className="px-4 py-2 rounded bg-gray-800 hover:bg-gray-700 text-sm text-gray-300">
            Cancel
          </button>
          <button
            onClick={apply}
            disabled={!preview || applying}
            className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm flex items-center gap-1.5 transition-colors"
          >
            {applying
              ? <><Loader2 size={14} className="animate-spin" /> Saving…</>
              : <><Check size={14} /> Save to Model</>
            }
          </button>
        </div>
      </div>
    </div>
  );
}

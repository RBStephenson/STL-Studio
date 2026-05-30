import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, SlidersHorizontal, AlertCircle, Tag, X, Bookmark, BookmarkPlus } from "lucide-react";
import { api, Model, Creator, ModelStats } from "../api/client";
import ModelCard from "../components/ModelCard";
import ScanButton from "../components/ScanButton";
import BulkTagBar from "../components/BulkTagBar";

const SITES = ["thingiverse", "printables", "myminifactory", "cults3d", "gumroad", "thangs", "makerworld", "other"];
const PAGE_SIZE = 48;
const PRESETS_KEY = "stl_filter_presets";

interface Preset { name: string; qs: string; }

function loadPresets(): Preset[] {
  try { return JSON.parse(localStorage.getItem(PRESETS_KEY) ?? "[]"); } catch { return []; }
}
function savePresets(presets: Preset[]) {
  localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
}

// Compact tri-state toggle: "all" | "1" | "0"
function TriToggle({ label, value, onChange }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const opts: { val: string; label: string }[] = [
    { val: "", label: "All" },
    { val: "1", label: "Yes" },
    { val: "0", label: "No" },
  ];
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-gray-500">{label}</span>
      <div className="flex rounded overflow-hidden border border-gray-700">
        {opts.map((o) => (
          <button
            key={o.val}
            onClick={() => onChange(o.val)}
            className={`px-2 py-1 text-xs transition-colors ${
              value === o.val
                ? "bg-indigo-600 text-white"
                : "bg-gray-800 text-gray-400 hover:text-gray-200"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function PaginationBar({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (p: number) => void }) {
  const [draft, setDraft] = useState(String(page));

  useEffect(() => { setDraft(String(page)); }, [page]);

  const btnCls = "px-3 py-1.5 rounded bg-gray-900 border border-gray-700 text-sm disabled:opacity-40 hover:border-gray-500 transition-colors";

  function commit(raw: string) {
    const n = parseInt(raw, 10);
    if (!isNaN(n)) onPage(Math.min(totalPages, Math.max(1, n)));
  }

  return (
    <div className="flex items-center justify-center gap-2 mt-8">
      <button onClick={() => onPage(page - 1)} disabled={page === 1} className={btnCls}>Prev</button>
      <div className="flex items-center gap-1.5 text-sm text-gray-400">
        <input
          type="text"
          inputMode="numeric"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(e) => { if (e.key === "Enter") { commit(draft); (e.target as HTMLInputElement).blur(); } }}
          className="w-12 text-center rounded bg-gray-900 border border-gray-600 py-1 text-sm text-white focus:outline-none focus:border-indigo-500"
        />
        <span>/ {totalPages}</span>
      </div>
      <button onClick={() => onPage(page + 1)} disabled={page === totalPages} className={btnCls}>Next</button>
    </div>
  );
}

export default function Library() {
  const [searchParams, setSearchParams] = useSearchParams();

  // All filter state lives in the URL
  const page         = Number(searchParams.get("page") ?? 1);
  const search       = searchParams.get("q") ?? "";
  const creatorId    = searchParams.get("creator_id") ?? "";
  const site         = searchParams.get("source_site") ?? "";
  const activeTag    = searchParams.get("tag") ?? "";
  const needsReview  = searchParams.get("needs_review") === "1";
  const nsfwParam    = searchParams.get("nsfw") ?? "";        // "" | "1" | "0"
  const thumbParam   = searchParams.get("has_thumbnail") ?? ""; // "" | "1" | "0"

  const setParam = (key: string, value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value); else next.delete(key);
      if (key !== "page") next.delete("page");
      return next;
    });
  };
  const setPage = (p: number) => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      p > 1 ? next.set("page", String(p)) : next.delete("page");
      return next;
    });
  };

  const [models, setModels] = useState<Model[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<ModelStats | null>(null);
  const [creators, setCreators] = useState<Creator[]>([]);
  const [allTags, setAllTags] = useState<{ tag: string; count: number }[]>([]);
  const [tagSearch, setTagSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [showFilters, setShowFilters] = useState(
    !!(creatorId || site || activeTag || nsfwParam || thumbParam)
  );
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [presets, setPresets] = useState<Preset[]>(loadPresets);
  const [savingPreset, setSavingPreset] = useState(false);
  const [presetName, setPresetName] = useState("");
  const presetInputRef = useRef<HTMLInputElement>(null);

  const scrollRestoredRef = useRef(false);

  const fetchModels = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number | boolean> = { page, page_size: PAGE_SIZE, group_variants: true };
      if (search)      params.q             = search;
      if (creatorId)   params.creator_id    = creatorId;
      if (site)        params.source_site   = site;
      if (activeTag)   params.tag           = activeTag;
      if (needsReview) params.needs_review  = true;
      if (nsfwParam)   params.nsfw          = nsfwParam === "1";
      if (thumbParam)  params.has_thumbnail = thumbParam === "1";
      const data = await api.models.list(params);
      setModels(data.items);
      setTotal(data.total);
    } finally {
      setLoading(false);
    }
  }, [page, search, creatorId, site, activeTag, needsReview, nsfwParam, thumbParam]);

  useEffect(() => { fetchModels(); }, [fetchModels]);
  useEffect(() => { api.models.creators().then(setCreators).catch(() => {}); }, []);
  useEffect(() => { api.models.stats().then(setStats).catch(() => {}); }, []);
  useEffect(() => { api.models.tags().then(setAllTags).catch(() => {}); }, []);

  // Restore scroll position when navigating back from a model detail page
  useEffect(() => {
    if (loading || scrollRestoredRef.current) return;
    const saved = sessionStorage.getItem("library_scroll");
    if (saved) {
      window.scrollTo({ top: Number(saved), behavior: "instant" });
      sessionStorage.removeItem("library_scroll");
      scrollRestoredRef.current = true;
    }
  }, [loading]);

  useEffect(() => {
    if (savingPreset) presetInputRef.current?.focus();
  }, [savingPreset]);

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const hasFilters = !!(creatorId || site || activeTag || needsReview || nsfwParam || thumbParam);

  const visibleTags = allTags.filter(({ tag }) =>
    !tagSearch || tag.includes(tagSearch.toLowerCase())
  );

  // Current URL params as a preset-saveable string (excluding page)
  const currentQS = (() => {
    const p = new URLSearchParams(searchParams);
    p.delete("page");
    return p.toString();
  })();

  const applyPreset = (preset: Preset) => {
    const p = new URLSearchParams(preset.qs);
    p.delete("page");
    setSearchParams(p);
  };

  const deletePreset = (name: string) => {
    const next = presets.filter(p => p.name !== name);
    setPresets(next);
    savePresets(next);
  };

  const confirmSavePreset = () => {
    const name = presetName.trim();
    if (!name) return;
    const next = [...presets.filter(p => p.name !== name), { name, qs: currentQS }];
    setPresets(next);
    savePresets(next);
    setSavingPreset(false);
    setPresetName("");
  };

  const toggleSelect = useCallback((id: number) => {
    setSelection(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelection(new Set(models.map(m => m.id)));
  }, [models]);

  const clearSelection = useCallback(() => setSelection(new Set()), []);

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Library</h1>
          <div className="flex items-center gap-3 mt-0.5">
            <p className="text-sm text-gray-500">{total.toLocaleString()} models</p>
            {stats && stats.needs_review > 0 && (
              <button
                onClick={() => setParam("needs_review", needsReview ? "" : "1")}
                className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded transition-colors ${
                  needsReview
                    ? "bg-amber-500 text-amber-950 font-medium"
                    : "bg-amber-950/50 text-amber-400 hover:bg-amber-900/50"
                }`}
              >
                <AlertCircle size={11} />
                {stats.needs_review} need review
              </button>
            )}
          </div>
        </div>
        <ScanButton onScanComplete={fetchModels} />
      </div>

      {/* Search + filter bar */}
      <div className="flex gap-2 mb-4 flex-wrap">
        <div className="relative flex-1 min-w-48">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search models…"
            value={search}
            onChange={(e) => setParam("q", e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded pl-9 pr-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
          />
        </div>

        {/* Active filter chips */}
        {activeTag && (
          <div className="flex items-center gap-1.5 px-3 py-2 rounded bg-indigo-950 border border-indigo-700 text-indigo-300 text-sm">
            <Tag size={13} />
            <span>{activeTag}</span>
            <button onClick={() => setParam("tag", "")} className="text-indigo-500 hover:text-indigo-200 transition-colors ml-0.5">
              <X size={13} />
            </button>
          </div>
        )}
        {nsfwParam && (
          <div className="flex items-center gap-1.5 px-3 py-2 rounded bg-red-950 border border-red-800 text-red-300 text-sm">
            <span>NSFW: {nsfwParam === "1" ? "Yes" : "No"}</span>
            <button onClick={() => setParam("nsfw", "")} className="text-red-500 hover:text-red-200 transition-colors">
              <X size={13} />
            </button>
          </div>
        )}
        {thumbParam && (
          <div className="flex items-center gap-1.5 px-3 py-2 rounded bg-gray-800 border border-gray-700 text-gray-300 text-sm">
            <span>Image: {thumbParam === "1" ? "Yes" : "No"}</span>
            <button onClick={() => setParam("has_thumbnail", "")} className="text-gray-500 hover:text-gray-200 transition-colors">
              <X size={13} />
            </button>
          </div>
        )}

        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1.5 px-3 py-2 rounded border text-sm transition-colors ${
            showFilters || hasFilters
              ? "bg-indigo-600 border-indigo-500 text-white"
              : "bg-gray-900 border-gray-700 text-gray-400 hover:text-gray-100"
          }`}
        >
          <SlidersHorizontal size={14} />
          Filters {hasFilters && !showFilters && "•"}
        </button>
      </div>

      {showFilters && (
        <div className="flex flex-col gap-3 mb-4 p-3 bg-gray-900 rounded border border-gray-800">

          {/* Saved presets */}
          {(presets.length > 0 || hasFilters) && (
            <div className="flex flex-wrap items-center gap-2 pb-3 border-b border-gray-800">
              <Bookmark size={13} className="text-gray-500 shrink-0" />
              {presets.map((p) => (
                <button
                  key={p.name}
                  onClick={() => applyPreset(p)}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-gray-800 border border-gray-700 text-xs text-gray-300 hover:border-indigo-500 hover:text-indigo-300 transition-colors"
                >
                  {p.name}
                  <span
                    role="button"
                    onClick={(e) => { e.stopPropagation(); deletePreset(p.name); }}
                    className="text-gray-600 hover:text-red-400 transition-colors ml-0.5"
                  >
                    <X size={11} />
                  </span>
                </button>
              ))}
              {hasFilters && !savingPreset && (
                <button
                  onClick={() => setSavingPreset(true)}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-gray-800 border border-dashed border-gray-600 text-xs text-gray-500 hover:text-indigo-300 hover:border-indigo-600 transition-colors"
                >
                  <BookmarkPlus size={11} />
                  Save preset
                </button>
              )}
              {savingPreset && (
                <form
                  onSubmit={(e) => { e.preventDefault(); confirmSavePreset(); }}
                  className="flex items-center gap-1"
                >
                  <input
                    ref={presetInputRef}
                    type="text"
                    placeholder="Preset name…"
                    value={presetName}
                    onChange={(e) => setPresetName(e.target.value)}
                    className="bg-gray-800 border border-indigo-600 rounded px-2 py-0.5 text-xs text-gray-100 placeholder-gray-600 focus:outline-none w-32"
                  />
                  <button type="submit" className="text-xs text-indigo-400 hover:text-indigo-200 px-1">Save</button>
                  <button type="button" onClick={() => { setSavingPreset(false); setPresetName(""); }} className="text-xs text-gray-600 hover:text-gray-300">
                    <X size={12} />
                  </button>
                </form>
              )}
            </div>
          )}

          {/* Dropdowns row */}
          <div className="flex flex-wrap gap-3 items-center">
            <select
              value={creatorId}
              onChange={(e) => setParam("creator_id", e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Creators</option>
              {creators.map((c) => (
                <option key={c.id} value={c.id}>{c.name} ({c.model_count})</option>
              ))}
            </select>
            <select
              value={site}
              onChange={(e) => setParam("source_site", e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Sites</option>
              {SITES.map((s) => (
                <option key={s} value={s} className="capitalize">{s}</option>
              ))}
            </select>

            <TriToggle label="NSFW" value={nsfwParam} onChange={(v) => setParam("nsfw", v)} />
            <TriToggle label="Has image" value={thumbParam} onChange={(v) => setParam("has_thumbnail", v)} />

            <label className="flex items-center gap-1.5 text-sm text-gray-400 cursor-pointer">
              <input
                type="checkbox"
                checked={needsReview}
                onChange={(e) => setParam("needs_review", e.target.checked ? "1" : "")}
                className="accent-amber-400"
              />
              Needs review only
            </label>
            {hasFilters && (
              <button
                onClick={() => setSearchParams(search ? { q: search } : {})}
                className="text-xs text-gray-500 hover:text-gray-300 px-2 ml-auto"
              >
                Clear all
              </button>
            )}
          </div>

          {/* Tag picker */}
          {allTags.length > 0 && (
            <div className="border-t border-gray-800 pt-3">
              <div className="flex items-center gap-2 mb-2">
                <Tag size={13} className="text-gray-500" />
                <span className="text-xs text-gray-500 font-medium uppercase tracking-wide">Filter by tag</span>
                <div className="relative ml-auto">
                  <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input
                    type="text"
                    placeholder="Search tags…"
                    value={tagSearch}
                    onChange={(e) => setTagSearch(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded pl-6 pr-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-36"
                  />
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                {visibleTags.map(({ tag, count }) => {
                  const isActive = activeTag === tag;
                  return (
                    <button
                      key={tag}
                      onClick={() => setParam("tag", isActive ? "" : tag)}
                      className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs transition-colors ${
                        isActive
                          ? "bg-indigo-600 border border-indigo-500 text-white"
                          : "bg-gray-800 border border-gray-700 text-gray-300 hover:border-indigo-500 hover:text-indigo-300"
                      }`}
                    >
                      {tag}
                      <span className={isActive ? "text-indigo-300" : "text-gray-500"}>{count}</span>
                    </button>
                  );
                })}
                {visibleTags.length === 0 && (
                  <span className="text-xs text-gray-600">No tags match "{tagSearch}"</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Grid */}
      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {Array.from({ length: 24 }).map((_, i) => (
            <div key={i} className="aspect-square bg-gray-900 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : models.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-gray-600">
          <p className="text-lg">No models found</p>
          <p className="text-sm mt-1">Try scanning your library or adjusting filters</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {models.map((m) => (
            <ModelCard
              key={m.id}
              model={m}
              selected={selection.has(m.id)}
              onSelect={toggleSelect}
            />
          ))}
        </div>
      )}

      {selection.size > 0 && (
        <BulkTagBar
          selectedIds={Array.from(selection)}
          totalOnPage={models.length}
          onSelectAll={selectAll}
          onClear={clearSelection}
          onDone={fetchModels}
        />
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <PaginationBar page={page} totalPages={totalPages} onPage={setPage} />
      )}
    </div>
  );
}

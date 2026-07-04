// Library search + filter bar: search box, active-filter chips, the collapsible
// filter panel (saved presets, creator/site/support/slicer dropdowns, tri-state
// toggles, min-rating, needs-review, clear-all), and the tag picker. Extracted
// from Library.tsx (STUDIO-63 P4) — behavior-preserving; markup moved verbatim.
//
// URL-filter state comes from useLibraryFilters (passed as `filters`); preset
// state stays in the page shell and is passed in.

import { useState } from "react";
import { Search, SlidersHorizontal, Tag, X, Bookmark, BookmarkPlus } from "lucide-react";
import { FilterPreset } from "../../api/client";
import { nextTagParams } from "../../utils/tagFilter";
import type { LibraryFilters } from "../../hooks/useLibraryFilters";

const SITES = ["thingiverse", "printables", "myminifactory", "cults3d", "gumroad", "thangs", "makerworld", "other"];

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

interface FilterBarProps {
  filters: LibraryFilters;
  showFilters: boolean;
  setShowFilters: (v: boolean) => void;
  hasFilters: boolean;
  creators: { id: number; name: string; model_count: number }[];
  allTags: { tag: string; count: number }[];
  presets: FilterPreset[];
  applyPreset: (preset: FilterPreset) => void;
  deletePreset: (name: string) => void;
  savingPreset: boolean;
  setSavingPreset: (v: boolean) => void;
  presetName: string;
  setPresetName: (v: string) => void;
  presetInputRef: React.RefObject<HTMLInputElement | null>;
  confirmSavePreset: () => void;
}

export default function FilterBar({
  filters,
  showFilters,
  setShowFilters,
  hasFilters,
  creators,
  allTags,
  presets,
  applyPreset,
  deletePreset,
  savingPreset,
  setSavingPreset,
  presetName,
  setPresetName,
  presetInputRef,
  confirmSavePreset,
}: FilterBarProps) {
  const {
    searchInput, searchInputRef, onSearchChange, clearSearch,
    activeTag, excludeTag, nsfwParam, thumbParam, creatorId, excludeCreatorId,
    site, supportParam, slicerParam, minRating, needsReview,
    setParam, setParams, setSearchParams,
  } = filters;

  const [tagSearch, setTagSearch] = useState("");
  const visibleTags = allTags.filter(({ tag }) =>
    !tagSearch || tag.includes(tagSearch.toLowerCase())
  );

  return (
    <>
      {/* Search + filter bar */}
      <div className="flex gap-2 mb-4 flex-wrap">
        <div className="relative flex-1 min-w-48">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            ref={searchInputRef}
            type="text"
            placeholder="Search models…  (press / )"
            value={searchInput}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded pl-9 pr-9 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
          />
          {searchInput && (
            <button
              type="button"
              onClick={clearSearch}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-200 transition-colors"
            >
              <X size={16} />
            </button>
          )}
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
        {excludeTag && (
          <div className="flex items-center gap-1.5 px-3 py-2 rounded bg-rose-950 border border-rose-700 text-rose-300 text-sm">
            <Tag size={13} />
            <span>≠ {excludeTag}</span>
            <button onClick={() => setParam("exclude_tag", "")} className="text-rose-500 hover:text-rose-200 transition-colors ml-0.5">
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
              onChange={(e) => setParams({ creator_id: e.target.value, exclude_creator_id: "" })}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Creators</option>
              {creators.map((c) => (
                <option key={c.id} value={c.id}>{c.name} ({c.model_count})</option>
              ))}
            </select>
            <select
              value={excludeCreatorId}
              onChange={(e) => setParams({ exclude_creator_id: e.target.value, creator_id: "" })}
              title="Hide all models from one creator"
              className={`bg-gray-800 border rounded px-2 py-1.5 text-sm focus:outline-none focus:border-rose-500 ${
                excludeCreatorId ? "border-rose-700 text-rose-300" : "border-gray-700 text-gray-200"
              }`}
            >
              <option value="">Exclude creator…</option>
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

            <select
              value={supportParam}
              onChange={(e) => setParam("support_status", e.target.value)}
              title="Filter by print-support status"
              className={`bg-gray-800 border rounded px-2 py-1.5 text-sm focus:outline-none focus:border-indigo-500 ${
                supportParam ? "border-indigo-700 text-indigo-300" : "border-gray-700 text-gray-200"
              }`}
            >
              <option value="">All supports</option>
              <option value="unsupported">Unsupported</option>
              <option value="pre-supported">Pre-supported</option>
              <option value="supported">Supported</option>
            </select>
            <select
              value={slicerParam}
              onChange={(e) => setParam("slicer", e.target.value)}
              title="Filter by slicer project format"
              className={`bg-gray-800 border rounded px-2 py-1.5 text-sm focus:outline-none focus:border-indigo-500 ${
                slicerParam ? "border-indigo-700 text-indigo-300" : "border-gray-700 text-gray-200"
              }`}
            >
              <option value="">All slicers</option>
              <option value="lychee">Lychee</option>
              <option value="chitubox">Chitubox</option>
            </select>

            <TriToggle label="NSFW" value={nsfwParam} onChange={(v) => setParam("nsfw", v)} />
            <TriToggle label="Has image" value={thumbParam} onChange={(v) => setParam("has_thumbnail", v)} />

            <div className="flex items-center gap-1.5">
              <span className="text-xs text-gray-500">Min rating</span>
              <select
                value={minRating}
                onChange={(e) => setParam("min_rating", e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="">Any</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>{"★".repeat(n)}{n < 5 ? "+" : ""}</option>
                ))}
              </select>
            </div>

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
                onClick={() => setSearchParams(searchInput ? { q: searchInput } : {})}
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
                  // Three-state cycle: off → include (indigo) → exclude (rose) → off
                  const isInclude = activeTag === tag;
                  const isExclude = excludeTag === tag;
                  return (
                    <button
                      key={tag}
                      onClick={() => setParams(nextTagParams(tag, activeTag, excludeTag))}
                      title={isInclude ? "Click again to exclude this tag" : isExclude ? "Click to clear" : "Show only this tag"}
                      className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs transition-colors ${
                        isInclude
                          ? "bg-indigo-600 border border-indigo-500 text-white"
                          : isExclude
                          ? "bg-rose-700 border border-rose-600 text-white"
                          : "bg-gray-800 border border-gray-700 text-gray-300 hover:border-indigo-500 hover:text-indigo-300"
                      }`}
                    >
                      {isExclude && "≠ "}{tag}
                      <span className={isInclude ? "text-indigo-300" : isExclude ? "text-rose-300" : "text-gray-500"}>{count}</span>
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
    </>
  );
}

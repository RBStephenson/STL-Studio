// Library filter sidebar — replaces the old top FilterBar (STUDIO-128).
// Collapsible left rail (260px <-> 64px), collapsed state persisted to
// localStorage so it survives reloads/navigation, per design/README.md
// screen 1. Trimmed to the design's filter set (search, creator, site,
// support status, tag chips, quick-filter stat buttons) — the older
// exclude-creator/slicer/NSFW+image tri-toggles/min-rating/saved-presets
// controls were dropped as part of this redesign (STUDIO-128 plan).
// "Excluded" is kept as a plain link alongside the four stat buttons: it's
// the only way to see and restore a model once it's been excluded from the
// viewer, so removing it would make exclusion irreversible via the UI.

import { useState, useEffect } from "react";
import { PanelLeft, Search, AlertCircle, Star, Printer, Sparkles, EyeOff, Tag, X } from "lucide-react";
import type { LibraryFilters } from "../../hooks/useLibraryFilters";
import { nextTagParams } from "../../utils/tagFilter";

const SITES = ["thingiverse", "printables", "myminifactory", "cults3d", "gumroad", "thangs", "makerworld", "other"];

const SIDEBAR_COLLAPSED_KEY = "stl_sidebar_collapsed";

export function useSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1");
  useEffect(() => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
  }, [collapsed]);
  return [collapsed, setCollapsed] as const;
}

interface StatButtonProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count?: number;
  colorClass: string;
}

function StatButton({ active, onClick, icon, label, count, colorClass }: StatButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg text-xs font-medium border transition-colors ${colorClass} ${
        active ? "ring-1 ring-inset ring-current" : ""
      }`}
    >
      <span className="flex items-center gap-1.5">
        {icon}
        {label}
      </span>
      {count !== undefined && <span>{count}</span>}
    </button>
  );
}

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  total: number;
  filters: LibraryFilters;
  creators: { id: number; name: string; model_count: number }[];
  allTags: { tag: string; count: number }[];
  stats: {
    needs_review: number;
    favorites: number;
    queued: number;
    excluded: number;
  } | null;
  recentDays: number;
  hasFilters: boolean;
}

export default function Sidebar({
  collapsed, onToggleCollapsed, total, filters, creators, allTags, stats, recentDays, hasFilters,
}: SidebarProps) {
  const {
    searchInput, searchInputRef, onSearchChange, clearSearch,
    activeTag, excludeTag, creatorId, site, supportParam,
    needsReview, favParam, printStatusParam, addedDays, excludedParam,
    setParam, setParams, setSearchParams,
  } = filters;

  const [tagSearch, setTagSearch] = useState("");
  const visibleTags = allTags.filter(({ tag }) => !tagSearch || tag.includes(tagSearch.toLowerCase()));

  return (
    <aside
      className={`shrink-0 bg-panel-inset border-r border-border-subtle flex flex-col gap-5 py-6 transition-[width] duration-200 overflow-hidden ${
        collapsed ? "w-16 px-3" : "w-64 px-4"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        {!collapsed && (
          <div className="min-w-0">
            <h1 className="text-xl font-extrabold text-text-primary tracking-tight whitespace-nowrap">Library</h1>
            <p className="text-xs text-text-muted whitespace-nowrap">{total.toLocaleString()} models</p>
          </div>
        )}
        <button
          onClick={onToggleCollapsed}
          title="Toggle filter sidebar"
          aria-label="Toggle filter sidebar"
          className="shrink-0 p-1.5 rounded-md bg-panel-secondary border border-border-subtle text-text-secondary hover:text-text-primary transition-colors"
        >
          <PanelLeft size={14} />
        </button>
      </div>

      {!collapsed && (
        <div className="flex flex-col gap-5 overflow-y-auto">
          {/* Quick-filter stat buttons */}
          <div className="flex flex-col gap-1.5">
            {stats && stats.needs_review > 0 && (
              <StatButton
                active={needsReview}
                onClick={() => setParam("needs_review", needsReview ? "" : "1")}
                icon={<AlertCircle size={13} />}
                label="Need review"
                count={stats.needs_review}
                colorClass="bg-status-amber/10 border-status-amber/20 text-status-amber"
              />
            )}
            {stats && stats.favorites > 0 && (
              <StatButton
                active={favParam}
                onClick={() => setParam("is_favorite", favParam ? "" : "1")}
                icon={<Star size={13} fill="currentColor" />}
                label="Favorites"
                count={stats.favorites}
                colorClass="bg-status-yellow/10 border-status-yellow/20 text-status-yellow"
              />
            )}
            {stats && stats.queued > 0 && (
              <StatButton
                active={printStatusParam === "queued"}
                onClick={() => setParams({ print_status: printStatusParam === "queued" ? "" : "queued", exclude_printed: "" })}
                icon={<Printer size={13} />}
                label="Queued"
                count={stats.queued}
                colorClass="bg-status-sky/10 border-status-sky/20 text-status-sky"
              />
            )}
            <StatButton
              active={!!addedDays}
              onClick={() => setParam("added_days", addedDays ? "" : String(recentDays))}
              icon={<Sparkles size={13} />}
              label="Recently added"
              colorClass="bg-accent-start/10 border-accent-start/20 text-accent-start"
            />
            {/* Not in the design mockup — kept so an excluded model has a recovery
                path (see file header). Understated on purpose. */}
            {stats && (stats.excluded > 0 || excludedParam) && (
              <button
                onClick={() => setParam("excluded", excludedParam ? "" : "1")}
                className={`flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${
                  excludedParam
                    ? "text-text-secondary bg-panel-secondary"
                    : "text-text-muted hover:text-text-secondary"
                }`}
              >
                <span className="flex items-center gap-1.5"><EyeOff size={12} /> Excluded</span>
                <span>{stats.excluded}</span>
              </button>
            )}
          </div>

          {/* Search */}
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              ref={searchInputRef}
              type="text"
              placeholder="Search models…  (press / )"
              value={searchInput}
              onChange={(e) => onSearchChange(e.target.value)}
              className="w-full bg-panel-secondary border border-border-subtle rounded-lg pl-8 pr-8 py-2 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-start"
            />
            {searchInput && (
              <button
                type="button"
                onClick={clearSearch}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary transition-colors"
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Creator / Site / Support dropdowns */}
          <div className="flex flex-col gap-3.5 border-t border-border pt-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-text-muted mb-1.5">Creator</p>
              <select
                value={creatorId}
                onChange={(e) => setParams({ creator_id: e.target.value, exclude_creator_id: "" })}
                className="w-full bg-panel-secondary border border-border-subtle rounded-lg px-2.5 py-2 text-sm text-text-primary-alt focus:outline-none focus:border-accent-start"
              >
                <option value="">All Creators</option>
                {creators.map((c) => (
                  <option key={c.id} value={c.id}>{c.name} ({c.model_count})</option>
                ))}
              </select>
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-text-muted mb-1.5">Site</p>
              <select
                value={site}
                onChange={(e) => setParam("source_site", e.target.value)}
                className="w-full bg-panel-secondary border border-border-subtle rounded-lg px-2.5 py-2 text-sm text-text-primary-alt focus:outline-none focus:border-accent-start"
              >
                <option value="">All Sites</option>
                {SITES.map((s) => (
                  <option key={s} value={s} className="capitalize">{s}</option>
                ))}
              </select>
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-text-muted mb-1.5">Support status</p>
              <select
                value={supportParam}
                onChange={(e) => setParam("support_status", e.target.value)}
                title="Filter by print-support status"
                className={`w-full bg-panel-secondary border rounded-lg px-2.5 py-2 text-sm focus:outline-none focus:border-accent-start ${
                  supportParam ? "border-accent-start text-accent-start" : "border-border-subtle text-text-primary-alt"
                }`}
              >
                <option value="">All supports</option>
                <option value="unsupported">Unsupported</option>
                <option value="pre-supported">Pre-supported</option>
                <option value="supported">Supported</option>
              </select>
            </div>

            <label className="flex items-center gap-1.5 text-sm text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={needsReview}
                onChange={(e) => setParam("needs_review", e.target.checked ? "1" : "")}
                className="accent-status-amber"
              />
              Needs review only
            </label>

            {allTags.length > 0 && (
              <div>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <Tag size={11} className="text-text-muted" />
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">Tags</p>
                </div>
                <input
                  type="text"
                  placeholder="Search tags…"
                  value={tagSearch}
                  onChange={(e) => setTagSearch(e.target.value)}
                  className="w-full bg-panel-secondary border border-border-subtle rounded-lg px-2.5 py-1.5 text-xs text-text-primary-alt placeholder-text-muted focus:outline-none focus:border-accent-start mb-2"
                />
                <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                  {visibleTags.map(({ tag, count }) => {
                    const isInclude = activeTag === tag;
                    const isExclude = excludeTag === tag;
                    return (
                      <button
                        key={tag}
                        onClick={() => setParams(nextTagParams(tag, activeTag, excludeTag))}
                        title={isInclude ? "Click again to exclude this tag" : isExclude ? "Click to clear" : "Show only this tag"}
                        className={`px-2 py-1 rounded-md text-xs transition-colors ${
                          isInclude
                            ? "bg-accent-end text-white"
                            : isExclude
                            ? "bg-status-rose-dark text-white"
                            : "bg-panel-secondary border border-border-subtle text-text-primary-alt2 hover:border-accent-start"
                        }`}
                      >
                        {isExclude && "≠ "}{tag} {count}
                      </button>
                    );
                  })}
                  {visibleTags.length === 0 && (
                    <span className="text-xs text-text-muted">No tags match "{tagSearch}"</span>
                  )}
                </div>
              </div>
            )}

            {hasFilters && (
              <button
                onClick={() => setSearchParams(searchInput ? { q: searchInput } : {})}
                className="text-xs text-text-muted hover:text-text-secondary text-left"
              >
                Clear all filters
              </button>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}

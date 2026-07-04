// All Library filter state lives in the URL. This hook owns the read side
// (deriving typed filter values from the query string), the write side
// (setParam / setParams / setPage, all resetting to page 1), the debounced
// search box, sort resolution + persistence, and the memoized list-query param
// set. Extracted from Library.tsx (STUDIO-63 P4) — behavior-preserving.

import { useState, useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { LibrarySort } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";

export function useLibraryFilters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { settings, update: updateSettings } = useAppSettings();
  const pageSize = settings.library_page_size;

  // All filter state lives in the URL
  const page         = Number(searchParams.get("page") ?? 1);
  const search       = searchParams.get("q") ?? "";
  const creatorId    = searchParams.get("creator_id") ?? "";
  const excludeCreatorId = searchParams.get("exclude_creator_id") ?? "";
  const site         = searchParams.get("source_site") ?? "";
  const activeTag    = searchParams.get("tag") ?? "";
  const excludeTag   = searchParams.get("exclude_tag") ?? "";
  const needsReview  = searchParams.get("needs_review") === "1";
  const nsfwParam    = searchParams.get("nsfw") ?? "";        // "" | "1" | "0"
  const thumbParam   = searchParams.get("has_thumbnail") ?? ""; // "" | "1" | "0"
  const favParam     = searchParams.get("is_favorite") === "1";
  const printStatusParam = searchParams.get("print_status") ?? "";
  const excludePrinted = searchParams.get("exclude_printed") === "1";
  const excludedParam = searchParams.get("excluded") === "1";
  const inboxParam   = searchParams.get("is_inbox") === "1";
  const minRating    = searchParams.get("min_rating") ?? "";  // "" | "1".."5" (#167)
  const supportParam = searchParams.get("support_status") ?? ""; // "" | "unsupported" | "pre-supported" | "supported" (#609)
  const slicerParam  = searchParams.get("slicer") ?? "";        // "" | "lychee" | "chitubox" (#609)
  const addedDays    = searchParams.get("added_days") ?? ""; // "Recently added" window (#170)
  const sortParam    = searchParams.get("sort") ?? "";       // "" | "name" | "added" | "creator" (#247)

  // Update one or more filter params in a single history entry and reset to
  // page 1. Multi-key form serves the mutually exclusive pairs
  // (creator_id/exclude_creator_id, tag/exclude_tag). Page itself goes
  // through setPage, never through here.
  const setParams = (updates: Record<string, string>) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [key, value] of Object.entries(updates)) {
        if (value) next.set(key, value); else next.delete(key);
      }
      next.delete("page");
      return next;
    });
  };
  const setParam = (key: string, value: string) => setParams({ [key]: value });

  // Search is debounced (#220): the input binds to local state for instant
  // feedback, and the `q` URL param is written ~250 ms after the last keystroke
  // with { replace: true } so typing doesn't fire a fetch per character or push
  // a history entry per character (Back used to step through "a", "ak", …).
  const [searchInput, setSearchInput] = useState(search);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep the input in sync when `q` changes from outside the box (clear-filters,
  // back/forward navigation, applying a preset). While typing, `q` is stale
  // between debounce flushes so this effect doesn't fight the local state. Any
  // pending debounce is dropped here too: an external `q` change supersedes a
  // half-typed value, so a late timer mustn't resurrect it (e.g. type then Back).
  useEffect(() => {
    setSearchInput(search);
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
  }, [search]);
  useEffect(() => () => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
  }, []);
  const onSearchChange = (value: string) => {
    setSearchInput(value);
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set("q", value); else next.delete("q");
        next.delete("page");
        return next;
      }, { replace: true });
    }, 250);
  };

  // Clear the search immediately — skip the debounce so the results update at
  // once — then return focus to the input for the next query (#355).
  const clearSearch = () => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    setSearchInput("");
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("q");
      next.delete("page");
      return next;
    }, { replace: true });
    searchInputRef.current?.focus();
  };

  const setPage = (p: number) => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      p > 1 ? next.set("page", String(p)) : next.delete("page");
      return next;
    });
  };

  // Sort (#247): the URL is canonical, but when it carries no `sort` the persisted
  // default applies. addedDays ("Recently added") forces newest-first regardless.
  const effectiveSort = addedDays ? "added" : (sortParam || settings.library_sort);
  // Mirror a non-default persisted sort into the URL so presets capture it and the
  // detail-page Prev/Next (which only sees the origin URL) walks the same order.
  useEffect(() => {
    if (!sortParam && !addedDays && settings.library_sort && settings.library_sort !== "name") {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("sort", settings.library_sort);
        return next;
      }, { replace: true });
    }
  }, [sortParam, addedDays, settings.library_sort, setSearchParams]);

  // Changing the dropdown drives the URL and persists the new default server-side.
  const changeSort = (value: LibrarySort) => {
    void updateSettings({ library_sort: value });
    setParam("sort", value);
  };

  // Variant grouping collapses non-representative variants. When filtering by
  // favorites/queue/printed (which apply to individual variants), disable grouping
  // so a flagged non-representative variant isn't hidden behind its group.
  const groupVariants = !favParam && !printStatusParam && !excludedParam;

  // The full list-query param set, memoized so it doubles as a stable cache key.
  const listParams = useMemo(() => {
    const params: Record<string, string | number | boolean> = { page, page_size: pageSize, group_variants: groupVariants };
    if (search)      params.q             = search;
    if (creatorId)   params.creator_id    = creatorId;
    if (excludeCreatorId) params.exclude_creator_id = excludeCreatorId;
    if (site)        params.source_site   = site;
    if (activeTag)   params.tag           = activeTag;
    if (excludeTag)  params.exclude_tag   = excludeTag;
    if (needsReview) params.needs_review  = true;
    if (nsfwParam)   params.nsfw          = nsfwParam === "1";
    if (thumbParam)  params.has_thumbnail = thumbParam === "1";
    if (favParam)    params.is_favorite   = true;
    if (printStatusParam) params.print_status  = printStatusParam;
    if (excludePrinted) params.exclude_printed = true;
    if (excludedParam) params.excluded    = true;
    if (inboxParam)   params.is_inbox   = true;
    if (minRating)   params.min_rating   = minRating;
    if (supportParam) params.support_status = supportParam;
    if (slicerParam)  params.slicer       = slicerParam;
    if (addedDays)   params.added_within_days = addedDays;
    if (effectiveSort && effectiveSort !== "name") params.sort = effectiveSort;
    return params;
  }, [page, pageSize, groupVariants, search, creatorId, excludeCreatorId, site, activeTag, excludeTag, needsReview, nsfwParam, thumbParam, favParam, printStatusParam, excludePrinted, excludedParam, inboxParam, minRating, supportParam, slicerParam, addedDays, effectiveSort]);

  return {
    // raw URL access (for callers that build their own param mutations)
    searchParams, setSearchParams,
    // derived filter values
    page, search, creatorId, excludeCreatorId, site, activeTag, excludeTag,
    needsReview, nsfwParam, thumbParam, favParam, printStatusParam, excludePrinted,
    excludedParam, inboxParam, minRating, supportParam, slicerParam, addedDays, sortParam,
    // writers
    setParam, setParams, setPage,
    // search box
    searchInput, searchInputRef, onSearchChange, clearSearch,
    // sort + grouping
    effectiveSort, changeSort, groupVariants,
    // list query params
    listParams,
  };
}

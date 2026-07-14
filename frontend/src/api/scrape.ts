import { request } from "./base";
import type { GroupScrapeResult, ScrapePreview } from "./types";

export const scrapeApi = {
  fetchUrl: (url: string) =>
    request<ScrapePreview>(`/scrape/fetch?url=${encodeURIComponent(url)}`),
  applyMetadata: (modelId: number, body: Partial<ScrapePreview>) =>
    request<{ ok: boolean }>(`/scrape/apply/${modelId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // Fill a model's gallery from scraped image_urls without touching any other
  // field (#1028) — for callers that write the rest of the fields themselves.
  applyImages: (modelId: number, imageUrls: string[]) =>
    request<{ ok: boolean; image_paths: string[] }>(`/scrape/apply-images/${modelId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_urls: imageUrls }),
    }),
  // Set a store page on selected variants and fetch+apply its metadata in one
  // step (#545). Scrapes once and fans out to all ids.
  applyGroup: (modelIds: number[], url: string) =>
    request<GroupScrapeResult>(`/scrape/apply-group`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_ids: modelIds, url }),
    }),
};

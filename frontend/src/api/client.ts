// Public API barrel (#STUDIO-62). The former 1600-line monolith was split into
// per-domain modules under api/*; this file re-composes them so every existing
// `import { api, type Model, ApiError } from "../api/client"` keeps working
// unchanged. New code may import the domain modules directly.

export * from "./types";
export { ApiError } from "./base";
export type { StampOptions, SeriesExportOptions } from "./base";

import { modelsApi } from "./models";
import { filesApi, fileUrl, documentUrl, stlUrl, downloadZip } from "./files";
import { reorganizeApi } from "./reorganize";
import { scrapeApi } from "./scrape";
import { scanApi } from "./scan";
import { importApi } from "./imports";
import { settingsApi } from "./settings";
import { paintingApi } from "./painting";
import { databaseApi } from "./database";
import { collectionsApi } from "./collections";

export const api = {
  models: modelsApi,
  files: filesApi,
  reorganize: reorganizeApi,
  scrape: scrapeApi,
  scan: scanApi,
  import: importApi,
  settings: settingsApi,
  painting: paintingApi,
  database: databaseApi,
  collections: collectionsApi,
  // Top-level URL/download helpers (kept flat on `api` for call-site parity).
  fileUrl,
  documentUrl,
  stlUrl,
  downloadZip,
};

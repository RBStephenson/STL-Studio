import { describe, it, expect } from "vitest";
import {
  api,
  ApiError,
  PRINT_STATUS_CYCLE,
  PAINT_FINISHES,
  type Model,
  type Guide,
} from "./client";

// Guards the #STUDIO-62 split: client.ts is now a barrel re-composing the
// per-domain api/* modules. These assertions fail loudly if a domain slice,
// method, or top-level helper is dropped or misnamed during future edits.

const EXPECTED_SLICE_METHODS: Record<string, string[]> = {
  models: [
    "list", "get", "stats", "creators", "tags", "renameTag", "mergeTag",
    "deleteTag", "update", "setGroupRep", "setThumbnail", "clearThumbnail",
    "setNSFW", "setFavorite", "setRating", "reorderQueue", "setExcluded",
    "setPrintStatus", "bulkTag", "bulkExclude", "bulkReview", "bulkEnrich",
    "bulkDelete", "characters", "variants", "splitPack", "mergeGroup",
    "splitGroup", "patchGroup", "getGroupingStrategy", "setGroupingStrategy",
    "reorderGroup", "updateSTLFile", "batchThumbnailFromUrl", "neighbors",
  ],
  files: ["openFolder", "driveStatus"],
  reorganize: ["preview", "previewWithOverrides", "apply", "undo"],
  scrape: ["fetchUrl", "applyMetadata", "applyImages", "applyGroup"],
  scan: [
    "start", "startCreator", "cancel", "status", "browse", "startInboxScan",
    "roots", "libraries", "addRoot", "updateRoot", "removeRoot",
  ],
  import: [
    "sourceContents", "scanFolder", "preview", "getMapping", "setMapping",
    "apply", "downloadImages",
  ],
  settings: ["get", "update", "upsertPreset", "deletePreset", "reloadEnv", "systemInfo"],
  painting: ["colorMatch", "colorMatchPoint"],
  database: ["backup", "restore", "health", "repair", "reset"],
  collections: [
    "list", "create", "getModels", "addModel", "removeModel", "update",
    "delete", "bulkAddModels",
  ],
};

describe("api barrel", () => {
  it("exposes every domain slice", () => {
    for (const slice of Object.keys(EXPECTED_SLICE_METHODS)) {
      expect(api[slice as keyof typeof api], slice).toBeTypeOf("object");
    }
  });

  it("keeps every domain method as a callable", () => {
    for (const [slice, methods] of Object.entries(EXPECTED_SLICE_METHODS)) {
      const obj = api[slice as keyof typeof api] as Record<string, unknown>;
      for (const m of methods) {
        expect(obj[m], `api.${slice}.${m}`).toBeTypeOf("function");
      }
    }
  });

  it("keeps nested settings sub-slices", () => {
    for (const sub of ["ai", "cults", "mmf"] as const) {
      expect(api.settings[sub].get).toBeTypeOf("function");
    }
  });

  it("keeps nested painting sub-slices", () => {
    for (const sub of ["brands", "lines", "inventory", "paints", "guides"] as const) {
      expect(api.painting[sub]).toBeTypeOf("object");
    }
    expect(api.painting.guides.exportSeriesPdf).toBeTypeOf("function");
  });

  it("keeps top-level url/download helpers flat on api", () => {
    expect(api.fileUrl).toBeTypeOf("function");
    expect(api.documentUrl).toBeTypeOf("function");
    expect(api.stlUrl).toBeTypeOf("function");
    expect(api.downloadZip).toBeTypeOf("function");
    // url builders are pure — verify they still shape the query string.
    expect(api.fileUrl("/a b.png", "9")).toBe(
      "/api/files/image?path=%2Fa%20b.png&v=9",
    );
    expect(api.stlUrl("/x.stl")).toBe("/api/files/stl?path=%2Fx.stl");
  });

  it("re-exports ApiError and value constants", () => {
    expect(new ApiError(404, "nope")).toBeInstanceOf(Error);
    expect(new ApiError(404, "nope").status).toBe(404);
    expect(PRINT_STATUS_CYCLE).toContain("printed");
    expect(PAINT_FINISHES).toContain("metallic");
  });

  it("re-exports types (compile-time only)", () => {
    const m = null as unknown as Model;
    const g = null as unknown as Guide;
    expect(m).toBeNull();
    expect(g).toBeNull();
  });
});

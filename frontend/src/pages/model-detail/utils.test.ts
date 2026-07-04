import { describe, it, expect } from "vitest";
import {
  toPascalCase,
  autoPartName,
  buildAlphaBand,
  groupAlphabetically,
  buildFileHierarchy,
  parseLibraryOrigin,
} from "./utils";

describe("toPascalCase", () => {
  it("title-cases each word and collapses whitespace", () => {
    expect(toPascalCase("  right   ARM ")).toBe("Right Arm");
  });
  it("returns empty string for blank input", () => {
    expect(toPascalCase("   ")).toBe("");
  });
});

describe("autoPartName", () => {
  it("strips .stl extension, Sup_ prefix, and underscores", () => {
    expect(autoPartName("Sup_left_arm.stl")).toBe("left arm");
  });
  it("leaves a plain name untouched", () => {
    expect(autoPartName("Head")).toBe("Head");
  });
});

describe("buildAlphaBand", () => {
  it("maps letters to their band", () => {
    expect(buildAlphaBand("b")).toBe("A–D");
    expect(buildAlphaBand("Z")).toBe("U–Z");
  });
  it("groups digits under 0–9", () => {
    expect(buildAlphaBand("3")).toBe("0–9");
  });
  it("falls back to # for non-alphanumerics", () => {
    expect(buildAlphaBand("!")).toBe("#");
  });
});

describe("groupAlphabetically", () => {
  it("buckets by first-letter band in canonical order", () => {
    const files = [
      { id: 1, filename: "Zorro.stl" },
      { id: 2, filename: "apple.stl" },
      { id: 3, filename: "9mm.stl" },
    ];
    const result = groupAlphabetically(files);
    expect(result.map(([band]) => band)).toEqual(["A–D", "U–Z", "0–9"]);
    expect(result[0][1][0].filename).toBe("apple.stl");
  });
});

describe("buildFileHierarchy", () => {
  it("nests sup files under their base as depth 1, sorted", () => {
    const files = [
      { id: 1, filename: "body.stl", sup_of_id: null },
      { id: 2, filename: "Sup_body.stl", sup_of_id: 1 },
      { id: 3, filename: "arm.stl", sup_of_id: null },
    ];
    const result = buildFileHierarchy(files);
    expect(result.map((r) => [r.file.id, r.depth])).toEqual([
      [3, 0], // arm sorts before body
      [1, 0],
      [2, 1],
    ]);
  });

  it("promotes orphaned sup files (missing parent) to top level", () => {
    const files = [
      { id: 2, filename: "Sup_ghost.stl", sup_of_id: 99 },
    ];
    const result = buildFileHierarchy(files);
    expect(result).toEqual([{ file: files[0], depth: 0 }]);
  });
});

describe("parseLibraryOrigin", () => {
  it("returns null when origin is undefined or not the Library grid", () => {
    expect(parseLibraryOrigin(undefined)).toBeNull();
    expect(parseLibraryOrigin("/collections/3?q=foo")).toBeNull();
  });

  it("extracts string filters and defaults group_variants to true", () => {
    const params = parseLibraryOrigin("/?q=knight&creator_id=5");
    expect(params).toMatchObject({ q: "knight", creator_id: "5", group_variants: true });
  });

  it("treats nsfw/has_thumbnail as tri-state", () => {
    expect(parseLibraryOrigin("/?nsfw=1")).toMatchObject({ nsfw: true });
    expect(parseLibraryOrigin("/?nsfw=0")).toMatchObject({ nsfw: false });
    expect(parseLibraryOrigin("/?q=x")).not.toHaveProperty("nsfw");
  });

  it("disables group_variants for favorite / print-status / excluded views", () => {
    expect(parseLibraryOrigin("/?is_favorite=1")).toMatchObject({
      is_favorite: true,
      group_variants: false,
    });
    expect(parseLibraryOrigin("/?print_status=printed")).toMatchObject({
      print_status: "printed",
      group_variants: false,
    });
  });

  it("maps the recently-added view to added_within_days + added sort", () => {
    expect(parseLibraryOrigin("/?added_days=7")).toMatchObject({
      added_within_days: "7",
      sort: "added",
    });
  });

  it("preserves an explicit sort when no added_days is present", () => {
    expect(parseLibraryOrigin("/?sort=name")).toMatchObject({ sort: "name" });
  });
});

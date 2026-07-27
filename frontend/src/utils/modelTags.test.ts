import { describe, it, expect } from "vitest";
import { Model } from "../api/client";
import { tagClass, visibleTags, TAG_COLORS } from "./modelTags";

function mkModel(over: Partial<Model> = {}): Model {
  return { id: 1, name: "m", auto_tags: [], removed_auto_tags: [], tags: [], ...over } as Model;
}

describe("visibleTags", () => {
  it("shows auto tags first, then the user's own", () => {
    const m = mkModel({ auto_tags: ["statue"], tags: ["favourite"] });
    expect(visibleTags(m)).toEqual(["statue", "favourite"]);
  });

  it("hides auto tags the user removed", () => {
    const m = mkModel({ auto_tags: ["statue", "bust"], removed_auto_tags: ["bust"] });
    expect(visibleTags(m)).toEqual(["statue"]);
  });

  it("de-duplicates a user tag that repeats an auto tag", () => {
    const m = mkModel({ auto_tags: ["statue"], tags: ["statue", "resin"] });
    expect(visibleTags(m)).toEqual(["statue", "resin"]);
  });

  it("prefers caller-supplied tags so an in-flight edit can be shown optimistically", () => {
    const m = mkModel({ auto_tags: ["statue"], tags: ["old"] });
    expect(visibleTags(m, ["new"])).toEqual(["statue", "new"]);
  });

  it("tolerates a model with no tag fields at all", () => {
    expect(visibleTags({ id: 1, name: "m" } as Model)).toEqual([]);
  });
});

describe("tagClass", () => {
  it("uses the known colour for a recognised tag", () => {
    expect(tagClass("statue")).toBe(TAG_COLORS.statue);
  });

  it("falls back to neutral styling for anything else", () => {
    expect(tagClass("some-user-tag")).toBe("bg-panel-secondary text-text-secondary");
  });
});

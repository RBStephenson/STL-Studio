import { describe, it, expect } from "vitest";
import { modelLinkTo } from "./modelLink";
import type { Model } from "../api/client";

function model(overrides: Partial<Model> = {}): Model {
  return {
    id: 1,
    name: "Test",
    title: null,
    creator_id: 5,
    character: null,
    variant_group_id: null,
    variant_group: null,
    variant_count: 1,
    folder_path: "/tmp/test",
    thumbnail_path: null,
    thumbnail_url: null,
    source_url: null,
    source_site: null,
    external_id: null,
    description: null,
    tags: [],
    auto_tags: [],
    category: null,
    license: null,
    needs_review: false,
    excluded: false,
    is_group_rep: false,
    variant_order: null,
    print_status: null,
    star_rating: null,
    created_at: "",
    updated_at: "",
    ...overrides,
  } as unknown as Model;
}

describe("modelLinkTo", () => {
  it("routes single model to /models/:id", () => {
    expect(modelLinkTo(model())).toBe("/models/1");
  });

  it("routes variant group without group_id to character path", () => {
    const m = model({ variant_count: 3, character: "Vigilante", variant_group_id: null });
    expect(modelLinkTo(m)).toBe("/groups/5/Vigilante");
  });

  it("appends ?gid when variant_group_id is set", () => {
    const m = model({ variant_count: 3, character: "Vigilante", variant_group_id: 42 });
    expect(modelLinkTo(m)).toBe("/groups/5/Vigilante?gid=42");
  });

  it("uses the durable group label for grouped cards when available", () => {
    const m = model({
      variant_count: 3,
      character: "Old Scanner Label",
      variant_group_id: 42,
      variant_group: {
        id: 42,
        creator_id: 5,
        label: "Renamed Group",
        rep_model_id: 1,
        source: "manual",
        reason: null,
        confidence: null,
      },
    });
    expect(modelLinkTo(m)).toBe("/groups/5/Renamed%20Group?gid=42");
  });

  it("encodes special characters in the character name", () => {
    const m = model({ variant_count: 2, character: "Spider-Man (Alt)", variant_group_id: 7 });
    expect(modelLinkTo(m)).toBe("/groups/5/Spider-Man%20(Alt)?gid=7");
  });

  it("uses the model name as the readable segment when a grouped card has no character", () => {
    const m = model({ variant_count: 2, character: null, variant_group_id: 42 });
    expect(modelLinkTo(m)).toBe("/groups/5/Test?gid=42");
  });
});

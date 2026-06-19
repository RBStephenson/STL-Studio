import { describe, it, expect } from "vitest";
import { reorderedIds } from "./reorderList";

describe("reorderedIds (#399)", () => {
  it("moves an item forward to the target position", () => {
    expect(reorderedIds([1, 2, 3, 4], 4, 2)).toEqual([1, 4, 2, 3]);
  });

  it("moves an item backward to the target position", () => {
    expect(reorderedIds([1, 2, 3, 4], 1, 3)).toEqual([2, 3, 1, 4]);
  });

  it("returns the same order for a no-op move", () => {
    expect(reorderedIds([1, 2, 3], 2, 2)).toEqual([1, 2, 3]);
  });

  it("returns the input unchanged when an id is unknown", () => {
    expect(reorderedIds([1, 2, 3], 9, 2)).toEqual([1, 2, 3]);
    expect(reorderedIds([1, 2, 3], 2, 9)).toEqual([1, 2, 3]);
  });
});

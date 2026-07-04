import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const update = vi.fn(async (..._args: unknown[]) => ({}));
const tagsList = vi.fn(async () => [{ tag: "hero", count: 3 }]);
const toast = vi.fn();

vi.mock("../../../api/client", () => ({
  api: { models: { update: (...a: unknown[]) => update(...a), tags: () => tagsList() } },
}));
vi.mock("../../../context/ToastContext", () => ({ useToast: () => ({ toast }) }));

import { useModelTags } from "./useModelTags";
import { ModelDetail as ModelDetailType } from "../../../api/client";

const mkModel = (over: Partial<ModelDetailType> = {}) =>
  ({ id: 1, tags: ["dragon"], removed_auto_tags: ["gore"], ...over } as unknown as ModelDetailType);
// Stable references so the hook's `[model]` sync effect doesn't refire each render.
const model = mkModel();

beforeEach(() => {
  update.mockClear();
  tagsList.mockClear();
  toast.mockClear();
});

describe("useModelTags", () => {
  it("initializes tags and removedAutoTags from the model", () => {
    const { result } = renderHook(() => useModelTags(model, 1));
    expect(result.current.tags).toEqual(["dragon"]);
    expect(result.current.removedAutoTags).toEqual(["gore"]);
  });

  it("addTag appends optimistically and persists", async () => {
    const { result } = renderHook(() => useModelTags(model, 1));
    await act(async () => { await result.current.addTag("knight"); });
    expect(result.current.tags).toEqual(["dragon", "knight"]);
    expect(update).toHaveBeenCalledWith(1, { tags: ["dragon", "knight"] });
  });

  it("addTag is a no-op for a tag already present", async () => {
    const { result } = renderHook(() => useModelTags(model, 1));
    await act(async () => { await result.current.addTag("dragon"); });
    expect(update).not.toHaveBeenCalled();
  });

  it("reverts and toasts when a mutation fails", async () => {
    update.mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => useModelTags(model, 1));
    await act(async () => { await result.current.addTag("knight"); });
    expect(result.current.tags).toEqual(["dragon"]); // reverted
    expect(toast).toHaveBeenCalled();
  });

  it("suppressAutoTag adds to removed and drops it from user tags", async () => {
    const { result } = renderHook(() => useModelTags(model, 1));
    await act(async () => { await result.current.suppressAutoTag("dragon"); });
    expect(result.current.tags).toEqual([]);
    expect(result.current.removedAutoTags).toContain("dragon");
    expect(update).toHaveBeenCalledWith(1, { removed_auto_tags: ["gore", "dragon"], tags: [] });
  });

  it("restoreAutoTag removes it from the suppressed list", async () => {
    const { result } = renderHook(() => useModelTags(model, 1));
    await act(async () => { await result.current.restoreAutoTag("gore"); });
    expect(result.current.removedAutoTags).toEqual([]);
    expect(update).toHaveBeenCalledWith(1, { removed_auto_tags: [] });
  });

  it("openTagEditor opens the editor and lazy-loads suggestions once", async () => {
    const { result } = renderHook(() => useModelTags(model, 1));
    act(() => { result.current.openTagEditor(); });
    expect(result.current.editingTags).toBe(true);
    await waitFor(() => expect(result.current.tagSuggestions).toEqual([{ tag: "hero", count: 3 }]));
    // second open does not refetch
    act(() => { result.current.doneEditing(); });
    act(() => { result.current.openTagEditor(); });
    expect(tagsList).toHaveBeenCalledTimes(1);
  });

  it("toggleHidden flips the hidden-tags flag", () => {
    const { result } = renderHook(() => useModelTags(model, 1));
    expect(result.current.showHiddenTags).toBe(false);
    act(() => { result.current.toggleHidden(); });
    expect(result.current.showHiddenTags).toBe(true);
  });
});

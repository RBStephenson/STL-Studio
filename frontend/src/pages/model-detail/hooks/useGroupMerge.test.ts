import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const characters = vi.fn(async (..._a: unknown[]) => ["Knight", "Mage"]);
const variants = vi.fn(async (..._a: unknown[]) => ({ items: [] as unknown[] }));
const mergeGroup = vi.fn(async (..._a: unknown[]) => ({}));
const splitGroup = vi.fn(async (..._a: unknown[]) => ({}));
const toast = vi.fn();
const confirm = vi.fn(async () => true);

vi.mock("../../../api/client", () => ({
  api: {
    models: {
      characters: (...a: unknown[]) => characters(...a),
      variants: (...a: unknown[]) => variants(...a),
      mergeGroup: (...a: unknown[]) => mergeGroup(...a),
      splitGroup: (...a: unknown[]) => splitGroup(...a),
    },
  },
}));
vi.mock("../../../context/ToastContext", () => ({ useToast: () => ({ toast }) }));
vi.mock("../../../context/ConfirmContext", () => ({ useConfirm: () => confirm }));

import { useGroupMerge } from "./useGroupMerge";
import { ModelDetail as ModelDetailType } from "../../../api/client";

const model = { id: 1, creator_id: 7, variant_group_id: null } as unknown as ModelDetailType;
const grouped = { id: 1, creator_id: 7, variant_group_id: 42 } as unknown as ModelDetailType;
const reload = vi.fn();

beforeEach(() => {
  characters.mockClear(); variants.mockClear(); mergeGroup.mockClear();
  splitGroup.mockClear(); toast.mockClear(); confirm.mockClear(); reload.mockClear();
  variants.mockResolvedValue({ items: [] });
  confirm.mockResolvedValue(true);
});

describe("useGroupMerge", () => {
  it("openMergePicker opens the picker and loads character suggestions", async () => {
    const { result } = renderHook(() => useGroupMerge(model, 1, reload));
    act(() => { result.current.openMergePicker(); });
    expect(result.current.settingGroup).toBe(true);
    await waitFor(() => expect(result.current.groupSuggestions).toEqual(["Knight", "Mage"]));
    expect(characters).toHaveBeenCalledWith(7);
  });

  it("cancelMerge closes the picker", () => {
    const { result } = renderHook(() => useGroupMerge(model, 1, reload));
    act(() => { result.current.openMergePicker(); });
    act(() => { result.current.cancelMerge(); });
    expect(result.current.settingGroup).toBe(false);
  });

  it("mergeIntoGroup is a no-op with empty input", async () => {
    const { result } = renderHook(() => useGroupMerge(model, 1, reload));
    await act(async () => { await result.current.mergeIntoGroup(); });
    expect(variants).not.toHaveBeenCalled();
  });

  it("mergeIntoGroup merges into an existing group and reloads", async () => {
    variants.mockResolvedValueOnce({ items: [{ id: 2, variant_group_id: 42, variant_group: { label: "Knights" } }] });
    const { result } = renderHook(() => useGroupMerge(model, 1, reload));
    act(() => { result.current.setGroupInput("Knights"); });
    await act(async () => { await result.current.mergeIntoGroup(); });
    expect(mergeGroup).toHaveBeenCalledWith([1], { groupId: 42, label: "Knights" });
    expect(reload).toHaveBeenCalled();
    expect(result.current.settingGroup).toBe(false);
  });

  it("mergeIntoGroup errors when no matching group exists", async () => {
    variants.mockResolvedValueOnce({ items: [{ id: 2, variant_group_id: null }] });
    const { result } = renderHook(() => useGroupMerge(model, 1, reload));
    act(() => { result.current.setGroupInput("Nope"); });
    await act(async () => { await result.current.mergeIntoGroup(); });
    expect(mergeGroup).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("No existing group"), "error");
  });

  it("removeFromGroup confirms then splits the group and reloads", async () => {
    const { result } = renderHook(() => useGroupMerge(grouped, 1, reload));
    await act(async () => { await result.current.removeFromGroup(); });
    expect(confirm).toHaveBeenCalled();
    expect(splitGroup).toHaveBeenCalledWith(42, [1]);
    expect(reload).toHaveBeenCalled();
  });

  it("removeFromGroup does nothing when the user cancels the confirm", async () => {
    confirm.mockResolvedValueOnce(false);
    const { result } = renderHook(() => useGroupMerge(grouped, 1, reload));
    await act(async () => { await result.current.removeFromGroup(); });
    expect(splitGroup).not.toHaveBeenCalled();
  });
});

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

const updateSTLFile = vi.fn(async (..._args: unknown[]) => ({}));
const toast = vi.fn();
let settings: Record<string, boolean>;

vi.mock("../../../api/client", () => ({
  api: { models: { updateSTLFile: (...a: unknown[]) => updateSTLFile(...a) } },
}));
vi.mock("../../../context/ToastContext", () => ({ useToast: () => ({ toast }) }));
vi.mock("../../../context/AppSettingsContext", () => ({ useAppSettings: () => ({ settings }) }));

import { usePartEditing } from "./usePartEditing";
import { ModelDetail as ModelDetailType } from "../../../api/client";

type StlFiles = ModelDetailType["stl_files"];
const file = (id: number, filename: string, over: Partial<StlFiles[number]> = {}) =>
  ({ id, filename, path: `/${filename}`, size_bytes: 1024, sup_of_id: null, part_type: null, part_name: null, ...over } as StlFiles[number]);

// Stable references — a new object each render would refire the [model] sync effect.
const base = file(1, "body.stl");
const sup = file(2, "Sup_body.stl", { sup_of_id: 1 });
const model = { id: 1, stl_files: [base, sup] } as unknown as ModelDetailType;
const solo = { id: 1, stl_files: [file(3, "arm.stl", { part_type: "Arms", part_name: "Left" })] } as unknown as ModelDetailType;

const patchModel = vi.fn();

beforeEach(() => {
  updateSTLFile.mockClear();
  updateSTLFile.mockResolvedValue({});
  toast.mockClear();
  patchModel.mockClear();
  settings = { part_categories_enabled: true };
});

describe("usePartEditing", () => {
  it("initializes partTypes and partNames from the model", () => {
    const { result } = renderHook(() => usePartEditing(solo, patchModel, null));
    expect(result.current.partTypes).toEqual({ 3: "Arms" });
    expect(result.current.partNames).toEqual({ 3: "Left" });
  });

  it("savePartType persists the file and patches the cache", async () => {
    const { result } = renderHook(() => usePartEditing(model, patchModel, null));
    await act(async () => { await result.current.savePartType(1, "torso") });
    expect(updateSTLFile).toHaveBeenCalledWith(1, { part_type: "Torso" });
    expect(patchModel).toHaveBeenCalled();
    expect(result.current.partTypes[1]).toBe("Torso");
  });

  it("savePartType propagates the category to linked sup files", async () => {
    const { result } = renderHook(() => usePartEditing(model, patchModel, null));
    await act(async () => { await result.current.savePartType(1, "Torso") });
    // both base (1) and its sup (2) get updated
    expect(updateSTLFile).toHaveBeenCalledWith(1, { part_type: "Torso" });
    expect(updateSTLFile).toHaveBeenCalledWith(2, { part_type: "Torso" });
  });

  it("savePartName trims and persists", async () => {
    const { result } = renderHook(() => usePartEditing(model, patchModel, null));
    await act(async () => { await result.current.savePartName(1, "  Body  ") });
    expect(updateSTLFile).toHaveBeenCalledWith(1, { part_name: "Body" });
  });

  it("linkSup links the file and mirrors the base category", async () => {
    const withCat = { id: 1, stl_files: [file(1, "body.stl", { part_type: "Torso" }), file(2, "loose.stl")] } as unknown as ModelDetailType;
    const { result } = renderHook(() => usePartEditing(withCat, patchModel, null));
    await act(async () => { await result.current.linkSup(1, 2) });
    expect(updateSTLFile).toHaveBeenCalledWith(2, { sup_of_id: 1 });
    expect(updateSTLFile).toHaveBeenCalledWith(2, { part_type: "Torso" });
  });

  it("unlinkSup clears sup_of_id", async () => {
    const { result } = renderHook(() => usePartEditing(model, patchModel, null));
    await act(async () => { await result.current.unlinkSup(2) });
    expect(updateSTLFile).toHaveBeenCalledWith(2, { sup_of_id: null });
  });

  it("reverts partTypes and toasts on save failure", async () => {
    updateSTLFile.mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => usePartEditing(model, patchModel, null));
    await act(async () => { await result.current.savePartType(1, "Torso") });
    expect(toast).toHaveBeenCalled();
    expect(result.current.partTypes[1] ?? "").toBe(""); // reverted to saved (none)
  });
});

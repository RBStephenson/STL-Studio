// STUDIO-61: behavior of the model query hooks — enable/disable gating and the
// data each returns. The api layer is mocked at the boundary; the hooks own
// caching and the enabled predicate.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createTestQueryClient } from "../../test/queryWrapper";
import { useModel, useModelVariants, useModelNeighbors } from "./models";
import type { ModelDetail } from "../../api/client";

const getMock = vi.fn();
const variantsMock = vi.fn();
const neighborsMock = vi.fn();

vi.mock("../../api/client", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  api: {
    models: {
      get: (...a: unknown[]) => getMock(...a),
      variants: (...a: unknown[]) => variantsMock(...a),
      neighbors: (...a: unknown[]) => neighborsMock(...a),
    },
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = createTestQueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const model = (over: Partial<ModelDetail> = {}) =>
  ({ id: 1, creator_id: 3, character: "Hero", variant_group_id: null, ...over }) as ModelDetail;

beforeEach(() => {
  getMock.mockReset();
  variantsMock.mockReset();
  neighborsMock.mockReset();
});

describe("useModel", () => {
  it("fetches the model when an id is given", async () => {
    getMock.mockResolvedValue(model());
    const { result } = renderHook(() => useModel(1), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getMock).toHaveBeenCalledWith(1);
    expect(result.current.data?.id).toBe(1);
  });

  it("does not fetch when id is undefined", () => {
    renderHook(() => useModel(undefined), { wrapper });
    expect(getMock).not.toHaveBeenCalled();
  });
});

describe("useModelVariants", () => {
  it("fetches siblings when creator + character are present", async () => {
    variantsMock.mockResolvedValue({ items: [model(), model({ id: 2 })] });
    const { result } = renderHook(() => useModelVariants(model()), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(variantsMock).toHaveBeenCalledWith(3, "Hero", null);
    expect(result.current.data).toHaveLength(2);
  });

  it("is disabled with no creator", () => {
    renderHook(() => useModelVariants(model({ creator_id: null as unknown as number })), { wrapper });
    expect(variantsMock).not.toHaveBeenCalled();
  });

  it("is enabled by a durable group id even without a character", async () => {
    variantsMock.mockResolvedValue({ items: [] });
    renderHook(() => useModelVariants(model({ character: null, variant_group_id: 9 })), { wrapper });
    await waitFor(() => expect(variantsMock).toHaveBeenCalledWith(3, "", 9));
  });
});

describe("useModelNeighbors", () => {
  it("is disabled when navOrigin is null", () => {
    renderHook(() => useModelNeighbors(1, null), { wrapper });
    expect(neighborsMock).not.toHaveBeenCalled();
  });

  it("fetches neighbors with the origin params", async () => {
    neighborsMock.mockResolvedValue({ prev_id: 4, next_id: 6 });
    const origin = { q: "dragon", group_variants: true };
    const { result } = renderHook(() => useModelNeighbors(1, origin), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(neighborsMock).toHaveBeenCalledWith(1, origin);
    expect(result.current.data).toEqual({ prev_id: 4, next_id: 6 });
  });
});

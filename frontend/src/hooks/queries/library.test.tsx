// STUDIO-61: the Library read hooks pass their params through and surface the
// api response. The api layer is mocked at the boundary.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createTestQueryClient } from "../../test/queryWrapper";
import { useLibraryModels, useCreators, useModelStats } from "./models";
import { useGuideModelIds } from "./guides";

const listMock = vi.fn();
const creatorsMock = vi.fn();
const statsMock = vi.fn();
const modelIdsMock = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    models: {
      list: (...a: unknown[]) => listMock(...a),
      creators: (...a: unknown[]) => creatorsMock(...a),
      stats: (...a: unknown[]) => statsMock(...a),
    },
    painting: { guides: { modelIds: (...a: unknown[]) => modelIdsMock(...a) } },
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = createTestQueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  listMock.mockReset();
  creatorsMock.mockReset();
  statsMock.mockReset();
  modelIdsMock.mockReset();
});

describe("useLibraryModels", () => {
  it("passes the param object through and returns the list", async () => {
    listMock.mockResolvedValue({ items: [{ id: 1 }], total: 1, page: 1, page_size: 60 });
    const params = { page: 2, group_variants: true, q: "dragon" };
    const { result } = renderHook(() => useLibraryModels(params), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listMock).toHaveBeenCalledWith(params);
    expect(result.current.data?.total).toBe(1);
  });
});

describe("useCreators / useModelStats", () => {
  it("fetch their respective endpoints", async () => {
    creatorsMock.mockResolvedValue([{ id: 3, name: "Foo", model_count: 2 }]);
    statsMock.mockResolvedValue({ needs_review: 4 });
    const creators = renderHook(() => useCreators(), { wrapper });
    const stats = renderHook(() => useModelStats(), { wrapper });
    await waitFor(() => expect(creators.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(stats.result.current.isSuccess).toBe(true));
    expect(creators.result.current.data?.[0].name).toBe("Foo");
    expect(stats.result.current.data?.needs_review).toBe(4);
  });
});

describe("useGuideModelIds", () => {
  it("is disabled when the painting module is off", () => {
    renderHook(() => useGuideModelIds(false), { wrapper });
    expect(modelIdsMock).not.toHaveBeenCalled();
  });

  it("returns a Set of ids when enabled", async () => {
    modelIdsMock.mockResolvedValue({ model_ids: [1, 2, 3] });
    const { result } = renderHook(() => useGuideModelIds(true), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(new Set([1, 2, 3]));
  });
});

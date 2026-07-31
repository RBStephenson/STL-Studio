import { afterEach, describe, expect, it, vi } from "vitest";

import { collectionsApi } from "./collections";

function okResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

function errorResponse(status = 500, detail?: string): Response {
  return {
    ok: false,
    status,
    statusText: "Server Error",
    json: async () => (detail ? { detail } : {}),
  } as Response;
}

describe("collectionsApi.bulkAddModels", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("POSTs one request with every model id to the bulk endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse({ added: 2, total: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await collectionsApi.bulkAddModels(7, [1, 2]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/collections/7/models/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_ids: [1, 2] }),
    });
    expect(res).toEqual({ added: 2, total: 2 });
  });

  it("rejects when the request returns a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(errorResponse(500)));

    await expect(collectionsApi.bulkAddModels(7, [1, 2])).rejects.toThrow("500");
  });

  it("resolves with the server's added/total counts on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okResponse({ added: 3, total: 5 })));

    await expect(collectionsApi.bulkAddModels(7, [1, 2, 3])).resolves.toEqual({ added: 3, total: 5 });
  });
});

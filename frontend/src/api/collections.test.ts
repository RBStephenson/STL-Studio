import { afterEach, describe, expect, it, vi } from "vitest";

import { collectionsApi } from "./collections";

function okResponse(): Response {
  return { ok: true, status: 200, statusText: "OK" } as Response;
}

function errorResponse(status = 500): Response {
  return { ok: false, status, statusText: "Server Error" } as Response;
}

describe("collectionsApi.bulkAddModels", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("POSTs one add per model to the collection endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", fetchMock);

    await collectionsApi.bulkAddModels(7, [1, 2]);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledWith("/api/collections/7/models/1", { method: "POST" });
    expect(fetchMock).toHaveBeenCalledWith("/api/collections/7/models/2", { method: "POST" });
  });

  it("rejects when any add returns a non-2xx response", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(okResponse())
      .mockResolvedValueOnce(errorResponse(500));
    vi.stubGlobal("fetch", fetchMock);

    await expect(collectionsApi.bulkAddModels(7, [1, 2])).rejects.toThrow("500");
  });

  it("resolves when every add succeeds", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okResponse()));

    await expect(collectionsApi.bulkAddModels(7, [1, 2, 3])).resolves.toBeUndefined();
  });
});

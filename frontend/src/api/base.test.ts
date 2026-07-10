import { describe, it, expect, vi, afterEach } from "vitest";
import { request, triggerBlobDownload } from "./base";

describe("request", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves without parsing a body on 204 No Content", async () => {
    // Regression: several DELETE endpoints (e.g. AI API config) return 204
    // with an empty body. Calling res.json() unconditionally on it throws
    // ("Unexpected end of JSON input"), surfacing as a JSON error on an
    // otherwise-successful delete.
    const jsonSpy = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 204, statusText: "No Content", json: jsonSpy,
    }));

    await expect(request("/settings/ai-apis/1", { method: "DELETE" })).resolves.toBeUndefined();
    expect(jsonSpy).not.toHaveBeenCalled();
  });

  it("still parses the body for a normal 200 JSON response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: vi.fn().mockResolvedValue({ id: 1 }),
    }));

    await expect(request("/settings/ai-apis")).resolves.toEqual({ id: 1 });
  });
});

describe("triggerBlobDownload (STUDIO-94)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("clicks a temp anchor pointing at the object URL with the given filename", () => {
    const objectUrl = "blob:mock-url";
    vi.spyOn(URL, "createObjectURL").mockReturnValue(objectUrl);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    let appended: HTMLAnchorElement | undefined;
    vi.spyOn(document.body, "appendChild").mockImplementation((node) => {
      appended = node as HTMLAnchorElement;
      return node;
    });

    triggerBlobDownload(new Blob(["x"]), "export.csv");

    expect(appended?.href).toBe(objectUrl);
    expect(appended?.download).toBe("export.csv");
    expect(clickSpy).toHaveBeenCalledOnce();
  });

  it("revokes the object URL asynchronously, not synchronously after click", () => {
    vi.useFakeTimers();
    const objectUrl = "blob:mock-url";
    vi.spyOn(URL, "createObjectURL").mockReturnValue(objectUrl);
    const revokeSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.spyOn(document.body, "appendChild").mockImplementation((n) => n);

    triggerBlobDownload(new Blob(["x"]), "export.csv");

    // Must not be revoked in the same tick as the click — that's the bug
    // (some browsers cancel/corrupt the download if revoked too early).
    expect(revokeSpy).not.toHaveBeenCalled();

    vi.advanceTimersByTime(0);
    expect(revokeSpy).toHaveBeenCalledWith(objectUrl);
  });
});

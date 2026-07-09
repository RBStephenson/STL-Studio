import { describe, it, expect, vi, afterEach } from "vitest";
import { triggerBlobDownload } from "./base";

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

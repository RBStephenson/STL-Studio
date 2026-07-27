import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import {
  failureDetail,
  registerProcessFailureHandlers,
  registerRendererFailureHandler,
  type FailureUi,
} from "./failureHandling";

function ui(): FailureUi {
  return {
    log: vi.fn(),
    showRendererFailure: vi.fn().mockResolvedValue("reload"),
    showMainFailure: vi.fn().mockResolvedValue(undefined),
    quit: vi.fn(),
  };
}

describe("failure handling", () => {
  it("formats Error and non-Error failure reasons", () => {
    expect(failureDetail(new Error("boom"))).toContain("boom");
    expect(failureDetail({ code: 7 })).toBe('{"code":7}');
  });

  it("logs every main-process failure but shows only one dialog until it resolves", () => {
    const source = new EventEmitter();
    const target = ui();
    registerProcessFailureHandlers(source, target);

    source.emit("uncaughtException", new Error("main failed"));
    source.emit("unhandledRejection", "promise failed");
    source.emit("uncaughtException", new Error("main failed again"));

    expect(target.log).toHaveBeenCalledTimes(3);
    expect(target.showMainFailure).toHaveBeenCalledTimes(1);
    expect(target.showMainFailure).toHaveBeenCalledWith(expect.stringContaining("main failed"));
  });

  it("shows a new dialog for a failure that arrives after the prior one is dismissed", async () => {
    const source = new EventEmitter();
    const target = ui();
    registerProcessFailureHandlers(source, target);

    source.emit("uncaughtException", new Error("first failure"));
    await Promise.resolve();
    await Promise.resolve();

    source.emit("uncaughtException", new Error("second failure"));

    expect(target.showMainFailure).toHaveBeenCalledTimes(2);
    expect(target.log).toHaveBeenCalledTimes(2);
  });

  it("clears the dedupe guard even if showMainFailure rejects", async () => {
    const source = new EventEmitter();
    const target = ui();
    target.showMainFailure = vi
      .fn()
      .mockRejectedValueOnce(new Error("dialog API failed"))
      .mockResolvedValue(undefined);
    registerProcessFailureHandlers(source, target);

    source.emit("uncaughtException", new Error("first failure"));
    await Promise.resolve();
    await Promise.resolve();

    source.emit("uncaughtException", new Error("second failure"));

    expect(target.showMainFailure).toHaveBeenCalledTimes(2);
  });

  it("offers one renderer recovery prompt and reloads after approval", async () => {
    const webContents = new EventEmitter() as EventEmitter & { reload: ReturnType<typeof vi.fn> };
    webContents.reload = vi.fn();
    const win = {
      webContents,
      isDestroyed: () => false,
    };
    const target = ui();
    registerRendererFailureHandler(win as never, target);

    webContents.emit("render-process-gone", {}, { reason: "crashed", exitCode: 1 });
    webContents.emit("render-process-gone", {}, { reason: "crashed", exitCode: 1 });
    await Promise.resolve();

    expect(target.showRendererFailure).toHaveBeenCalledOnce();
    expect(webContents.reload).toHaveBeenCalledOnce();
  });
});

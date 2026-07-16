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
    showMainFailure: vi.fn(),
    quit: vi.fn(),
  };
}

describe("failure handling", () => {
  it("formats Error and non-Error failure reasons", () => {
    expect(failureDetail(new Error("boom"))).toContain("boom");
    expect(failureDetail({ code: 7 })).toBe('{"code":7}');
  });

  it("surfaces uncaught exceptions and unhandled rejections", () => {
    const source = new EventEmitter();
    const target = ui();
    registerProcessFailureHandlers(source, target);

    source.emit("uncaughtException", new Error("main failed"));
    source.emit("unhandledRejection", "promise failed");

    expect(target.showMainFailure).toHaveBeenCalledTimes(2);
    expect(target.log).toHaveBeenCalledTimes(2);
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

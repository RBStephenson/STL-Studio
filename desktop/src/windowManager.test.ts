import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createWindowStatePersister,
  editContextFromParams,
  handleAppCommand,
  navFor,
} from "./windowManager";

describe("navFor", () => {
  function fakeHistory() {
    return {
      canGoBack: vi.fn().mockReturnValue(true),
      canGoForward: vi.fn().mockReturnValue(false),
      goBack: vi.fn(),
      goForward: vi.fn(),
    };
  }

  it("delegates to the resolved webContents' navigation history", () => {
    const history = fakeHistory();
    const nav = navFor(() => ({ navigationHistory: history as never }));

    expect(nav.canGoBack()).toBe(true);
    expect(nav.canGoForward()).toBe(false);
    nav.goBack();
    nav.goForward();
    expect(history.goBack).toHaveBeenCalledOnce();
    expect(history.goForward).toHaveBeenCalledOnce();
  });

  it("re-resolves the webContents on every call (tracks focus changes)", () => {
    let current: { navigationHistory: ReturnType<typeof fakeHistory> } | null = null;
    const nav = navFor(() => current as never);

    expect(nav.canGoBack()).toBe(false);

    const history = fakeHistory();
    current = { navigationHistory: history };
    expect(nav.canGoBack()).toBe(true);
  });

  it("no-ops when there is no resolved webContents", () => {
    const nav = navFor(() => null);
    expect(nav.canGoBack()).toBe(false);
    expect(nav.canGoForward()).toBe(false);
    expect(() => nav.goBack()).not.toThrow();
    expect(() => nav.goForward()).not.toThrow();
    expect(() => nav.reload()).not.toThrow();
  });
});

describe("editContextFromParams", () => {
  it("maps Electron's context-menu params to an EditContext", () => {
    expect(
      editContextFromParams({ isEditable: true, editFlags: { canCopy: false, canPaste: true } }),
    ).toEqual({ isEditable: true, canCopy: false, canPaste: true });
  });
});

describe("handleAppCommand", () => {
  function fakeHistory() {
    return {
      canGoBack: vi.fn().mockReturnValue(true),
      canGoForward: vi.fn().mockReturnValue(true),
      goBack: vi.fn(),
      goForward: vi.fn(),
    };
  }

  it("goes back on browser-backward when possible", () => {
    const history = fakeHistory();
    handleAppCommand("browser-backward", history);
    expect(history.goBack).toHaveBeenCalledOnce();
    expect(history.goForward).not.toHaveBeenCalled();
  });

  it("goes forward on browser-forward when possible", () => {
    const history = fakeHistory();
    handleAppCommand("browser-forward", history);
    expect(history.goForward).toHaveBeenCalledOnce();
    expect(history.goBack).not.toHaveBeenCalled();
  });

  it("does nothing when there's nowhere to go", () => {
    const history = fakeHistory();
    history.canGoBack.mockReturnValue(false);
    history.canGoForward.mockReturnValue(false);
    handleAppCommand("browser-backward", history);
    handleAppCommand("browser-forward", history);
    expect(history.goBack).not.toHaveBeenCalled();
    expect(history.goForward).not.toHaveBeenCalled();
  });

  it("ignores unrelated commands", () => {
    const history = fakeHistory();
    handleAppCommand("something-else", history);
    expect(history.goBack).not.toHaveBeenCalled();
    expect(history.goForward).not.toHaveBeenCalled();
  });
});

describe("createWindowStatePersister", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces schedule() calls into a single delayed save", () => {
    const save = vi.fn();
    const state = { bounds: { width: 1280, height: 800 }, isMaximized: false };
    const persister = createWindowStatePersister({
      userDataDir: "/userdata",
      getState: () => state,
      delayMs: 250,
      save,
    });

    persister.schedule();
    vi.advanceTimersByTime(100);
    persister.schedule();
    vi.advanceTimersByTime(100);
    expect(save).not.toHaveBeenCalled();

    vi.advanceTimersByTime(250);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("/userdata", state);
  });

  it("flush() saves immediately and cancels any pending timer", () => {
    const save = vi.fn();
    const state = { bounds: { width: 1280, height: 800 }, isMaximized: true };
    const persister = createWindowStatePersister({
      userDataDir: "/userdata",
      getState: () => state,
      delayMs: 250,
      save,
    });

    persister.schedule();
    persister.flush();
    expect(save).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(1000);
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("flush() with no pending schedule still saves once", () => {
    const save = vi.fn();
    const persister = createWindowStatePersister({
      userDataDir: "/userdata",
      getState: () => ({ bounds: { width: 800, height: 600 }, isMaximized: false }),
      delayMs: 250,
      save,
    });
    persister.flush();
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("swallows save errors via onError instead of throwing", () => {
    const onError = vi.fn();
    const save = vi.fn().mockImplementation(() => {
      throw new Error("disk full");
    });
    const persister = createWindowStatePersister({
      userDataDir: "/userdata",
      getState: () => ({ bounds: { width: 800, height: 600 }, isMaximized: false }),
      delayMs: 250,
      save,
      onError,
    });

    expect(() => persister.flush()).not.toThrow();
    expect(onError).toHaveBeenCalledWith(expect.any(Error));
  });
});

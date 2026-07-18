import type { WebContents } from "electron";

import type { EditContext, NavTarget } from "./menu";
import { saveWindowState } from "./windowState";
import type { WindowState } from "./windowState";

/** A NavTarget over a webContents' navigation history, resolved lazily via
 *  `getWebContents` — so the same builder drives both a fixed window (its own
 *  webContents never changes) and the app menu (which must always act on
 *  whichever window currently has focus). */
export function navFor(
  getWebContents: () => Pick<WebContents, "navigationHistory" | "reload"> | null | undefined,
): NavTarget {
  const history = () => getWebContents()?.navigationHistory;
  return {
    canGoBack: () => history()?.canGoBack() ?? false,
    canGoForward: () => history()?.canGoForward() ?? false,
    goBack: () => history()?.goBack(),
    goForward: () => history()?.goForward(),
    reload: () => getWebContents()?.reload(),
  };
}

/** Builds the right-click context-menu params (EditContext) Electron's
 *  `context-menu` event carries into the shape `buildContextMenuTemplate`
 *  expects. */
export function editContextFromParams(params: {
  isEditable: boolean;
  editFlags: { canCopy: boolean; canPaste: boolean };
}): EditContext {
  return {
    isEditable: params.isEditable,
    canCopy: params.editFlags.canCopy,
    canPaste: params.editFlags.canPaste,
  };
}

export type NavigationHistoryLike = {
  canGoBack(): boolean;
  canGoForward(): boolean;
  goBack(): void;
  goForward(): void;
};

/** Mouse back/forward buttons (`app-command`) act on the window's own
 *  navigation history, silently no-op-ing when there's nowhere to go. */
export function handleAppCommand(command: string, history: NavigationHistoryLike): void {
  if (command === "browser-backward" && history.canGoBack()) {
    history.goBack();
  } else if (command === "browser-forward" && history.canGoForward()) {
    history.goForward();
  }
}

export type WindowStatePersisterDeps = {
  userDataDir: string;
  getState: () => WindowState;
  delayMs: number;
  save?: typeof saveWindowState;
  onError?: (error: unknown) => void;
  setTimeout?: typeof setTimeout;
  clearTimeout?: typeof clearTimeout;
};

/** Debounces window resize/move events into a single delayed disk write, and
 *  flushes immediately (synchronously) on close so the final state is never
 *  lost to a pending timer. Save errors are swallowed (diagnostics only) —
 *  a failure to persist window position must never block closing the app. */
export function createWindowStatePersister(deps: WindowStatePersisterDeps): {
  schedule(): void;
  flush(): void;
} {
  const save = deps.save ?? saveWindowState;
  const setTimer = deps.setTimeout ?? setTimeout;
  const clearTimer = deps.clearTimeout ?? clearTimeout;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const writeNow = (): void => {
    try {
      save(deps.userDataDir, deps.getState());
    } catch (error) {
      deps.onError?.(error);
    }
  };

  return {
    schedule(): void {
      if (timer) clearTimer(timer);
      timer = setTimer(() => {
        timer = null;
        writeNow();
      }, deps.delayMs);
    },
    flush(): void {
      if (timer) {
        clearTimer(timer);
        timer = null;
      }
      writeNow();
    },
  };
}

/**
 * Application + context menu templates for the desktop shell (STUDIO-104).
 *
 * These are pure builders that return Electron menu templates (plain data) so
 * they can be unit-tested without an Electron runtime. `main.ts` wires them to
 * real `Menu.buildFromTemplate` / `webContents` objects.
 *
 * The default Electron menu ships an Edit menu we don't want; building our own
 * menu here replaces it. Clipboard actions (Copy/Paste/Select All) move into the
 * right-click context menu so removing the Edit menu doesn't lose them.
 */
import type { MenuItemConstructorOptions } from "electron";

/** The navigation surface the menus drive — a thin seam over a webContents'
 *  navigationHistory so the builders stay Electron-free and testable. */
export interface NavTarget {
  canGoBack(): boolean;
  canGoForward(): boolean;
  goBack(): void;
  goForward(): void;
  reload(): void;
}

/** Editing context for a right-click, sourced from the `context-menu` event's
 *  params (`isEditable`, `editFlags.canCopy`, `editFlags.canPaste`). */
export interface EditContext {
  isEditable: boolean;
  canCopy: boolean;
  canPaste: boolean;
}

/**
 * Right-click context menu: navigation always present; clipboard items appear
 * only when relevant (a selection to copy, or an editable field to paste into).
 * Back/Forward reflect live nav state — this template is rebuilt per right-click.
 */
export function buildContextMenuTemplate(
  nav: NavTarget,
  ctx: EditContext,
): MenuItemConstructorOptions[] {
  const template: MenuItemConstructorOptions[] = [
    { label: "Back", enabled: nav.canGoBack(), click: () => nav.goBack() },
    { label: "Forward", enabled: nav.canGoForward(), click: () => nav.goForward() },
    { label: "Reload", click: () => nav.reload() },
  ];

  const clipboard: MenuItemConstructorOptions[] = [];
  if (ctx.canCopy) {
    clipboard.push({ role: "copy" });
  }
  if (ctx.isEditable) {
    clipboard.push({ role: "paste", enabled: ctx.canPaste });
    clipboard.push({ role: "selectAll" });
  }
  if (clipboard.length > 0) {
    template.push({ type: "separator" }, ...clipboard);
  }

  return template;
}

/**
 * Custom application menu bar — intentionally omits the Edit menu. Back/Forward
 * are always enabled (the click handlers guard on `canGoBack/Forward`) so the
 * app menu doesn't need rebuilding on every navigation; the context menu carries
 * the accurate enable/disable state.
 */
export function buildApplicationMenuTemplate(
  nav: NavTarget,
  opts: { isMac: boolean; onRegenerateKey?: () => void },
): MenuItemConstructorOptions[] {
  const template: MenuItemConstructorOptions[] = [];

  if (opts.isMac) {
    template.push({ role: "appMenu" });
  }

  const fileSubmenu: MenuItemConstructorOptions[] = [];
  if (opts.onRegenerateKey) {
    fileSubmenu.push(
      { label: "Regenerate Encryption Key…", click: () => opts.onRegenerateKey?.() },
      { type: "separator" },
    );
  }
  fileSubmenu.push(opts.isMac ? { role: "close" } : { role: "quit" });
  template.push({ label: "File", submenu: fileSubmenu });

  template.push({
    label: "Navigate",
    submenu: [
      {
        label: "Back",
        accelerator: "Alt+Left",
        click: () => {
          if (nav.canGoBack()) nav.goBack();
        },
      },
      {
        label: "Forward",
        accelerator: "Alt+Right",
        click: () => {
          if (nav.canGoForward()) nav.goForward();
        },
      },
      { type: "separator" },
      { label: "Reload", accelerator: "CmdOrCtrl+R", click: () => nav.reload() },
    ],
  });

  template.push({
    label: "View",
    submenu: [
      { role: "resetZoom" },
      { role: "zoomIn" },
      { role: "zoomOut" },
      { type: "separator" },
      { role: "togglefullscreen" },
      { role: "toggleDevTools" },
    ],
  });

  template.push({ role: "windowMenu" });

  return template;
}

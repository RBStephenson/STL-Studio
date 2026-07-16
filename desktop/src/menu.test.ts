import { describe, expect, it, vi } from "vitest";

import {
  buildApplicationMenuTemplate,
  buildContextMenuTemplate,
} from "./menu";
import type { EditContext, NavTarget } from "./menu";

function makeNav(overrides: Partial<NavTarget> = {}): {
  nav: NavTarget;
  calls: { back: number; forward: number; reload: number };
} {
  const calls = { back: 0, forward: 0, reload: 0 };
  const nav: NavTarget = {
    canGoBack: () => true,
    canGoForward: () => true,
    goBack: () => {
      calls.back += 1;
    },
    goForward: () => {
      calls.forward += 1;
    },
    reload: () => {
      calls.reload += 1;
    },
    ...overrides,
  };
  return { nav, calls };
}

const noEdit: EditContext = { isEditable: false, canCopy: false, canPaste: false };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const labels = (t: any[]) => t.map((i) => i.label ?? i.role ?? i.type);

describe("buildContextMenuTemplate", () => {
  it("always offers Back/Forward/Reload", () => {
    const { nav } = makeNav();
    const t = buildContextMenuTemplate(nav, noEdit);
    expect(labels(t)).toEqual(["Back", "Forward", "Reload"]);
  });

  it("disables Back/Forward when navigation isn't possible", () => {
    const { nav } = makeNav({ canGoBack: () => false, canGoForward: () => false });
    const t = buildContextMenuTemplate(nav, noEdit);
    expect(t[0]).toMatchObject({ label: "Back", enabled: false });
    expect(t[1]).toMatchObject({ label: "Forward", enabled: false });
  });

  it("wires Back/Forward/Reload to the nav target", () => {
    const { nav, calls } = makeNav();
    const t = buildContextMenuTemplate(nav, noEdit);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (t[0] as any).click();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (t[1] as any).click();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (t[2] as any).click();
    expect(calls).toEqual({ back: 1, forward: 1, reload: 1 });
  });

  it("adds Copy when there's a selection", () => {
    const { nav } = makeNav();
    const t = buildContextMenuTemplate(nav, { isEditable: false, canCopy: true, canPaste: false });
    const roles = t.map((i) => i.role).filter(Boolean);
    expect(roles).toContain("copy");
    expect(roles).not.toContain("paste");
  });

  it("adds Paste + Select All only in an editable field", () => {
    const { nav } = makeNav();
    const t = buildContextMenuTemplate(nav, { isEditable: true, canCopy: true, canPaste: true });
    const roles = t.map((i) => i.role).filter(Boolean);
    expect(roles).toEqual(expect.arrayContaining(["copy", "paste", "selectAll"]));
  });
});

describe("buildApplicationMenuTemplate", () => {
  it("omits the Edit menu", () => {
    const { nav } = makeNav();
    const t = buildApplicationMenuTemplate(nav, { isMac: false });
    expect(labels(t)).not.toContain("Edit");
  });

  it("includes a Navigate menu with Back/Forward/Reload", () => {
    const { nav } = makeNav();
    const t = buildApplicationMenuTemplate(nav, { isMac: false });
    const navMenu = t.find((i) => i.label === "Navigate");
    expect(navMenu).toBeDefined();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const sub = (navMenu as any).submenu as any[];
    expect(labels(sub)).toEqual(["Back", "Forward", "separator", "Reload"]);
  });

  it("Back/Forward are always enabled but guard on nav state", () => {
    const { nav, calls } = makeNav({ canGoBack: () => false, canGoForward: () => true });
    const t = buildApplicationMenuTemplate(nav, { isMac: false });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const sub = (t.find((i) => i.label === "Navigate") as any).submenu as any[];
    sub[0].click(); // Back — canGoBack false, must no-op
    sub[1].click(); // Forward — canGoForward true, must fire
    expect(calls.back).toBe(0);
    expect(calls.forward).toBe(1);
  });

  it("starts with the macOS app menu only on macOS", () => {
    const { nav } = makeNav();
    expect(buildApplicationMenuTemplate(nav, { isMac: false })[0].role).not.toBe("appMenu");
    expect(buildApplicationMenuTemplate(nav, { isMac: true })[0].role).toBe("appMenu");
  });

  it("wires the manual update check from the Help menu", () => {
    const { nav } = makeNav();
    const onCheckForUpdates = vi.fn();
    const t = buildApplicationMenuTemplate(nav, { isMac: false, onCheckForUpdates });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const help = (t.find((i) => i.label === "Help") as any).submenu as any[];
    help[0].click();
    expect(onCheckForUpdates).toHaveBeenCalledOnce();
  });
});

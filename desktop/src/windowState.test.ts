import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  DEFAULT_WINDOW_BOUNDS,
  boundsIntersectAnyDisplay,
  readWindowState,
  saveWindowState,
  windowStatePath,
} from "./windowState";
import type { WindowDisplay } from "./windowState";

const displays: WindowDisplay[] = [
  { workArea: { x: 0, y: 0, width: 1920, height: 1080 } },
];

const tempDirs: string[] = [];

function makeUserDataDir(): string {
  const dir = mkdtempSync(join(tmpdir(), "stl-window-state-"));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("readWindowState", () => {
  it("falls back when no state file exists", () => {
    const state = readWindowState(makeUserDataDir(), displays);
    expect(state).toEqual({
      bounds: DEFAULT_WINDOW_BOUNDS,
      isMaximized: false,
    });
  });

  it("falls back when the state file is corrupt", () => {
    const dir = makeUserDataDir();
    writeFileSync(windowStatePath(dir), "{ nope", "utf8");

    const state = readWindowState(dir, displays);
    expect(state.bounds).toEqual(DEFAULT_WINDOW_BOUNDS);
  });

  it("restores valid bounds and maximized state", () => {
    const dir = makeUserDataDir();
    writeFileSync(
      windowStatePath(dir),
      JSON.stringify({
        bounds: { x: 50, y: 60, width: 1400, height: 900 },
        isMaximized: true,
      }),
      "utf8",
    );

    expect(readWindowState(dir, displays)).toEqual({
      bounds: { x: 50, y: 60, width: 1400, height: 900 },
      isMaximized: true,
    });
  });

  it("falls back when saved bounds are offscreen", () => {
    const dir = makeUserDataDir();
    writeFileSync(
      windowStatePath(dir),
      JSON.stringify({
        bounds: { x: 5000, y: 5000, width: 900, height: 700 },
        isMaximized: false,
      }),
      "utf8",
    );

    const state = readWindowState(dir, displays);
    expect(state).toEqual({
      bounds: DEFAULT_WINDOW_BOUNDS,
      isMaximized: false,
    });
  });
});

describe("saveWindowState", () => {
  it("writes normalized bounds and maximized state", () => {
    const dir = makeUserDataDir();

    saveWindowState(dir, {
      bounds: { x: 12.4, y: 45.6, width: 1280.2, height: 800.8 },
      isMaximized: true,
    });

    expect(JSON.parse(readFileSync(windowStatePath(dir), "utf8"))).toEqual({
      bounds: { x: 12, y: 46, width: 1280, height: 801 },
      isMaximized: true,
    });
  });

  it("does not write invalid state", () => {
    const dir = makeUserDataDir();

    saveWindowState(dir, {
      bounds: { width: 100, height: 100 },
      isMaximized: false,
    });

    expect(() => readFileSync(windowStatePath(dir), "utf8")).toThrow();
  });
});

describe("boundsIntersectAnyDisplay", () => {
  it("accepts bounds that overlap a display work area", () => {
    expect(
      boundsIntersectAnyDisplay(
        { x: -100, y: 100, width: 300, height: 300 },
        displays,
      ),
    ).toBe(true);
  });

  it("rejects bounds that do not overlap any display work area", () => {
    expect(
      boundsIntersectAnyDisplay(
        { x: -500, y: -500, width: 200, height: 200 },
        displays,
      ),
    ).toBe(false);
  });
});

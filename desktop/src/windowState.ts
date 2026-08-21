import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const WINDOW_STATE_FILE = "window-state.json";
export const DEFAULT_WINDOW_BOUNDS: WindowBounds = {
  width: 1280,
  height: 800,
};

const MIN_WINDOW_WIDTH = 640;
const MIN_WINDOW_HEIGHT = 480;

export const DEFAULT_ZOOM_FACTOR = 1.0;
const MIN_ZOOM_FACTOR = 0.25;
const MAX_ZOOM_FACTOR = 5.0;

export interface WindowBounds {
  x?: number;
  y?: number;
  width: number;
  height: number;
}

export interface WindowDisplay {
  workArea: WindowBounds & { x: number; y: number };
}

export interface WindowState {
  bounds: WindowBounds;
  isMaximized: boolean;
  zoomFactor: number;
}

export function windowStatePath(userDataDir: string): string {
  return join(userDataDir, WINDOW_STATE_FILE);
}

export function readWindowState(
  userDataDir: string,
  displays: WindowDisplay[],
): WindowState {
  const fallback: WindowState = {
    bounds: { ...DEFAULT_WINDOW_BOUNDS },
    isMaximized: false,
    zoomFactor: DEFAULT_ZOOM_FACTOR,
  };

  try {
    const parsed: unknown = JSON.parse(
      readFileSync(windowStatePath(userDataDir), "utf8"),
    );
    const state = normalizeWindowState(parsed);
    if (!state) {
      return fallback;
    }
    if (!boundsIntersectAnyDisplay(state.bounds, displays)) {
      // Bounds are unusable (offscreen/stale display layout), but the zoom
      // preference is unrelated to window position — keep it.
      return { ...fallback, zoomFactor: state.zoomFactor };
    }
    return state;
  } catch {
    return fallback;
  }
}

export function saveWindowState(
  userDataDir: string,
  state: WindowState,
): void {
  const normalized = normalizeWindowState(state);
  if (!normalized) {
    return;
  }
  writeFileSync(
    windowStatePath(userDataDir),
    `${JSON.stringify(normalized, null, 2)}\n`,
    "utf8",
  );
}

export function boundsIntersectAnyDisplay(
  bounds: WindowBounds,
  displays: WindowDisplay[],
): boolean {
  if (bounds.x === undefined || bounds.y === undefined) {
    return true;
  }
  const positionedBounds = { ...bounds, x: bounds.x, y: bounds.y };
  return displays.some((display) => (
    rectanglesIntersect(positionedBounds, display.workArea)
  ));
}

function normalizeWindowState(value: unknown): WindowState | null {
  if (!isRecord(value)) {
    return null;
  }

  const boundsValue = value.bounds;
  if (!isRecord(boundsValue)) {
    return null;
  }

  const width = normalizeDimension(boundsValue.width, MIN_WINDOW_WIDTH);
  const height = normalizeDimension(boundsValue.height, MIN_WINDOW_HEIGHT);
  if (width === null || height === null) {
    return null;
  }

  const bounds: WindowBounds = { width, height };
  const x = normalizeCoordinate(boundsValue.x);
  const y = normalizeCoordinate(boundsValue.y);
  if (x !== null && y !== null) {
    bounds.x = x;
    bounds.y = y;
  }

  return {
    bounds,
    isMaximized: value.isMaximized === true,
    zoomFactor: normalizeZoomFactor(value.zoomFactor),
  };
}

function normalizeDimension(value: unknown, minimum: number): number | null {
  if (!Number.isFinite(value) || typeof value !== "number" || value < minimum) {
    return null;
  }
  return Math.round(value);
}

/** A corrupt or absurd zoom value falls back to the default rather than
 *  invalidating the whole saved state (unlike bounds, an out-of-range zoom
 *  isn't fatal to usability). Missing field (older state files) also falls
 *  back here, giving backward compatibility for free. */
function normalizeZoomFactor(value: unknown): number {
  if (
    typeof value !== "number"
    || !Number.isFinite(value)
    || value < MIN_ZOOM_FACTOR
    || value > MAX_ZOOM_FACTOR
  ) {
    return DEFAULT_ZOOM_FACTOR;
  }
  return value;
}

function normalizeCoordinate(value: unknown): number | null {
  if (!Number.isFinite(value) || typeof value !== "number") {
    return null;
  }
  return Math.round(value);
}

function rectanglesIntersect(
  first: WindowBounds & { x: number; y: number },
  second: WindowBounds & { x: number; y: number },
): boolean {
  return (
    first.x < second.x + second.width
    && first.x + first.width > second.x
    && first.y < second.y + second.height
    && first.y + first.height > second.y
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

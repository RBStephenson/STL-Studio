import { isAbsolute } from "node:path";

export interface UserDataPathTarget {
  setPath(name: "userData", path: string): void;
}

/** Apply the explicit profile used by installed-app automation before Electron
 * acquires its single-instance lock. Normal launches do not set this variable. */
export function applyUserDataOverride(
  target: UserDataPathTarget,
  value: string | undefined,
): string | null {
  const path = value?.trim();
  if (!path) return null;
  if (!isAbsolute(path)) {
    throw new Error("STL_STUDIO_USER_DATA_DIR must be an absolute path");
  }
  target.setPath("userData", path);
  return path;
}

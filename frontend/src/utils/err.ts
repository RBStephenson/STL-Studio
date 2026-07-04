/** Extract a human-readable message from an unknown catch value. */
export function errMsg(e: unknown): string | undefined {
  if (e instanceof Error) return e.message;
  if (typeof e === "string") return e;
  return undefined;
}

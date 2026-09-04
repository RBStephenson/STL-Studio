import { useCallback, useEffect, useRef } from "react";

/**
 * Returns a scheduler that runs `fn` on the next tick and cancels it on unmount.
 *
 * Deferring by one tick is how a newly revealed input gets focused: the ref is
 * only attached after React commits, so reaching for it in the same handler
 * finds null. Those callbacks are null-safe and same-tick, so they were never
 * the bug STUDIO-349 is about — but they are the same *shape* the lint rule
 * flags, and exempting seven of them with inline disables would blunt a rule
 * whose whole value is being absolute. One cancelling helper is cheaper.
 *
 * One pending call at a time: scheduling again replaces the previous one, which
 * matches every current use (focus the thing that was just revealed).
 */
export function useNextTick() {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  return useCallback((fn: () => void) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(fn, 0);
  }, []);
}

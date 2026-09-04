import { useEffect, useRef, useState } from "react";

export type FlashType = "ok" | "err";

export function useSettingsFlash() {
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // One timer per channel, not one shared timer: a success flash followed by an
  // error flash used to leave two independent clears pending, and collapsing
  // them into a single ref would strand the success message on screen.
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (successTimerRef.current) clearTimeout(successTimerRef.current);
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    },
    [],
  );

  const flash = (msg: string, type: FlashType) => {
    if (type === "ok") {
      if (successTimerRef.current) clearTimeout(successTimerRef.current);
      setSuccess(msg);
      successTimerRef.current = setTimeout(() => setSuccess(null), 3000);
    } else {
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
      setError(msg);
      errorTimerRef.current = setTimeout(() => setError(null), 4000);
    }
  };

  return { success, error, flash };
}

import { useState } from "react";

export type FlashType = "ok" | "err";

export function useSettingsFlash() {
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const flash = (msg: string, type: FlashType) => {
    if (type === "ok") {
      setSuccess(msg);
      setTimeout(() => setSuccess(null), 3000);
    } else {
      setError(msg);
      setTimeout(() => setError(null), 4000);
    }
  };

  return { success, error, flash };
}

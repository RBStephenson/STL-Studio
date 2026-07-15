import { useEffect, useState } from "react";

export const STORAGE_RECOVERED_EVENT = "stl-studio:storage-recovered";

export function useStorageRecoverySignal(): number {
  const [signal, setSignal] = useState(0);
  useEffect(() => {
    const recovered = () => setSignal((value) => value + 1);
    window.addEventListener(STORAGE_RECOVERED_EVENT, recovered);
    return () => window.removeEventListener(STORAGE_RECOVERED_EVENT, recovered);
  }, []);
  return signal;
}

export function withStorageRecoverySignal(url: string, signal: number): string {
  if (signal === 0 || !url.startsWith("/api/files/image?")) return url;
  return `${url}&storage_recovery=${signal}`;
}

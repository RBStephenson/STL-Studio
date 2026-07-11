import { useState, useEffect, useRef } from "react";
import { api, ScanStatus } from "../api/client";
import { useToast } from "../context/ToastContext";
import { errMsg } from "../utils/err";

/** Shared scan trigger/poll logic (STUDIO-166) — used by every "start a scan"
 *  control so they all reflect the same running/idle state instead of each
 *  reimplementing (or omitting) the polling loop. */
export function useScanStatus(onScanComplete?: () => void) {
  const [status, setStatus] = useState<ScanStatus | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const wasRunningRef = useRef(false);
  const { toast } = useToast();

  useEffect(() => {
    api.scan.status().then(setStatus).catch(() => {});
  }, []);

  useEffect(() => {
    if (status?.running) {
      wasRunningRef.current = true;
      setCancelling(false);
    } else {
      // running → idle: announce the backend's completion summary (#283).
      // `status.message` carries "done — N models, M files[, P removed]" (#223).
      if (wasRunningRef.current) {
        wasRunningRef.current = false;
        toast(status?.message || "Scan complete.", "success");
        onScanComplete?.();
      }
      return;
    }
    const interval = setInterval(() => {
      api.scan.status().then(setStatus).catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
  }, [status?.running, status?.message, onScanComplete, toast]);

  const start = async () => {
    try {
      const s = await api.scan.start();
      setStatus(s);
    } catch (e) {
      toast(errMsg(e) || "Couldn't start the scan — try again.", "error");
    }
  };

  const cancel = async () => {
    setCancelling(true);
    try {
      await api.scan.cancel();
    } catch {
      setCancelling(false);
    }
  };

  return { status, cancelling, start, cancel };
}

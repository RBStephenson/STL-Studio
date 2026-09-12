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

  // The library is unusable for writes while EITHER is true (STUDIO-450).
  // Polling on `running` alone stopped the moment a cancelled scan reached its
  // terminal state, which is well before the worker releases the write lock —
  // so the UI went idle, invited the next action, and that action got a 409.
  const active = !!(status?.running || status?.busy);

  useEffect(() => {
    api.scan.status().then(setStatus).catch(() => {});
  }, []);

  useEffect(() => {
    if (status?.running) {
      wasRunningRef.current = true;
      setCancelling(false);
    }
    if (!active) {
      // A scan ran and the library is writable again: announce the backend's
      // completion summary (#283). `status.message` carries "done — N models,
      // M files[, P removed]" (#223). Gated on wasRunningRef so a reorganize
      // apply — which makes the library busy without any scan — never reports
      // itself as a finished scan, and deferred until `busy` clears so
      // onScanComplete refetches settled data rather than mid-regroup rows.
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
  }, [active, status?.running, status?.message, onScanComplete, toast]);

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

  /** True while the write lock is held but no scan job is running — a cancelled
   *  scan unwinding, or a reorganize/install holding the library. Controls that
   *  would write must stay disabled here even though nothing is "scanning". */
  const finishing = !!(status?.busy && !status?.running);

  return { status, cancelling, finishing, busy: active, start, cancel };
}

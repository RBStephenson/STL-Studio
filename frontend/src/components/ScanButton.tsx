import { useState, useEffect, useRef } from "react";
import { RefreshCw, Square } from "lucide-react";
import { api, ScanStatus } from "../api/client";
import { useToast } from "../context/ToastContext";
import { errMsg } from "../utils/err";

interface Props {
  onScanComplete?: () => void;
}

export default function ScanButton({ onScanComplete }: Props) {
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

  return (
    <div className="flex items-center gap-3">
      {status?.running && (
        <span className="text-xs text-text-secondary animate-pulse">
          {cancelling ? "Cancelling…" : `Scanning… ${status.models_found ?? 0} models`}
        </span>
      )}
      {status?.running ? (
        <button
          onClick={cancel}
          disabled={cancelling}
          title="Cancel scan"
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-panel-secondary hover:bg-border disabled:opacity-40 disabled:cursor-not-allowed border border-border-divider text-sm text-text-primary-alt transition-colors"
        >
          <Square size={13} fill="currentColor" />
          {cancelling ? "Cancelling…" : "Cancel"}
        </button>
      ) : (
        <button
          onClick={start}
          className="btn-cta flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold text-white"
        >
          <RefreshCw size={14} />
          Scan Library
        </button>
      )}
    </div>
  );
}

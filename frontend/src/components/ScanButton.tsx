import { RefreshCw, Square } from "lucide-react";
import { useScanStatus } from "../hooks/useScanStatus";

interface Props {
  onScanComplete?: () => void;
}

export default function ScanButton({ onScanComplete }: Props) {
  const { status, cancelling, finishing, start, cancel } = useScanStatus(onScanComplete);

  return (
    <div className="flex items-center gap-3">
      {(status?.running || finishing) && (
        <span className="text-xs text-text-secondary animate-pulse">
          {finishing
            ? // A cancelled scan is unwinding; anything else holding the lock is
              // a reorganize or install, which "finishing up" would misdescribe.
              status?.cancelled
              ? "Finishing up…"
              : "Library busy…"
            : cancelling
              ? "Cancelling…"
              : `Scanning… ${status?.models_found ?? 0} models`}
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
          // The library is still locked by a cancelled scan's unwind, a
          // reorganize apply/undo, or an install (STUDIO-450). Offering Scan
          // here is the lie this ticket is about: the click 409s.
          disabled={finishing}
          title={finishing ? "The library is busy — try again in a moment" : "Scan library"}
          className="btn-cta flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <RefreshCw size={14} />
          Scan Library
        </button>
      )}
    </div>
  );
}

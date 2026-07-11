import { RefreshCw, Square } from "lucide-react";
import { useScanStatus } from "../hooks/useScanStatus";

interface Props {
  onScanComplete?: () => void;
}

export default function ScanButton({ onScanComplete }: Props) {
  const { status, cancelling, start, cancel } = useScanStatus(onScanComplete);

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

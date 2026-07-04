// Print-status state + handlers for ModelDetail: the current print status and
// print count, with cycle/clear actions. Extracted from ModelDetail.tsx
// (STUDIO-63 P3) — behavior-preserving. Optimistic-local with revert on
// failure, matching the original inline logic.

import { useState, useEffect } from "react";
import { api, PrintStatus, ModelDetail as ModelDetailType } from "../../../api/client";
import { useToast } from "../../../context/ToastContext";

export interface UsePrintStatus {
  printStatus: PrintStatus;
  printCount: number;
  cyclePrintStatus: () => Promise<void>;
  clearPrintStatus: () => Promise<void>;
}

export function usePrintStatus(model: ModelDetailType | null, modelId: number | undefined): UsePrintStatus {
  const { toast } = useToast();
  const [printStatus, setPrintStatus] = useState<PrintStatus>("none");
  const [printCount, setPrintCount] = useState(0);

  // Sync local state from the loaded model.
  useEffect(() => {
    if (model) {
      setPrintStatus(model.print_status ?? "none");
      setPrintCount(model.print_count ?? 0);
    }
  }, [model]);

  const cyclePrintStatus = async () => {
    const { PRINT_STATUS_CYCLE } = await import("../../../api/client");
    const idx = PRINT_STATUS_CYCLE.indexOf(printStatus);
    const next = PRINT_STATUS_CYCLE[(idx + 1) % PRINT_STATUS_CYCLE.length];
    const prev = printStatus;
    const prevCount = printCount;
    setPrintStatus(next);
    try {
      const res = await api.models.setPrintStatus(Number(modelId), next);
      setPrintCount(res.print_count);
    } catch {
      setPrintStatus(prev);
      setPrintCount(prevCount);
      toast("Couldn't update print status — try again.", "error");
    }
  };

  const clearPrintStatus = async () => {
    const prev = printStatus;
    const prevCount = printCount;
    setPrintStatus("none");
    try {
      const res = await api.models.setPrintStatus(Number(modelId), "none");
      setPrintCount(res.print_count);
    } catch {
      setPrintStatus(prev);
      setPrintCount(prevCount);
      toast("Couldn't clear print status — try again.", "error");
    }
  };

  return { printStatus, printCount, cyclePrintStatus, clearPrintStatus };
}

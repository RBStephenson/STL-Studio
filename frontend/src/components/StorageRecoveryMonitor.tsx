import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import { useToast } from "../context/ToastContext";
import { STORAGE_RECOVERED_EVENT } from "../hooks/useStorageRecoverySignal";

const CHECK_WHILE_UNAVAILABLE_MS = 5_000;
const CHECK_WHILE_AVAILABLE_MS = 30_000;

export function storageRecoveryTransition(before: boolean | undefined, available: boolean) {
  if (before === undefined && !available) return { message: "Loading previews from external storage…", type: "info" as const, recovered: false };
  if (before === true && !available) return { message: "Some library files are temporarily unavailable. Your catalog is safe.", type: "info" as const, recovered: false };
  if (before === false && available) return { message: "External storage is available again.", type: "success" as const, recovered: true };
  return null;
}

export default function StorageRecoveryMonitor() {
  const { settings } = useAppSettings();
  const { toast } = useToast();
  const previous = useRef<boolean | undefined>(undefined);
  const query = useQuery({
    queryKey: ["settings", "storage-recovery"],
    queryFn: () => api.settings.storageRecovery(),
    enabled: settings.storage_recovery_enabled,
    retry: false,
    refetchInterval: (q) => q.state.data?.all_available === false
      ? CHECK_WHILE_UNAVAILABLE_MS
      : CHECK_WHILE_AVAILABLE_MS,
  });

  useEffect(() => {
    if (!settings.storage_recovery_enabled) {
      previous.current = undefined;
      return;
    }
    const status = query.data;
    if (!status || status.enabled_libraries === 0) return;
    const before = previous.current;
    previous.current = status.all_available;

    const transition = storageRecoveryTransition(before, status.all_available);
    if (transition) toast(transition.message, transition.type);
    if (transition?.recovered) {
      window.dispatchEvent(new Event(STORAGE_RECOVERED_EVENT));
    }
  }, [query.data, settings.storage_recovery_enabled, toast]);

  return null;
}

import { useState } from "react";
import { RefreshCw, Loader2 } from "lucide-react";
import { useToast } from "../context/ToastContext";

interface RefreshResult {
  candidates: number;
  refreshed: number;
  failed: number;
}

interface Props {
  /** Limit the refresh to one creator. Omit for a library-wide refresh. */
  creatorId?: number;
  /** Short label for the scope, used in the confirm prompt ("Refresh Acme?"). */
  scopeLabel: string;
  /** Render compact (icon + short text) for inline use on a card/header. */
  compact?: boolean;
  /** Called after a successful refresh so the parent can reload counts. */
  onDone?: (result: RefreshResult) => void;
}

// Re-enrich only touches listings older than this many days (or never fetched);
// "All" drops the filter and refreshes every model that has a source URL.
const STALE_OPTIONS: { label: string; days: number | null }[] = [
  { label: "Older than 7 days", days: 7 },
  { label: "Older than 30 days", days: 30 },
  { label: "Older than 90 days", days: 90 },
  { label: "All", days: null },
];

export default function RefreshEnrich({ creatorId, scopeLabel, compact, onDone }: Props) {
  const [staleDays, setStaleDays] = useState<number | null>(30);
  const [running, setRunning] = useState(false);
  const { toast } = useToast();

  const run = async () => {
    const scopeText = staleDays === null
      ? "every model with a stored source URL"
      : `models not refreshed in ${staleDays} days`;
    // A refresh overwrites aggressively, so confirm before clobbering edits.
    if (!window.confirm(
      `Re-fetch storefront metadata for ${scopeText} in ${scopeLabel}?\n\n` +
      "This overwrites titles, thumbnails, and descriptions with the latest " +
      "listing data. Tags are merged, not replaced."
    )) return;

    setRunning(true);
    try {
      const r = await fetch("/api/enrich/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(creatorId !== undefined ? { creator_id: creatorId } : {}),
          ...(staleDays !== null ? { stale_days: staleDays } : {}),
        }),
      });
      if (!r.ok) throw new Error("Refresh failed");
      const result: RefreshResult = await r.json();

      if (result.candidates === 0) {
        toast("Nothing to refresh — no matching models with a source URL.", "info");
      } else {
        toast(
          `Refreshed ${result.refreshed} of ${result.candidates} model` +
          `${result.candidates === 1 ? "" : "s"}` +
          (result.failed > 0 ? ` (${result.failed} couldn't be fetched)` : "") + ".",
          "success"
        );
      }
      onDone?.(result);
    } catch (e: any) {
      toast(e.message ?? "Refresh failed", "error");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <select
        aria-label="Refresh staleness"
        value={staleDays ?? "all"}
        onChange={(e) => setStaleDays(e.target.value === "all" ? null : Number(e.target.value))}
        disabled={running}
        className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-indigo-500 disabled:opacity-40"
      >
        {STALE_OPTIONS.map((o) => (
          <option key={o.label} value={o.days ?? "all"}>{o.label}</option>
        ))}
      </select>
      <button
        onClick={run}
        disabled={running}
        title={`Re-fetch storefront metadata for ${scopeLabel}`}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-xs text-gray-200 transition-colors"
      >
        {running
          ? <Loader2 size={13} className="animate-spin" />
          : <RefreshCw size={13} />}
        {compact ? "Refresh" : "Refresh metadata"}
      </button>
    </div>
  );
}

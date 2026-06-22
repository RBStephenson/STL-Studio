import { useEffect, useRef, useState } from "react";
import { FileDown, Layers, ChevronDown } from "lucide-react";
import { api, Guide, SeriesExportOptions } from "../../api/client";
import { useToast } from "../../context/ToastContext";

interface Props {
  guide: Guide;
  busy: boolean;
  setBusy: (b: boolean) => void;
}

/**
 * Export menu for the guide reader (#511). Wraps the single-guide PDF export and
 * — when the guide belongs to a series — the series-bundle export, with the
 * per-export reward-stamping controls the backend exposes (#490): cover page,
 * Patreon-exclusive footer (on by default), tier label, watermark (off).
 */
export default function GuideExportMenu({ guide, busy, setBusy }: Props) {
  const { toast } = useToast();
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);

  const [cover, setCover] = useState(true);
  const [footer, setFooter] = useState(true);
  const [tier, setTier] = useState("");
  const [watermark, setWatermark] = useState(false);

  const hasSeries = guide.series_id != null;

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const stamp = (): SeriesExportOptions => {
    const opts: SeriesExportOptions = { footer, watermark };
    if (tier.trim()) opts.tier = tier.trim();
    return opts;
  };

  const run = async (action: () => Promise<void>, failMsg: string) => {
    setBusy(true);
    setOpen(false);
    try {
      await action();
    } catch (e) {
      toast((e as Error)?.message || failMsg, "error");
    } finally {
      setBusy(false);
    }
  };

  const exportGuide = () =>
    run(() => api.painting.guides.exportPdf(guide.id, guide.slug, stamp()),
      "Could not export the PDF.");

  const exportSeries = () =>
    run(() => api.painting.guides.exportSeriesPdf(guide.series_id as number, { ...stamp(), cover }),
      "Could not export the series bundle.");

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        title="Export this guide as a print-ready PDF"
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm px-3 py-1.5 rounded transition-colors disabled:opacity-50"
      >
        <FileDown size={15} /> Export PDF <ChevronDown size={13} />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-1 w-64 bg-gray-900 border border-gray-700 rounded shadow-xl p-3 z-20 text-sm text-gray-200"
        >
          <div className="font-medium text-gray-300 mb-2">Export options</div>

          <label className="flex items-center gap-2 py-1 cursor-pointer">
            <input type="checkbox" checked={footer} onChange={(e) => setFooter(e.target.checked)} />
            <span>Patreon-exclusive footer</span>
          </label>
          <label className="flex items-center gap-2 py-1 cursor-pointer">
            <input type="checkbox" checked={watermark} onChange={(e) => setWatermark(e.target.checked)} />
            <span>Diagonal watermark</span>
          </label>
          {hasSeries && (
            <label className="flex items-center gap-2 py-1 cursor-pointer">
              <input type="checkbox" checked={cover} onChange={(e) => setCover(e.target.checked)} />
              <span>Cover page (series bundle)</span>
            </label>
          )}

          <label className="block mt-2 mb-3">
            <span className="text-xs text-gray-400">Tier label (optional)</span>
            <input
              type="text"
              value={tier}
              onChange={(e) => setTier(e.target.value)}
              placeholder="e.g. Hero Tier"
              className="mt-1 w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm focus:outline-none focus:border-indigo-500"
            />
          </label>

          <button
            onClick={exportGuide}
            disabled={busy}
            role="menuitem"
            className="w-full inline-flex items-center gap-1.5 justify-center bg-gray-800 hover:bg-gray-700 border border-gray-700 px-3 py-1.5 rounded transition-colors disabled:opacity-50"
          >
            <FileDown size={15} /> Export this guide
          </button>
          {hasSeries && (
            <button
              onClick={exportSeries}
              disabled={busy}
              role="menuitem"
              className="w-full mt-2 inline-flex items-center gap-1.5 justify-center bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded transition-colors disabled:opacity-50"
            >
              <Layers size={15} /> Export series bundle
            </button>
          )}
        </div>
      )}
    </div>
  );
}

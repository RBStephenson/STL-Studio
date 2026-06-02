import { useState, useEffect, useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import {
  ChevronLeft, SkipForward, CheckCircle, ExternalLink,
  AlertTriangle, Package, RefreshCw,
} from "lucide-react";
import { api, Model } from "../api/client";
import ScanButton from "../components/ScanButton";

const BATCH_SIZE = 50;

export default function Triage() {
  const [queue, setQueue] = useState<Model[]>([]);
  const [cursor, setCursor] = useState(0);
  const [total, setTotal] = useState(0);
  const [dismissed, setDismissed] = useState(0);
  const [loading, setLoading] = useState(true);
  const [done, setDone] = useState(false);
  const [creators, setCreators] = useState<Map<number, string>>(new Map());
  const skippedIdsRef = useRef<Set<number>>(new Set());

  const loadBatch = useCallback(async (resetSkipped = false) => {
    setLoading(true);
    if (resetSkipped) skippedIdsRef.current = new Set();
    try {
      const [batch, stats] = await Promise.all([
        api.models.list({ needs_review: true, page_size: BATCH_SIZE }),
        api.models.stats(),
      ]);
      setTotal(stats.needs_review);
      const filtered = batch.items.filter(m => !skippedIdsRef.current.has(m.id));
      if (filtered.length === 0 && batch.items.length > 0) {
        // All items in this batch were previously skipped — cycle around
        skippedIdsRef.current = new Set();
        setQueue(batch.items);
        setCursor(0);
      } else if (filtered.length === 0) {
        setDone(true);
      } else {
        setQueue(filtered);
        setCursor(0);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBatch();
    api.models.creators().then(cs =>
      setCreators(new Map(cs.map(c => [c.id, c.name])))
    );
  }, [loadBatch]);

  const current = queue[cursor] ?? null;

  const dismiss = useCallback(async () => {
    if (!current) return;
    await api.models.update(current.id, { needs_review: false });
    setDismissed(d => d + 1);
    setTotal(t => t - 1);
    const next = [...queue];
    next.splice(cursor, 1);
    if (next.length === 0) {
      loadBatch();
    } else {
      setQueue(next);
      if (cursor >= next.length) setCursor(next.length - 1);
    }
  }, [current, queue, cursor, loadBatch]);

  const skip = useCallback(() => {
    if (!current) return;
    skippedIdsRef.current.add(current.id);
    if (cursor + 1 >= queue.length) {
      loadBatch();
    } else {
      setCursor(c => c + 1);
    }
  }, [current, cursor, queue.length, loadBatch]);

  const prev = useCallback(() => {
    setCursor(c => Math.max(0, c - 1));
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "ArrowRight" || e.key === " " || e.key === "Enter") {
        e.preventDefault();
        dismiss();
      } else if (e.key === "s" || e.key === "S" || e.key === "ArrowDown") {
        e.preventDefault();
        skip();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        prev();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [dismiss, skip, prev]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 text-gray-400">
        Loading review queue…
      </div>
    );
  }

  if (done || total === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-96 gap-4 text-gray-400">
        <CheckCircle size={48} className="text-green-500" />
        <p className="text-lg">All caught up — nothing needs review.</p>
        <Link to="/" className="text-indigo-400 hover:underline text-sm">
          Back to Library
        </Link>
      </div>
    );
  }

  const thumbSrc = current
    ? (current.thumbnail_path
        ? api.fileUrl(current.thumbnail_path)
        : current.thumbnail_url ?? null)
    : null;

  const creatorName = current?.creator_id
    ? (creators.get(current.creator_id) ?? "Unknown")
    : "Unknown";

  const totalReviewed = dismissed;
  const totalSeen = totalReviewed + total;
  const progressPct = totalSeen > 0 ? Math.max(2, (totalReviewed / totalSeen) * 100) : 2;

  return (
    <div className="max-w-5xl mx-auto px-6 py-6 flex flex-col gap-5">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-100">Review Queue</h1>
        <div className="flex items-center gap-3">
          <button
            onClick={() => loadBatch()}
            title="Refresh queue"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-800 border border-gray-700 text-sm text-gray-300 hover:bg-gray-700 transition-colors"
          >
            <RefreshCw size={13} />
            Refresh
          </button>
          <ScanButton />
        </div>
      </div>

      {/* Progress header */}
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-2 text-gray-400">
          <AlertTriangle size={14} className="text-yellow-500" />
          <span>
            <span className="text-white font-medium">{total.toLocaleString()}</span> models need review
          </span>
          {dismissed > 0 && (
            <span className="text-green-400 text-xs">
              · {dismissed} cleared this session
            </span>
          )}
        </span>
        <span className="text-xs text-gray-600">
          {cursor + 1} of {queue.length} in batch
        </span>
      </div>

      <div className="w-full bg-gray-800 rounded-full h-1">
        <div
          className="bg-indigo-500 h-1 rounded-full transition-all duration-300"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Main card */}
      {current && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden flex min-h-[400px]">
          {/* Thumbnail */}
          <div className="w-72 shrink-0 bg-gray-950 flex items-center justify-center overflow-hidden">
            {thumbSrc ? (
              <img
                src={thumbSrc}
                alt={current.name}
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="flex flex-col items-center gap-2 text-gray-700">
                <Package size={48} />
                <span className="text-xs">No image</span>
              </div>
            )}
          </div>

          {/* Info */}
          <div className="flex-1 p-6 flex flex-col gap-4 min-w-0">
            <div>
              <p className="text-xs text-gray-500 mb-1">{creatorName}</p>
              <h2 className="text-xl font-semibold text-white leading-snug">
                {current.title || current.name}
              </h2>
              {current.title && current.title !== current.name && (
                <p className="text-sm text-gray-400 mt-0.5">{current.name}</p>
              )}
            </div>

            <p className="text-xs text-gray-600 font-mono break-all leading-relaxed">
              {current.folder_path}
            </p>

            {current.auto_tags?.length > 0 && (
              <div>
                <p className="text-xs text-gray-500 mb-1.5">Detected tags</p>
                <div className="flex flex-wrap gap-1.5">
                  {current.auto_tags.map(tag => (
                    <span
                      key={tag}
                      className="px-2 py-0.5 bg-indigo-950 border border-indigo-800 text-indigo-300 rounded text-xs"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {current.tags?.length > 0 && (
              <div>
                <p className="text-xs text-gray-500 mb-1.5">User tags</p>
                <div className="flex flex-wrap gap-1.5">
                  {current.tags.map(tag => (
                    <span
                      key={tag}
                      className="px-2 py-0.5 bg-gray-800 border border-gray-700 text-gray-300 rounded text-xs"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="mt-auto flex flex-col gap-3">
              <Link
                to={`/models/${current.id}`}
                target="_blank"
                className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-indigo-400 transition-colors w-fit"
              >
                <ExternalLink size={12} />
                Open full detail
              </Link>

              <div className="flex items-center gap-2">
                <button
                  onClick={prev}
                  disabled={cursor === 0}
                  title="Back (←)"
                  className="flex items-center gap-1.5 px-3 py-2 rounded bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-700 disabled:opacity-30 text-sm transition-colors"
                >
                  <ChevronLeft size={15} />
                  Back
                </button>
                <button
                  onClick={skip}
                  title="Skip (S)"
                  className="flex items-center gap-1.5 px-4 py-2 rounded bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-700 text-sm transition-colors"
                >
                  <SkipForward size={15} />
                  Skip
                </button>
                <button
                  onClick={dismiss}
                  title="Looks Good (→ / Space)"
                  className="flex items-center gap-1.5 px-5 py-2 rounded bg-green-700 border border-green-600 text-white hover:bg-green-600 text-sm font-medium transition-colors ml-auto"
                >
                  <CheckCircle size={15} />
                  Looks Good
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Keyboard hints */}
      <div className="flex items-center justify-center gap-6 text-xs text-gray-600">
        {(
          [
            ["→ / Space", "Looks Good"],
            ["S", "Skip"],
            ["←", "Back"],
          ] as [string, string][]
        ).map(([key, label]) => (
          <span key={key} className="flex items-center gap-1.5">
            <kbd className="bg-gray-800 px-1.5 py-0.5 rounded border border-gray-700 font-mono">
              {key}
            </kbd>
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

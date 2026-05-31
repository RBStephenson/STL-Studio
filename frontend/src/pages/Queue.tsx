import { useState, useEffect, useCallback } from "react";
import { Printer, Check, History } from "lucide-react";
import { api, Model } from "../api/client";
import ModelCard from "../components/ModelCard";

export default function Queue() {
  const [queued, setQueued] = useState<Model[]>([]);
  const [printed, setPrinted] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [q, p] = await Promise.all([
        api.models.list({ in_queue: true, sort: "queued_at", group_variants: false, page_size: 200 }),
        api.models.list({ printed: true, sort: "printed_at", group_variants: false, page_size: 60 }),
      ]);
      setQueued(q.items);
      setPrinted(p.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6">
      <div className="flex items-center gap-2 mb-6">
        <Printer size={20} className="text-sky-400" />
        <h1 className="text-2xl font-bold text-gray-100">Print Queue</h1>
        <span className="text-sm text-gray-500 ml-1">({queued.length})</span>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="aspect-square bg-gray-900 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : queued.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-600">
          <Printer size={40} className="mb-3 opacity-40" />
          <p className="text-lg">Nothing queued to print</p>
          <p className="text-sm mt-1">Add models to the queue from any model's card or detail page</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {queued.map((m) => (
            <ModelCard key={m.id} model={m} backTo="/queue" />
          ))}
        </div>
      )}

      {/* Recently printed */}
      {printed.length > 0 && (
        <div className="mt-12">
          <div className="flex items-center gap-2 mb-4 pb-2 border-b border-gray-800">
            <History size={16} className="text-emerald-400" />
            <h2 className="text-lg font-semibold text-gray-200">Recently Printed</h2>
            <span className="text-sm text-gray-500">({printed.length})</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4 opacity-75">
            {printed.map((m) => (
              <div key={m.id} className="relative">
                <ModelCard model={m} backTo="/queue" />
                {m.printed_at && (
                  <span className="absolute top-2 left-2 z-10 flex items-center gap-1 bg-emerald-900/90 text-emerald-300 text-xs px-1.5 py-0.5 rounded font-medium">
                    <Check size={10} />
                    {new Date(m.printed_at).toLocaleDateString()}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Paintbrush, Plus, Upload } from "lucide-react";
import { api, GuideListItem } from "../api/client";
import ImportGuideModal from "../components/guide/ImportGuideModal";

export default function GuidesPage() {
  const [guides, setGuides] = useState<GuideListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const load = useCallback(() => {
    let alive = true;
    api.painting.guides
      .list({ page_size: 200 })
      .then((data) => { if (alive) setGuides(data.items); })
      .catch((e) => { if (alive) setError(e?.message || "Could not load guides."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  useEffect(() => load(), [load]);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <div className="flex items-start justify-between gap-4 mb-1">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <Paintbrush size={22} className="text-indigo-400" />
          Painting Guides
        </h1>
        <div className="flex items-center gap-2">
          <Link
            to="/painting/guides/new"
            title="Create a new guide from scratch"
            className="inline-flex items-center gap-1.5 bg-accent-end hover:bg-accent-start text-white text-sm px-3 py-1.5 rounded transition-colors"
          >
            <Plus size={15} /> New guide
          </Link>
          <button
            onClick={() => setImporting(true)}
            title="Import a guide from an HTML file — it lands as a draft for review"
            className="inline-flex items-center gap-1.5 bg-panel-secondary hover:bg-panel-secondary border border-border text-text-primary-alt text-sm px-3 py-1.5 rounded transition-colors"
          >
            <Upload size={15} /> Import guide
          </button>
        </div>
      </div>
      <p className="text-sm text-text-secondary-alt mb-8">
        Step-by-step painting guides for your models.
      </p>

      {importing && (
        <ImportGuideModal
          onClose={() => setImporting(false)}
          onImported={() => { setImporting(false); load(); }}
        />
      )}

      {error && (
        <p role="alert" className="text-sm text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded px-3 py-2">
          {error}
        </p>
      )}

      {!loading && !error && guides.length === 0 && (
        <div
          className="flex flex-col items-center text-center rounded-[14px] border border-dashed px-8 py-16"
          style={{ borderColor: "#1e2027", background: "#0e0f13" }}
        >
          <div
            className="flex items-center justify-center w-14 h-14 rounded-full mb-4"
            style={{ background: "#26163a" }}
          >
            <Paintbrush size={22} strokeWidth={1.6} style={{ color: "var(--color-status-fuchsia)" }} />
          </div>
          <p className="text-base font-bold text-text-primary-alt mb-2">No painting guides yet</p>
          <p className="text-[13px] leading-relaxed text-text-secondary-alt max-w-[320px] mb-6">
            Guides walk through a model step by step, with paint recipes pulled straight from your shelf.
          </p>
          <Link to="/painting/guides/new" className="btn-cta inline-flex items-center gap-1.5 text-white text-sm px-4 py-2 rounded">
            <Plus size={15} /> New guide
          </Link>
        </div>
      )}

      {guides.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2">
          {guides.map((g) => (
            <li key={g.id}>
              <Link
                to={`/painting/guides/${g.id}`}
                className="block bg-panel border border-border-subtle rounded-lg px-4 py-3 hover:border-indigo-600 transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-text-primary">{g.title}</span>
                  {g.status !== "published" && (
                    <span className="text-[10px] uppercase tracking-wide text-amber-400 border border-amber-900/60 rounded px-1.5 py-0.5">
                      {g.status}
                    </span>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary-alt">
                  {g.scale && <span>{g.scale}</span>}
                  {g.franchise && <span>· {g.franchise}</span>}
                  {g.technique_tags.slice(0, 4).map((t) => (
                    <span key={t} className="text-text-muted">#{t}</span>
                  ))}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

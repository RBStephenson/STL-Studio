import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Paintbrush } from "lucide-react";
import { api, GuideListItem } from "../api/client";

export default function GuidesPage() {
  const [guides, setGuides] = useState<GuideListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.painting.guides
      .list({ page_size: 200 })
      .then((data) => { if (alive) setGuides(data.items); })
      .catch((e) => { if (alive) setError(e?.message || "Could not load guides."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="flex items-center gap-2 text-2xl font-bold text-white mb-1">
        <Paintbrush size={22} className="text-indigo-400" />
        Painting Guides
      </h1>
      <p className="text-sm text-gray-500 mb-8">
        Step-by-step painting guides for your models.
      </p>

      {error && (
        <p role="alert" className="text-sm text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded px-3 py-2">
          {error}
        </p>
      )}

      {!loading && !error && guides.length === 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg px-6 py-12 text-center">
          <p className="text-sm text-gray-400 mb-1">No guides yet</p>
          <p className="text-xs text-gray-600">
            Guides you create or import will appear here, with color recipes, techniques, and printable exports.
          </p>
        </div>
      )}

      {guides.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2">
          {guides.map((g) => (
            <li key={g.id}>
              <Link
                to={`/painting/guides/${g.id}`}
                className="block bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 hover:border-indigo-600 transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-gray-100">{g.title}</span>
                  {g.status !== "published" && (
                    <span className="text-[10px] uppercase tracking-wide text-amber-400 border border-amber-900/60 rounded px-1.5 py-0.5">
                      {g.status}
                    </span>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500">
                  {g.scale && <span>{g.scale}</span>}
                  {g.franchise && <span>· {g.franchise}</span>}
                  {g.technique_tags.slice(0, 4).map((t) => (
                    <span key={t} className="text-gray-600">#{t}</span>
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

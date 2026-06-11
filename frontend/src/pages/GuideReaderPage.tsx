import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Printer } from "lucide-react";
import { api, Guide } from "../api/client";
import GuideReader from "../components/guide/GuideReader";
import ModelLink from "../components/guide/ModelLink";

export default function GuideReaderPage() {
  const { id } = useParams<{ id: string }>();
  const [guide, setGuide] = useState<Guide | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    api.painting.guides
      .get(Number(id))
      .then((g) => { if (alive) setGuide(g); })
      .catch((e) => { if (alive) setError(e?.message || "Could not load this guide."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [id]);

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 pt-4 flex items-center justify-between print:hidden">
        <div className="flex items-center gap-4">
          <Link to="/painting/guides" className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300">
            <ArrowLeft size={14} /> All guides
          </Link>
          {guide?.model_id != null && <ModelLink modelId={guide.model_id} />}
        </div>
        {guide && (
          <button
            onClick={() => window.print()}
            title="Print this guide — every tab and sub-tab expands into one document"
            className="inline-flex items-center gap-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm px-3 py-1.5 rounded transition-colors"
          >
            <Printer size={15} /> Print
          </button>
        )}
      </div>

      {loading && <p className="max-w-5xl mx-auto px-4 py-8 text-sm text-gray-500">Loading…</p>}
      {error && (
        <p role="alert" className="max-w-5xl mx-auto px-4 py-8 text-sm text-rose-400">{error}</p>
      )}
      {guide && <GuideReader guide={guide} />}
    </div>
  );
}

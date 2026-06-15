import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api, Guide, TabInput } from "../api/client";
import GuideSpineEditor from "../components/guide/GuideSpineEditor";
import { useToast } from "../context/ToastContext";

export default function GuideContentEditorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [guide, setGuide] = useState<Guide | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError(null);
    api.painting.guides
      .get(Number(id))
      .then((g) => { if (alive) setGuide(g); })
      .catch((e) => { if (alive) setLoadError(e?.message || "Could not load this guide."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [id]);

  const save = async (tabs: TabInput[]) => {
    setBusy(true);
    setSaveError(null);
    try {
      // Sending `tabs` replaces the whole content subtree (#258 semantics).
      await api.painting.guides.update(Number(id), { tabs });
      toast("Guide content saved.", "success");
      navigate(`/painting/guides/${id}`);
    } catch (e) {
      setSaveError((e as Error)?.message || "Could not save the guide content.");
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <Link to={`/painting/guides/${id}`} className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 mb-4">
        <ArrowLeft size={14} /> Back to guide
      </Link>
      <h1 className="text-2xl font-bold text-white mb-1">Edit content</h1>
      {guide && <p className="text-sm text-gray-500 mb-6">{guide.title}</p>}

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {loadError && <p role="alert" className="text-sm text-rose-400">{loadError}</p>}

      {!loading && !loadError && guide && (
        <GuideSpineEditor
          initialTabs={guide.tabs}
          busy={busy}
          error={saveError}
          onSave={save}
          onCancel={() => navigate(`/painting/guides/${id}`)}
        />
      )}
    </div>
  );
}

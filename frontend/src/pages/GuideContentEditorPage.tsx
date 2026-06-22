import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Eye, EyeOff } from "lucide-react";
import { api, Guide, GuideTab, GuideValidationResult, TabInput } from "../api/client";
import GuideSpineEditor from "../components/guide/GuideSpineEditor";
import GuideReader from "../components/guide/GuideReader";
import GuideValidationPanel from "../components/guide/GuideValidationPanel";
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
  // Live preview projection of the in-progress draft (#488), fed by the editor.
  const [previewTabs, setPreviewTabs] = useState<GuideTab[] | null>(null);
  const [showPreview, setShowPreview] = useState(true);
  // Validator findings for the SAVED guide (#489); refreshed after each save.
  const [validation, setValidation] = useState<GuideValidationResult | null>(null);
  const [validating, setValidating] = useState(false);

  const refreshValidation = async (guideId: number) => {
    setValidating(true);
    try {
      setValidation(await api.painting.guides.validate(guideId));
    } catch {
      // A failed validation fetch shouldn't block editing — leave the panel as is.
    } finally {
      setValidating(false);
    }
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError(null);
    api.painting.guides
      .get(Number(id))
      .then((g) => { if (alive) { setGuide(g); refreshValidation(g.id); } })
      .catch((e) => { if (alive) setLoadError(e?.message || "Could not load this guide."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // refreshValidation is stable for the lifetime of this page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const save = async (tabs: TabInput[]) => {
    setBusy(true);
    setSaveError(null);
    try {
      // Sending `tabs` replaces the whole content subtree (#258 semantics).
      await api.painting.guides.update(Number(id), { tabs });
      toast("Guide content saved.", "success");
      // Stay on the editor and re-run validation so the panel reflects the save.
      await refreshValidation(Number(id));
    } catch (e) {
      setSaveError((e as Error)?.message || "Could not save the guide content.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <Link to={`/painting/guides/${id}`} className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 mb-4">
        <ArrowLeft size={14} /> Back to guide
      </Link>
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1">Edit content</h1>
          {guide && <p className="text-sm text-gray-500">{guide.title}</p>}
        </div>
        {!loading && !loadError && guide && (
          <button
            type="button"
            onClick={() => setShowPreview((v) => !v)}
            aria-pressed={showPreview}
            className="hidden lg:inline-flex items-center gap-1.5 shrink-0 text-sm text-gray-400 hover:text-gray-200 border border-gray-700 rounded px-2.5 py-1.5"
          >
            {showPreview ? <EyeOff size={15} /> : <Eye size={15} />}
            {showPreview ? "Hide preview" : "Show preview"}
          </button>
        )}
      </div>

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {loadError && <p role="alert" className="text-sm text-rose-400">{loadError}</p>}

      {!loading && !loadError && guide && (
        <div className="mb-4">
          <GuideValidationPanel result={validation} loading={validating} />
        </div>
      )}

      {!loading && !loadError && guide && (
        <div className={showPreview ? "lg:grid lg:grid-cols-2 lg:gap-6 lg:items-start" : ""}>
          <GuideSpineEditor
            initialTabs={guide.tabs}
            busy={busy}
            error={saveError}
            onSave={save}
            onCancel={() => navigate(`/painting/guides/${id}`)}
            onPreviewChange={setPreviewTabs}
          />
          {showPreview && (
            <div className="hidden lg:block lg:sticky lg:top-6 mt-6 lg:mt-0">
              <div className="text-[11px] uppercase tracking-wide text-gray-500 mb-2">Live preview</div>
              <div className="border border-gray-800 rounded-lg overflow-auto max-h-[calc(100vh-7rem)]">
                <GuideReader guide={{ ...guide, tabs: previewTabs ?? guide.tabs }} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

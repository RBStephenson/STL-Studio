import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Printer, Globe, Undo2, Trash2, Pencil, ListTree } from "lucide-react";
import { api, Guide } from "../api/client";
import GuideReader from "../components/guide/GuideReader";
import GuideExportMenu from "../components/guide/GuideExportMenu";
import ModelLink from "../components/guide/ModelLink";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";

export default function GuideReaderPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const confirm = useConfirm();
  const [guide, setGuide] = useState<Guide | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  const togglePublish = async () => {
    if (!guide) return;
    const next = guide.status === "published" ? "draft" : "published";
    setBusy(true);
    try {
      const updated = await api.painting.guides.update(guide.id, { status: next });
      setGuide(updated);
      toast(next === "published" ? "Guide published." : "Guide unpublished — back to draft.", "success");
    } catch (e) {
      toast((e as Error)?.message || "Could not update the guide.", "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!guide) return;
    const ok = await confirm({
      title: "Delete this guide?",
      message: `“${guide.title}” and all its tabs, steps and swatches will be permanently deleted.`,
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.painting.guides.delete(guide.id);
      toast("Guide deleted.", "success");
      navigate("/painting/guides");
    } catch (e) {
      toast((e as Error)?.message || "Could not delete the guide.", "error");
      setBusy(false);
    }
  };

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
          <div className="flex items-center gap-2">
            <Link
              to={`/painting/guides/${guide.id}/edit`}
              title="Edit this guide's title, metadata and details"
              className="inline-flex items-center gap-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm px-3 py-1.5 rounded transition-colors"
            >
              <Pencil size={15} /> Edit
            </Link>
            <Link
              to={`/painting/guides/${guide.id}/content`}
              title="Edit this guide's tabs, steps and swatches"
              className="inline-flex items-center gap-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm px-3 py-1.5 rounded transition-colors"
            >
              <ListTree size={15} /> Edit content
            </Link>
            <button
              onClick={togglePublish}
              disabled={busy}
              title={guide.status === "published" ? "Unpublish — return this guide to draft" : "Publish this guide"}
              className="inline-flex items-center gap-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm px-3 py-1.5 rounded transition-colors disabled:opacity-50"
            >
              {guide.status === "published"
                ? (<><Undo2 size={15} /> Unpublish</>)
                : (<><Globe size={15} /> Publish</>)}
            </button>
            <button
              onClick={remove}
              disabled={busy}
              title="Delete this guide"
              className="inline-flex items-center gap-1.5 bg-gray-800 hover:bg-red-950/60 border border-gray-700 hover:border-red-800 text-gray-300 hover:text-red-300 text-sm px-3 py-1.5 rounded transition-colors disabled:opacity-50"
            >
              <Trash2 size={15} /> Delete
            </button>
            <GuideExportMenu guide={guide} busy={busy} setBusy={setBusy} />
            <button
              onClick={() => window.print()}
              title="Print this guide — every tab and sub-tab expands into one document"
              className="inline-flex items-center gap-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm px-3 py-1.5 rounded transition-colors"
            >
              <Printer size={15} /> Print
            </button>
          </div>
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

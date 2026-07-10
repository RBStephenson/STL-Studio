import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, FolderOpen, Package, X } from "lucide-react";
import { api, Model, Collection } from "../api/client";
import ModelCard from "../components/ModelCard";
import { useToast } from "../context/ToastContext";

export default function CollectionDetail() {
  const { id } = useParams<{ id: string }>();
  const collectionId = Number(id);
  const { toast } = useToast();

  const [collection, setCollection] = useState<Collection | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      api.collections.list(),
      api.collections.getModels(collectionId),
    ])
      .then(([cols, mdls]) => {
        setCollection(cols.find((c) => c.id === collectionId) ?? null);
        setModels(mdls);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id, collectionId]);

  const removeModel = async (e: React.MouseEvent, modelId: number) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await api.collections.removeModel(collectionId, modelId);
      setModels((prev) => prev.filter((m) => m.id !== modelId));
      setCollection((prev) =>
        prev ? { ...prev, model_count: Math.max(0, prev.model_count - 1) } : prev
      );
    } catch {
      toast("Couldn't remove model from collection — try again.", "error");
    }
  };

  if (loading) return <div className="p-8 text-text-secondary-alt animate-pulse">Loading…</div>;
  if (!collection) return <div className="p-8 text-text-secondary-alt">Collection not found.</div>;

  return (
    <div className="p-6">
      <Link
        to="/collections"
        className="flex items-center gap-1.5 text-sm text-text-secondary-alt hover:text-text-primary-alt2 mb-6 w-fit"
      >
        <ArrowLeft size={14} /> Back to Collections
      </Link>

      <div className="flex items-center gap-2 mb-1">
        <FolderOpen size={20} className="text-indigo-400" />
        <h1 className="text-2xl font-bold text-text-primary">{collection.name}</h1>
      </div>
      {collection.description && (
        <p className="text-sm text-text-secondary-alt mb-1 ml-7">{collection.description}</p>
      )}
      <p className="text-xs text-text-muted mb-6 ml-7">{models.length} model{models.length !== 1 ? "s" : ""}</p>

      {models.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-text-muted">
          <Package size={48} />
          <p className="mt-3">No models in this collection yet</p>
          <p className="text-xs mt-1">Add models from their detail page</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
          {models.map((model) => (
            <div key={model.id} className="relative group/remove">
              <ModelCard
                model={model}
                backTo={`/collections/${collectionId}`}
              />
              <button
                onClick={(e) => removeModel(e, model.id)}
                title="Remove from collection"
                className="absolute top-1 left-1 z-20 p-1 rounded-full bg-black/70 hover:bg-red-900/80 text-text-secondary hover:text-red-300 opacity-0 group-hover/remove:opacity-100 transition-opacity"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

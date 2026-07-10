// Sibling-variant picker strip for ModelDetail. Lets you jump to another variant
// of the same character. Extracted from ModelDetail.tsx (STUDIO-63 P2) —
// behavior-preserving. Renders nothing unless there is more than one variant.

import { Link } from "react-router-dom";
import { Layers, Package, Printer, Star } from "lucide-react";
import { api, Model, ModelDetail as ModelDetailType, PrintStatus } from "../../../api/client";

interface VariantSwitcherProps {
  variants: Model[];
  model: ModelDetailType;
  /** Live local favorite toggle for the current variant (may differ from fetch). */
  favorite: boolean;
  /** Live local print status for the current variant. */
  printStatus: PrintStatus;
  /** Live local nsfw flag for the current variant. */
  nsfw: boolean;
  showNSFW: boolean;
  backTo: string;
}

export default function VariantSwitcher({
  variants,
  model,
  favorite,
  printStatus,
  nsfw,
  showNSFW,
  backTo,
}: VariantSwitcherProps) {
  if (variants.length <= 1) return null;

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-text-muted flex items-center gap-1.5">
        <Layers size={12} className="text-indigo-400" />
        {variants.length} variants of {model.variant_group?.label ?? model.character}
      </p>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {variants.map((v) => {
          const vThumb = v.thumbnail_path
            ? api.fileUrl(v.thumbnail_path, v.updated_at)
            : v.thumbnail_url ?? null;
          const isCurrent = v.id === model.id;
          // For the current variant, reflect live local toggles rather
          // than the (possibly stale) value from the variants fetch.
          const vFavorite = isCurrent ? favorite : v.is_favorite;
          const vQueued = (isCurrent ? printStatus : v.print_status) === "queued";
          // Include the current model's own nsfw flag so the whole
          // strip reads censored together, not just the flagged
          // variant (STUDIO-45).
          const vBlurred = (v.nsfw || nsfw) && !showNSFW;
          return (
            <Link
              key={v.id}
              to={`/models/${v.id}`}
              state={{ from: backTo }}
              title={v.title || v.name}
              className={`relative shrink-0 w-20 rounded-lg overflow-hidden border-2 transition-colors ${
                isCurrent
                  ? "border-accent-start"
                  : "border-border-subtle hover:border-border-divider"
              }`}
            >
              <div className="aspect-square bg-panel-secondary">
                {vThumb ? (
                  <img
                    src={vThumb}
                    alt=""
                    className={`w-full h-full object-cover ${vBlurred ? "blur-lg" : ""}`}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-text-muted-alt">
                    <Package size={20} />
                  </div>
                )}
                {vBlurred && (
                  <span className="absolute bottom-1 left-1 bg-black/70 rounded px-1 text-[8px] font-medium text-red-400 leading-tight">
                    NSFW
                  </span>
                )}
              </div>
              {(vFavorite || vQueued) && (
                <div className="absolute top-1 right-1 flex gap-0.5">
                  {vQueued && (
                    <span className="bg-black/70 rounded p-0.5 text-sky-400">
                      <Printer size={9} />
                    </span>
                  )}
                  {vFavorite && (
                    <span className="bg-black/70 rounded p-0.5 text-yellow-400">
                      <Star size={9} fill="currentColor" />
                    </span>
                  )}
                </div>
              )}
              <p className="px-1 py-0.5 text-[10px] leading-tight text-text-secondary truncate">
                {v.title || v.name}
              </p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

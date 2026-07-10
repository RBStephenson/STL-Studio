// Source-site stats badges (likes / downloads / source / license) for ModelDetail.
// Extracted from ModelDetail.tsx (STUDIO-63 P2) — behavior-preserving.

import { Heart, Download } from "lucide-react";
import { ModelDetail as ModelDetailType } from "../../../api/client";

export default function StatsRow({ model }: { model: ModelDetailType }) {
  return (
    <div className="flex items-center gap-4 text-sm text-text-secondary">
      {model.like_count != null && (
        <span title="Likes on the source site" className="flex items-center gap-1 text-yellow-400">
          <Heart size={14} fill="currentColor" />
          {model.like_count.toLocaleString()}
        </span>
      )}
      {model.download_count != null && (
        <span className="flex items-center gap-1">
          <Download size={14} />
          {model.download_count.toLocaleString()}
        </span>
      )}
      {model.source_site && (
        <span className="capitalize bg-panel-secondary px-2 py-0.5 rounded text-xs">
          {model.source_site}
        </span>
      )}
      {model.license && (
        <span className="bg-panel-secondary px-2 py-0.5 rounded text-xs">{model.license}</span>
      )}
    </div>
  );
}

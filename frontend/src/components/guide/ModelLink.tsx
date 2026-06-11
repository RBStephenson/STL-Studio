import { Link } from "react-router-dom";
import { Box } from "lucide-react";

/**
 * Cross-module link from a guide back to its STL-Inventory model (#263).
 * Rendered in the reader-page toolbar when the guide has a `model_id`.
 */
export default function ModelLink({ modelId }: { modelId: number }) {
  return (
    <Link
      to={`/models/${modelId}`}
      title="View this model in the library"
      className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300"
    >
      <Box size={14} /> View model
    </Link>
  );
}

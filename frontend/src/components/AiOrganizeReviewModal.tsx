import { useState } from "react";
import { X, Wand2, Loader2, AlertTriangle, Info } from "lucide-react";
import { api, AiOrganizePreviewResult, AiOrganizeSuggestionPreview, STLFile } from "../api/client";
import { errMsg } from "../utils/err";
import { PART_TYPE_SUGGESTIONS } from "../pages/model-detail/utils";

interface EditableRow extends AiOrganizeSuggestionPreview {
  checked: boolean;
  editedPartType: string;
  editedPartName: string;
}

interface Props {
  modelId: number;
  result: AiOrganizePreviewResult;
  stlFiles: STLFile[];
  onApplied: () => void;
  onClose: () => void;
}

// AI Organize is success-via-API-or-nothing (#821): a non-"ok" status means
// there is nothing to review, only an explanation of why. "ok" needs no
// banner — the table below speaks for itself.
const STATUS_BANNER: Record<string, { tone: "error" | "info"; fallback: string }> = {
  error: { tone: "error", fallback: "The AI call failed." },
  disabled: { tone: "info", fallback: "AI Organize has no API configured." },
  skipped: { tone: "info", fallback: "The AI had nothing to refine." },
};

export default function AiOrganizeReviewModal({
  modelId,
  result,
  stlFiles,
  onApplied,
  onClose,
}: Props) {
  const fileById = Object.fromEntries(stlFiles.map((f) => [f.id, f]));

  // Success-via-API-or-nothing (#821), enforced here too, not just trusted
  // from the response: only a genuinely successful AI call populates rows —
  // never heuristic-only guesses presented as if the AI produced them.
  const [rows, setRows] = useState<EditableRow[]>(() =>
    result.llm_status === "ok"
      ? result.suggestions.map((s) => ({
          ...s,
          checked: true,
          editedPartType: s.part_type ?? "",
          editedPartName: s.part_name ?? "",
        }))
      : []
  );
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkedCount = rows.filter((r) => r.checked).length;
  const banner = result.llm_status && result.llm_status !== "ok"
    ? { ...STATUS_BANNER[result.llm_status], detail: result.llm_detail }
    : null;

  const toggle = (id: number) =>
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, checked: !r.checked } : r)));

  const toggleAll = () => {
    const allChecked = rows.every((r) => r.checked);
    setRows((prev) => prev.map((r) => ({ ...r, checked: !allChecked })));
  };

  const setField = (id: number, field: "editedPartType" | "editedPartName", value: string) =>
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));

  const apply = async () => {
    const selected = rows
      .filter((r) => r.checked)
      .map((r) => ({
        id: r.id,
        part_type: r.editedPartType || null,
        part_name: r.editedPartName || null,
        sup_of_id: r.sup_of_id ?? null,
      }));
    if (!selected.length) return;
    setApplying(true);
    setError(null);
    try {
      await api.models.aiOrganizeApply(modelId, selected);
      onApplied();
    } catch (e) {
      setError(errMsg(e) || "Apply failed");
      setApplying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="bg-panel-inset border border-border-subtle rounded-lg shadow-2xl w-full max-w-7xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-subtle">
          <div className="flex items-center gap-2 text-sm font-semibold text-text-primary-alt">
            <Wand2 size={16} className="text-violet-400" />
            AI Organize — Review Suggestions
          </div>
          <button onClick={onClose} className="text-text-secondary-alt hover:text-text-primary-alt transition-colors">
            <X size={18} />
          </button>
        </div>

        {banner ? (
          <div
            className={`flex items-start gap-2 px-5 py-3 border-b border-border-subtle text-sm ${
              banner.tone === "error" ? "text-rose-300" : "text-text-secondary"
            }`}
          >
            {banner.tone === "error"
              ? <AlertTriangle size={16} className="shrink-0 mt-0.5 text-rose-400" />
              : <Info size={16} className="shrink-0 mt-0.5 text-text-secondary-alt" />}
            <span>{banner.detail || banner.fallback}</span>
          </div>
        ) : (
          <p className="px-5 py-2 text-xs text-text-secondary-alt border-b border-border-subtle">
            Uncheck rows to skip them. Edit any value before applying.
          </p>
        )}

        {/* Table — nothing to review when the AI didn't succeed (#821): AI
            Organize never presents heuristic-only guesses as if the AI
            produced them, so a non-"ok" result has zero rows by design. */}
        {rows.length > 0 && (
        <div className="overflow-auto flex-1">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-panel-inset border-b border-border-subtle">
              <tr>
                <th className="px-3 py-2 w-8">
                  <input
                    type="checkbox"
                    checked={rows.every((r) => r.checked)}
                    onChange={toggleAll}
                    className="accent-violet-500"
                    title="Toggle all"
                  />
                </th>
                <th className="px-3 py-2 text-left text-text-secondary font-medium">File</th>
                <th className="px-3 py-2 text-left text-text-secondary font-medium">Current type</th>
                <th className="px-3 py-2 text-left text-text-secondary font-medium">Proposed type</th>
                <th className="px-3 py-2 text-left text-text-secondary font-medium">Current name</th>
                <th className="px-3 py-2 text-left text-text-secondary font-medium">Proposed name</th>
                <th className="px-3 py-2 text-left text-text-secondary font-medium">Links to</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const current = fileById[row.id];
                const dimmed = !row.checked ? "opacity-40" : "";
                const supFile = row.sup_of_id ? fileById[row.sup_of_id] : null;
                return (
                  <tr
                    key={row.id}
                    className={`border-b border-border hover:bg-panel/40 ${dimmed}`}
                  >
                    <td className="px-3 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={row.checked}
                        onChange={() => toggle(row.id)}
                        className="accent-violet-500"
                      />
                    </td>
                    <td className="px-3 py-2 text-text-primary-alt2 font-mono max-w-[180px] truncate" title={row.filename}>
                      {row.filename}
                    </td>
                    <td className="px-3 py-2 text-text-secondary-alt">
                      {current?.part_type || <span className="text-text-muted-alt">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      <select
                        value={row.editedPartType}
                        onChange={(e) => setField(row.id, "editedPartType", e.target.value)}
                        disabled={!row.checked}
                        className="bg-panel border border-border-subtle rounded px-2 py-1 text-text-primary focus:border-violet-600 focus:outline-none w-28"
                      >
                        <option value="">—</option>
                        {PART_TYPE_SUGGESTIONS.map((t) => (
                          <option key={t} value={t}>{t}</option>
                        ))}
                        {row.editedPartType && !PART_TYPE_SUGGESTIONS.includes(row.editedPartType) && (
                          <option value={row.editedPartType}>{row.editedPartType}</option>
                        )}
                      </select>
                    </td>
                    <td className="px-3 py-2 text-text-secondary-alt max-w-[140px] truncate" title={current?.part_name ?? undefined}>
                      {current?.part_name || <span className="text-text-muted-alt">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="text"
                        value={row.editedPartName}
                        onChange={(e) => setField(row.id, "editedPartName", e.target.value)}
                        disabled={!row.checked}
                        className="bg-panel border border-border-subtle rounded px-2 py-1 text-text-primary focus:border-violet-600 focus:outline-none w-36"
                        placeholder="—"
                      />
                    </td>
                    <td className="px-3 py-2 text-text-secondary font-mono max-w-[160px] truncate" title={supFile?.filename}>
                      {supFile
                        ? <span className="text-violet-400">{supFile.filename}</span>
                        : <span className="text-text-muted-alt">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-border-subtle gap-3">
          {error && <p className="text-xs text-rose-400 flex-1">{error}</p>}
          {!error && rows.length > 0 && (
            <span className="text-xs text-text-muted flex-1">{checkedCount} of {rows.length} selected</span>
          )}
          {!error && rows.length === 0 && <span className="flex-1" />}
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="text-sm text-text-secondary hover:text-text-primary-alt border border-border rounded px-4 py-1.5"
            >
              {rows.length === 0 ? "Close" : "Cancel"}
            </button>
            {rows.length > 0 && (
            <button
              onClick={apply}
              disabled={applying || checkedCount === 0}
              className="flex items-center gap-1.5 text-sm bg-violet-700 hover:bg-violet-600 text-white rounded px-4 py-1.5 disabled:opacity-50"
            >
              {applying && <Loader2 size={14} className="animate-spin" />}
              Apply {checkedCount > 0 ? `(${checkedCount})` : ""}
            </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

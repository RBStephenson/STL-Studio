import { AlertTriangle, CircleAlert, CheckCircle2 } from "lucide-react";
import { GuideValidationResult, ValidationFlag } from "../../api/client";

// Jump to the step a flag points at (the editor tags step cards with this id).
function focusNode(f: ValidationFlag) {
  if (f.tab_index == null || f.phase_index == null || f.step_index == null) return;
  const el = document.getElementById(`guide-step-${f.tab_index}-${f.phase_index}-${f.step_index}`);
  el?.scrollIntoView({ behavior: "smooth", block: "center" });
}

/**
 * Validator findings for the open guide (#489). Block flags must be resolved
 * before the guide can publish; warnings are advisory. Each flag jumps to its
 * step card. Reflects the last SAVED state — the panel refreshes after a save.
 */
export default function GuideValidationPanel({
  result, loading,
}: { result: GuideValidationResult | null; loading: boolean }) {
  if (loading && !result) {
    return <p className="text-xs text-text-secondary-alt">Checking…</p>;
  }
  if (!result) return null;

  if (result.flags.length === 0) {
    return (
      <p className="inline-flex items-center gap-1.5 text-sm text-emerald-400">
        <CheckCircle2 size={15} /> No validation issues.
      </p>
    );
  }

  // Block flags first, then warnings — most actionable at the top.
  const flags = [...result.flags].sort(
    (a, b) => (a.severity === b.severity ? 0 : a.severity === "block" ? -1 : 1),
  );
  const blocks = result.flags.filter((f) => f.severity === "block").length;

  return (
    <div className="border border-border-subtle rounded-lg p-3 bg-panel/60">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-medium text-text-primary-alt">Validation</h2>
        <span className={`text-xs ${blocks ? "text-rose-400" : "text-amber-400"}`}>
          {blocks > 0
            ? `${blocks} blocking issue${blocks === 1 ? "" : "s"} — resolve before publishing`
            : `${result.flags.length} warning${result.flags.length === 1 ? "" : "s"}`}
        </span>
      </div>
      <ul className="space-y-1.5">
        {flags.map((f, i) => {
          const jumpable = f.tab_index != null && f.phase_index != null && f.step_index != null;
          const Icon = f.severity === "block" ? CircleAlert : AlertTriangle;
          return (
            <li key={i}>
              <button
                type="button"
                onClick={() => focusNode(f)}
                disabled={!jumpable}
                className={`w-full text-left flex items-start gap-2 rounded px-2 py-1.5 text-xs ${
                  jumpable ? "hover:bg-panel-secondary cursor-pointer" : "cursor-default"
                }`}
              >
                <Icon
                  size={14}
                  className={`mt-0.5 shrink-0 ${f.severity === "block" ? "text-rose-400" : "text-amber-400"}`}
                />
                <span className="min-w-0">
                  {f.path && <span className="block text-text-secondary truncate">{f.path}</span>}
                  <span className="text-text-primary-alt">{f.message}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

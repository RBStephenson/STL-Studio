import { X, Layers, Puzzle, Link2 } from "lucide-react";
import type { AiOrganizeStrategy } from "../api/client";

interface Props {
  onChoose: (strategy: AiOrganizeStrategy) => void;
  onClose: () => void;
}

// Hover text for each option (#878) — native `title` attribute, matching
// this codebase's existing tooltip convention (no dedicated Tooltip component).
const STRATEGY_TOOLTIPS: Record<AiOrganizeStrategy, string> = {
  unit:
    "Groups files by the in-game unit or character they belong to (e.g. every " +
    "\"Royal Guard 1\" file — head, helmet, weapon — gets that as its category), " +
    "instead of by physical part. Category names are derived per-model, so they " +
    "aren't limited to the app's standard category list.",
  parts:
    "The standard approach: categorizes each file by physical part type " +
    "(Head, Weapon, Base, etc.) picked from the app's standard category list.",
  link_sups:
    "Matches a currently-unlinked file named \"Sup\", \"Supported\", or " +
    "\"Hollowed\" to its likely base part by name (e.g. \"Icon of Flame 2 " +
    "Supported\" → \"Icon of Flame 2\") and suggests the link. A plain-named " +
    "file is never linked to another file, only ever a possible match target. " +
    "Pure name matching — no AI API needed, works even without one configured.",
};

export default function AiOrganizeStrategyModal({ onChoose, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-md shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h2 className="text-base font-semibold text-gray-100">AI Organize</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-gray-800 text-gray-500 hover:text-gray-300"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5 flex flex-col gap-3">
          <p className="text-sm text-gray-400">How should the AI categorize this model's files?</p>

          <button
            onClick={() => onChoose("unit")}
            title={STRATEGY_TOOLTIPS.unit}
            className="flex items-start gap-3 text-left px-4 py-3 rounded-lg border border-gray-700 bg-gray-800 hover:bg-gray-750 hover:border-indigo-500 transition-colors"
          >
            <Layers size={18} className="text-indigo-400 shrink-0 mt-0.5" />
            <span>
              <span className="block text-sm font-medium text-gray-100">Unit-based</span>
              <span className="block text-xs text-gray-500 mt-0.5">
                Group by the unit/character a file belongs to (e.g. "Royal Guard 1").
              </span>
            </span>
          </button>

          <button
            onClick={() => onChoose("parts")}
            title={STRATEGY_TOOLTIPS.parts}
            className="flex items-start gap-3 text-left px-4 py-3 rounded-lg border border-gray-700 bg-gray-800 hover:bg-gray-750 hover:border-indigo-500 transition-colors"
          >
            <Puzzle size={18} className="text-indigo-400 shrink-0 mt-0.5" />
            <span>
              <span className="block text-sm font-medium text-gray-100">Parts-based</span>
              <span className="block text-xs text-gray-500 mt-0.5">
                Categorize by physical part type (Head, Weapon, Base, etc.) — the standard approach.
              </span>
            </span>
          </button>

          <button
            onClick={() => onChoose("link_sups")}
            title={STRATEGY_TOOLTIPS.link_sups}
            className="flex items-start gap-3 text-left px-4 py-3 rounded-lg border border-gray-700 bg-gray-800 hover:bg-gray-750 hover:border-indigo-500 transition-colors"
          >
            <Link2 size={18} className="text-indigo-400 shrink-0 mt-0.5" />
            <span>
              <span className="block text-sm font-medium text-gray-100">Link supported parts</span>
              <span className="block text-xs text-gray-500 mt-0.5">
                Match unlinked "Sup"/"Supported"/"Hollowed" files to their base part by name. No AI API needed.
              </span>
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}

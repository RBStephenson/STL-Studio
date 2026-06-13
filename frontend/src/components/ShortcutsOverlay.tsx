import { Keyboard, X } from "lucide-react";

interface Props {
  onClose: () => void;
}

const SHORTCUTS: { keys: string[]; desc: string }[] = [
  { keys: ["/"], desc: "Focus the search box" },
  { keys: ["A", "D"], desc: "Move left / right between cards" },
  { keys: ["W", "S"], desc: "Move up / down a row" },
  { keys: ["←", "→", "↑", "↓"], desc: "Move between cards (arrow keys)" },
  { keys: ["Enter"], desc: "Open the focused model" },
  { keys: ["Esc"], desc: "Clear focus / close this dialog" },
  { keys: ["?"], desc: "Show this help" },
];

// Help dialog for the Library keyboard shortcuts (#169). Closing is driven by
// the backdrop, the X button, and the global Escape handler in Library.
export default function ShortcutsOverlay({ onClose }: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="w-full max-w-sm rounded-xl border border-gray-700 bg-gray-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-100">
            <Keyboard size={18} className="text-indigo-400" />
            Keyboard shortcuts
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-gray-500 hover:text-gray-200 transition-colors"
          >
            <X size={18} />
          </button>
        </div>
        <ul className="flex flex-col gap-2.5">
          {SHORTCUTS.map(({ keys, desc }) => (
            <li key={desc} className="flex items-center justify-between gap-4">
              <span className="text-sm text-gray-400">{desc}</span>
              <span className="flex items-center gap-1 shrink-0">
                {keys.map((k) => (
                  <kbd
                    key={k}
                    className="min-w-[1.6rem] text-center rounded border border-gray-600 bg-gray-800 px-1.5 py-0.5 text-xs font-medium text-gray-200"
                  >
                    {k}
                  </kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

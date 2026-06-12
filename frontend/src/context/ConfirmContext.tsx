import { createContext, useContext, useState, useCallback, ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

export interface ConfirmOptions {
  /** Dialog heading. Defaults to "Are you sure?". */
  title?: string;
  /** Body — string or rich node. Newlines in a string render as separate lines. */
  message: ReactNode;
  /** Confirm button label. Defaults to "Confirm". */
  confirmLabel?: string;
  /** Cancel button label. Defaults to "Cancel". */
  cancelLabel?: string;
  /** Style the confirm button as destructive (red). */
  destructive?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

// Default resolves false so a missing provider can never silently confirm a
// destructive action.
const ConfirmContext = createContext<ConfirmFn>(() => Promise.resolve(false));

interface PendingConfirm {
  options: ConfirmOptions;
  resolve: (result: boolean) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingConfirm | null>(null);

  const confirm = useCallback<ConfirmFn>(
    (options) => new Promise<boolean>((resolve) => setPending({ options, resolve })),
    [],
  );

  const settle = useCallback(
    (result: boolean) => {
      setPending((cur) => {
        cur?.resolve(result);
        return null;
      });
    },
    [],
  );

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && <ConfirmDialog options={pending.options} onSettle={settle} />}
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({
  options,
  onSettle,
}: {
  options: ConfirmOptions;
  onSettle: (result: boolean) => void;
}) {
  const {
    title = "Are you sure?",
    message,
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    destructive = false,
  } = options;

  const lines =
    typeof message === "string"
      ? message.split("\n").map((line, i) => <p key={i}>{line || " "}</p>)
      : message;

  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-black/70"
      onClick={() => onSettle(false)}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-md shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 px-5 pt-5">
          {destructive && <AlertTriangle size={20} className="shrink-0 mt-0.5 text-red-400" />}
          <div className="flex-1">
            <h2 className="font-semibold text-gray-100">{title}</h2>
            <div className="mt-2 text-sm text-gray-400 leading-snug space-y-2">{lines}</div>
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-4">
          <button
            onClick={() => onSettle(false)}
            className="px-3 py-1.5 rounded text-sm bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            autoFocus
            onClick={() => onSettle(true)}
            className={`px-3 py-1.5 rounded text-sm text-white transition-colors ${
              destructive
                ? "bg-red-600 hover:bg-red-500"
                : "bg-indigo-600 hover:bg-indigo-500"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export const useConfirm = () => useContext(ConfirmContext);

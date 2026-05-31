import { createContext, useContext, useState, useCallback, ReactNode } from "react";
import { CheckCircle, AlertCircle, Info, X } from "lucide-react";

type ToastType = "success" | "error" | "info";

interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue>({ toast: () => {} });

let _nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, type: ToastType = "info") => {
      const id = ++_nextId;
      setToasts((prev) => [...prev, { id, message, type }]);
      setTimeout(() => remove(id), 4000);
    },
    [remove],
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <Toaster toasts={toasts} onClose={remove} />
    </ToastContext.Provider>
  );
}

const ICONS = { success: CheckCircle, error: AlertCircle, info: Info } as const;
const STYLES: Record<ToastType, string> = {
  success: "bg-emerald-950/90 border-emerald-700 text-emerald-200",
  error: "bg-red-950/90 border-red-700 text-red-200",
  info: "bg-gray-900/95 border-gray-700 text-gray-200",
};

function Toaster({ toasts, onClose }: { toasts: Toast[]; onClose: (id: number) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 w-80 max-w-[calc(100vw-2rem)]">
      {toasts.map((t) => {
        const Icon = ICONS[t.type];
        return (
          <div
            key={t.id}
            role="status"
            className={`flex items-start gap-2.5 px-4 py-3 rounded-lg border shadow-lg text-sm animate-[fadeIn_0.15s_ease-out] ${STYLES[t.type]}`}
          >
            <Icon size={16} className="shrink-0 mt-0.5" />
            <span className="flex-1 leading-snug">{t.message}</span>
            <button
              onClick={() => onClose(t.id)}
              className="shrink-0 text-current/60 hover:text-current transition-colors"
              aria-label="Dismiss"
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export const useToast = () => useContext(ToastContext);

import { useState, useEffect, useCallback } from "react";
import { X, Folder, HardDrive, ArrowUp, Check, Loader2, AlertCircle } from "lucide-react";
import { api, DirListing } from "../api/client";

interface Props {
  onSelect: (path: string) => void;
  onClose: () => void;
  mode?: string; // passed to /scan/browse — "inbox" uses bootstrap allowlist
  initialPath?: string;
}

export default function FolderPicker({ onSelect, onClose, mode, initialPath }: Props) {
  const [listing, setListing] = useState<DirListing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const browse = useCallback((path?: string) => {
    setLoading(true);
    setError(null);
    api.scan
      .browse(path, mode)
      .then(setListing)
      .catch(() => setError("Can't open that folder (permission denied or unavailable)."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { browse(initialPath); }, [browse, initialPath]);

  const atDriveList = listing?.is_drive_list ?? false;
  const currentPath = listing?.path ?? "";
  const canSelect = !atDriveList && !!currentPath;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg max-h-[80vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h2 className="font-semibold text-gray-100">Choose a folder</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X size={18} />
          </button>
        </div>

        {/* Current path + up */}
        <div className="flex items-center gap-2 px-5 py-3 border-b border-gray-800 bg-gray-950/40">
          <button
            onClick={() => browse(listing?.parent ?? undefined)}
            disabled={listing?.parent == null}
            title="Up one level"
            className="p-1.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-400 disabled:opacity-30 disabled:hover:bg-gray-800"
          >
            <ArrowUp size={15} />
          </button>
          <span className="text-sm text-gray-300 font-mono truncate flex-1">
            {atDriveList ? "This PC" : currentPath || "…"}
          </span>
        </div>

        {/* Listing */}
        <div className="flex-1 overflow-y-auto p-2 min-h-[14rem]">
          {loading ? (
            <div className="flex items-center justify-center h-40 text-gray-600 gap-2">
              <Loader2 size={16} className="animate-spin" />
              <span className="text-sm">Loading…</span>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center h-40 text-gray-500 gap-2 px-6 text-center">
              <AlertCircle size={24} className="text-amber-500" />
              <p className="text-sm">{error}</p>
            </div>
          ) : listing && listing.entries.length === 0 ? (
            <div className="flex items-center justify-center h-40 text-gray-600 text-sm">
              No sub-folders here
            </div>
          ) : (
            <div className="flex flex-col">
              {listing?.entries.map((e) => (
                <button
                  key={e.path}
                  onClick={() => browse(e.path)}
                  className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-gray-800 text-left text-sm text-gray-200 transition-colors"
                >
                  {atDriveList ? (
                    <HardDrive size={15} className="text-indigo-400 shrink-0" />
                  ) : (
                    <Folder size={15} className="text-indigo-400 shrink-0" />
                  )}
                  <span className="truncate font-mono">{e.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 px-5 py-4 border-t border-gray-800">
          <span className="text-xs text-gray-600">
            Navigate into the folder you want, then select it.
          </span>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded bg-gray-800 hover:bg-gray-700 text-sm text-gray-300">
              Cancel
            </button>
            <button
              onClick={() => onSelect(currentPath)}
              disabled={!canSelect}
              className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm flex items-center gap-1.5 transition-colors"
            >
              <Check size={14} />
              Select this folder
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

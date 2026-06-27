import { AlertCircle, CheckCircle } from "lucide-react";

interface Props {
  success: string | null;
  error: string | null;
}

export default function FlashBanner({ success, error }: Props) {
  return (
    <>
      {success && (
        <div className="flex items-center gap-2 bg-green-950/60 border border-green-800 text-green-300 text-sm px-4 py-2.5 rounded-lg mb-4">
          <CheckCircle size={15} /> {success}
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 bg-red-950/60 border border-red-800 text-red-300 text-sm px-4 py-2.5 rounded-lg mb-4">
          <AlertCircle size={15} /> {error}
        </div>
      )}
    </>
  );
}

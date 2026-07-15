import { useEffect, useState } from "react";
import { CheckCircle2, Clipboard, Server, TriangleAlert } from "lucide-react";
import { api, type SystemInfo } from "../api/client";
import { useAppSettings } from "../context/AppSettingsContext";
import { errMsg } from "../utils/err";

const modeLabel = (mode: SystemInfo["deployment_mode"]) => ({
  electron: "Electron desktop",
  standalone: "Standalone web",
  web: "Hosted web",
})[mode];

export function diagnosticText(info: SystemInfo): string {
  return [
    "STL Studio system info",
    `Version: ${info.version}`,
    `Deployment: ${modeLabel(info.deployment_mode)}`,
    `Backend: ${info.backend_status}`,
    `Database: ${info.database_status}`,
    `Libraries: ${info.libraries_available}/${info.libraries_enabled} available (${info.libraries_configured} configured)`,
    `Last scan: ${info.last_scan ?? "never"}`,
  ].join("\n");
}

export default function SystemInfoPanel() {
  const { settings } = useAppSettings();
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!settings.system_info_enabled) return;
    let alive = true;
    api.settings.systemInfo()
      .then((value) => { if (alive) setInfo(value); })
      .catch((e) => { if (alive) setLoadError(errMsg(e) || "Could not load system info."); });
    return () => { alive = false; };
  }, [settings.system_info_enabled]);

  if (!settings.system_info_enabled) return null;
  if (loadError) {
    return <div role="alert" className="mt-5 rounded-lg border border-rose-800/70 bg-rose-950/30 px-4 py-3 text-sm text-rose-300">{loadError}</div>;
  }
  if (!info) {
    return <div role="status" className="mt-5 text-sm text-text-muted">Loading system info…</div>;
  }

  const degraded = info.backend_status !== "healthy"
    || info.database_status !== "healthy"
    || info.libraries_available < info.libraries_enabled;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(diagnosticText(info));
      setCopyError(null);
      setCopied(true);
    } catch {
      setCopyError("Could not copy diagnostics. Your browser may have blocked clipboard access.");
    }
  };

  return (
    <section aria-labelledby="system-info-title" className="mt-6 rounded-xl border border-border-subtle bg-panel/70 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 id="system-info-title" className="flex items-center gap-2 font-semibold text-text-primary-alt">
            <Server size={16} /> System Info
          </h3>
          <p className="mt-1 text-xs text-text-muted">Sanitized and safe to include in a public support request.</p>
        </div>
        <button onClick={copy} className="flex items-center gap-1.5 rounded border border-border bg-panel-secondary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary-alt">
          <Clipboard size={13} /> {copied ? "Copied" : "Copy diagnostics"}
        </button>
      </div>

      <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
        <dt className="text-text-muted">Version</dt><dd className="text-text-primary-alt2">{info.version}</dd>
        <dt className="text-text-muted">Deployment</dt><dd className="text-text-primary-alt2">{modeLabel(info.deployment_mode)}</dd>
        <dt className="text-text-muted">Backend</dt><dd className="text-text-primary-alt2">{info.backend_status}</dd>
        <dt className="text-text-muted">Database</dt><dd className="text-text-primary-alt2">{info.database_status}</dd>
        <dt className="text-text-muted">Libraries</dt>
        <dd className="text-text-primary-alt2">{info.libraries_available} of {info.libraries_enabled} enabled available ({info.libraries_configured} configured)</dd>
        <dt className="text-text-muted">Last scan</dt>
        <dd className="text-text-primary-alt2">{info.last_scan ? new Date(info.last_scan).toLocaleString() : "Never"}</dd>
      </dl>

      <div className={`mt-4 flex items-center gap-2 rounded px-3 py-2 text-xs ${degraded ? "bg-amber-950/40 text-amber-300" : "bg-emerald-950/35 text-emerald-300"}`}>
        {degraded ? <TriangleAlert size={14} /> : <CheckCircle2 size={14} />}
        {degraded
          ? "Some services or libraries are temporarily unavailable. Your catalog data is retained."
          : "STL Studio and all enabled libraries are available."}
      </div>
      {copyError && <p role="alert" className="mt-2 text-xs text-rose-300">{copyError}</p>}
    </section>
  );
}

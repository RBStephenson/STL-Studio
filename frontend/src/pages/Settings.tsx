import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { SlidersHorizontal, HardDrive, Paintbrush, Bot, Database } from "lucide-react";
import { api, ScanRoot } from "../api/client";
import HelpLink from "../components/HelpLink";
import LibraryTab from "./settings/LibraryTab";
import ScanningTab from "./settings/ScanningTab";
import PaintingTab from "./settings/PaintingTab";
import AiIntegrationsTab from "./settings/AiIntegrationsTab";
import PreferencesTab from "./settings/PreferencesTab";
import DataTab from "./settings/DataTab";

// Re-keyed per design/README.md "New Since Last Handoff" — Settings sidebar
// nav reorg: 6-tab underline nav consolidated to 5 groups. Old tab content
// components are unchanged and stacked within their new group rather than
// physically merged, keeping the diff (and risk) small.
type TabId = "general" | "library" | "features" | "ai" | "data";

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: "general",  label: "General",           icon: <SlidersHorizontal size={14} /> },
  { id: "library",  label: "Library & Scanning", icon: <HardDrive size={14} /> },
  { id: "features", label: "Features",           icon: <Paintbrush size={14} /> },
  { id: "ai",       label: "AI & Automation",    icon: <Bot size={14} /> },
  { id: "data",     label: "Data",               icon: <Database size={14} /> },
];

function hashToTab(hash: string): TabId {
  const id = hash.replace("#", "") as TabId;
  return TABS.some((t) => t.id === id) ? id : "library";
}

export default function Settings() {
  const location = useLocation();
  const navigate = useNavigate();
  const [active, setActive] = useState<TabId>(() => hashToTab(location.hash));

  const [roots, setRoots] = useState<ScanRoot[]>([]);
  const [loading, setLoading] = useState(true);

  const loadRoots = () => {
    api.scan.roots()
      .then(setRoots)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadRoots(); }, []);

  useEffect(() => {
    setActive(hashToTab(location.hash));
  }, [location.hash]);

  const switchTab = (id: TabId) => {
    navigate(`/settings#${id}`, { replace: true });
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="flex items-center gap-2 text-2xl font-bold text-white mb-1">
        Settings
        <HelpLink section="settings" label="About scan locations & data management" />
      </h1>
      <p className="text-sm text-text-secondary-alt mb-6">Configure your library, scanning rules, and integrations.</p>

      <div className="flex gap-8 items-start">
        {/* Sidebar nav */}
        <nav className="w-[210px] shrink-0 sticky top-8 flex flex-col gap-0.5">
          {TABS.map((tab) => {
            const isActive = active === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => switchTab(tab.id)}
                aria-current={isActive ? "page" : undefined}
                className="flex items-center gap-2 text-sm text-left transition-colors"
                style={{
                  padding: "9px 12px",
                  background: isActive ? "#1c1e2e" : "transparent",
                  borderLeft: isActive ? "2px solid #6366f1" : "2px solid transparent",
                  borderRadius: "0 8px 8px 0",
                  color: isActive ? "#f4f4f6" : "#8b8f9c",
                }}
              >
                {tab.icon}
                {tab.label}
              </button>
            );
          })}
        </nav>

        {/* Tab content */}
        <div className="flex-1 min-w-0 flex flex-col gap-8">
          {active === "general" && <PreferencesTab />}
          {active === "library" && (
            <>
              <LibraryTab roots={roots} loading={loading} onRootsChanged={loadRoots} />
              <ScanningTab />
            </>
          )}
          {active === "features" && <PaintingTab />}
          {active === "ai"       && <AiIntegrationsTab />}
          {active === "data"     && <DataTab />}
        </div>
      </div>
    </div>
  );
}

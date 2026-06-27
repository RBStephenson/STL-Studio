import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { HardDrive, ScanLine, Paintbrush, Bot, SlidersHorizontal, Database } from "lucide-react";
import { api, ScanRoot } from "../api/client";
import HelpLink from "../components/HelpLink";
import LibraryTab from "./settings/LibraryTab";
import ScanningTab from "./settings/ScanningTab";
import PaintingTab from "./settings/PaintingTab";
import AiIntegrationsTab from "./settings/AiIntegrationsTab";
import PreferencesTab from "./settings/PreferencesTab";
import DataTab from "./settings/DataTab";

type TabId = "library" | "scanning" | "painting" | "ai" | "preferences" | "data";

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: "library",     label: "Library",           icon: <HardDrive size={14} /> },
  { id: "scanning",    label: "Scanning",           icon: <ScanLine size={14} /> },
  { id: "painting",    label: "Painting",           icon: <Paintbrush size={14} /> },
  { id: "ai",         label: "AI & Integrations",  icon: <Bot size={14} /> },
  { id: "preferences", label: "Preferences",        icon: <SlidersHorizontal size={14} /> },
  { id: "data",        label: "Data",               icon: <Database size={14} /> },
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
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="flex items-center gap-2 text-2xl font-bold text-white mb-1">
        Settings
        <HelpLink section="settings" label="About scan locations & data management" />
      </h1>
      <p className="text-sm text-gray-500 mb-6">Configure your library, scanning rules, and integrations.</p>

      {/* Tab nav */}
      <div className="flex gap-1 mb-8 border-b border-gray-800 flex-wrap">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => switchTab(tab.id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-colors -mb-px ${
              active === tab.id
                ? "border-indigo-500 text-white"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {active === "library"     && <LibraryTab roots={roots} loading={loading} onRootsChanged={loadRoots} />}
      {active === "scanning"    && <ScanningTab />}
      {active === "painting"    && <PaintingTab />}
      {active === "ai"          && <AiIntegrationsTab />}
      {active === "preferences" && <PreferencesTab />}
      {active === "data"        && <DataTab />}
    </div>
  );
}

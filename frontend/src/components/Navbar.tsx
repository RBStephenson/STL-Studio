import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Box, FolderOpen, Users, LayoutGrid, EyeOff, Eye, AlertTriangle, Settings, Printer } from "lucide-react";
import { useNSFW } from "../context/NSFWContext";
import { api } from "../api/client";

export default function Navbar() {
  const { pathname } = useLocation();
  const { showNSFW, toggle } = useNSFW();
  const [reviewCount, setReviewCount] = useState<number | null>(null);
  const [queueCount, setQueueCount] = useState<number | null>(null);

  useEffect(() => {
    api.models.stats().then(s => {
      setReviewCount(s.needs_review);
      setQueueCount(s.queued);
    }).catch(() => {});
  }, []);

  const links = [
    { to: "/",            label: "Library",     icon: LayoutGrid,    badge: null },
    { to: "/creators",    label: "Creators",    icon: Users,         badge: null },
    { to: "/collections", label: "Collections", icon: FolderOpen,    badge: null },
    { to: "/queue",       label: "Queue",       icon: Printer,       badge: queueCount },
    { to: "/triage",      label: "Triage",      icon: AlertTriangle, badge: reviewCount },
    { to: "/settings",   label: "Settings",    icon: Settings,      badge: null },
  ];

  return (
    <nav className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-8">
      <Link to="/" className="flex items-center gap-2 text-indigo-400 font-bold text-lg shrink-0">
        <Box size={22} />
        STL Inventory
      </Link>

      <div className="flex items-center gap-1 ml-4">
        {links.map(({ to, label, icon: Icon, badge }) => (
          <Link
            key={to}
            to={to}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
              pathname === to
                ? "bg-indigo-600 text-white"
                : "text-gray-400 hover:text-gray-100 hover:bg-gray-800"
            }`}
          >
            <Icon size={15} />
            {label}
            {badge != null && badge > 0 && (
              <span className={`ml-0.5 px-1.5 py-0.5 rounded-full text-xs font-medium leading-none ${
                pathname === to
                  ? "bg-white/20 text-white"
                  : "bg-yellow-500/20 text-yellow-400"
              }`}>
                {badge.toLocaleString()}
              </span>
            )}
          </Link>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={toggle}
          title={showNSFW ? "Hide NSFW content" : "Show NSFW content"}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors border ${
            showNSFW
              ? "bg-red-950/60 border-red-800 text-red-400 hover:bg-red-900/60"
              : "bg-gray-800 border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-600"
          }`}
        >
          {showNSFW ? <Eye size={14} /> : <EyeOff size={14} />}
          {showNSFW ? "NSFW On" : "NSFW Off"}
        </button>
      </div>
    </nav>
  );
}

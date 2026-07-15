import { Routes, Route, Navigate } from "react-router-dom";
import { useAppSettings } from "./context/AppSettingsContext";
import Navbar from "./components/Navbar";
import Library from "./pages/Library";
import ModelDetail from "./pages/ModelDetail";
import Creators from "./pages/Creators";
import Collections from "./pages/Collections";
import CollectionDetail from "./pages/CollectionDetail";
import Queue from "./pages/Queue";
import Triage from "./pages/Triage";
import VariantGroup from "./pages/VariantGroup";
import Settings from "./pages/Settings";
import Help from "./pages/Help";
import TagsPage from "./pages/TagsPage";
import GuidesPage from "./pages/GuidesPage";
import GuideReaderPage from "./pages/GuideReaderPage";
import GuideEditorPage from "./pages/GuideEditorPage";
import GuideWizardPage from "./pages/GuideWizardPage";
import GuideContentEditorPage from "./pages/GuideContentEditorPage";
import GuideDraftReviewPage from "./pages/GuideDraftReviewPage";
import PaintShelfPage from "./pages/PaintShelfPage";
import ColorMatchStudioPage from "./pages/ColorMatchStudioPage";
import ReorganizePage from "./pages/ReorganizePage";
import ImportPage from "./pages/ImportPage";
import ImportPreviewPage from "./pages/ImportPreviewPage";
import BackToTop from "./components/BackToTop";
import StorageRecoveryMonitor from "./components/StorageRecoveryMonitor";

// The Reorganize feature is gated behind the `reorganize_enabled` flag: when
// off, the page is unreachable even by direct URL (the nav link is hidden in
// the Library settings tab).
function ReorganizeRoute() {
  const { settings } = useAppSettings();
  return settings.reorganize_enabled ? <ReorganizePage /> : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <StorageRecoveryMonitor />
      <Navbar />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/models/:id" element={<ModelDetail />} />
          <Route path="/groups/:creatorId/:character" element={<VariantGroup />} />
          <Route path="/creators" element={<Creators />} />
          <Route path="/collections" element={<Collections />} />
          <Route path="/collections/:id" element={<CollectionDetail />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/triage" element={<Triage />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/reorganize" element={<ReorganizeRoute />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/import/preview" element={<ImportPreviewPage />} />
          <Route path="/tags" element={<TagsPage />} />
          <Route path="/painting/guides" element={<GuidesPage />} />
          <Route path="/painting/guides/new" element={<GuideWizardPage />} />
          <Route path="/painting/guides/:id" element={<GuideReaderPage />} />
          <Route path="/painting/guides/:id/edit" element={<GuideEditorPage />} />
          <Route path="/painting/guides/:id/content" element={<GuideContentEditorPage />} />
          <Route path="/painting/guides/:id/draft" element={<GuideDraftReviewPage />} />
          <Route path="/painting/shelf" element={<PaintShelfPage />} />
          <Route path="/painting/color-match" element={<ColorMatchStudioPage />} />
          <Route path="/help" element={<Help />} />
        </Routes>
      </main>
      <BackToTop />
    </div>
  );
}

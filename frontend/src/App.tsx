import { Routes, Route } from "react-router-dom";
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
import GuideContentEditorPage from "./pages/GuideContentEditorPage";
import PaintShelfPage from "./pages/PaintShelfPage";
import ReorganizePage from "./pages/ReorganizePage";
import BackToTop from "./components/BackToTop";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
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
          <Route path="/reorganize" element={<ReorganizePage />} />
          <Route path="/tags" element={<TagsPage />} />
          <Route path="/painting/guides" element={<GuidesPage />} />
          <Route path="/painting/guides/new" element={<GuideEditorPage />} />
          <Route path="/painting/guides/:id" element={<GuideReaderPage />} />
          <Route path="/painting/guides/:id/edit" element={<GuideEditorPage />} />
          <Route path="/painting/guides/:id/content" element={<GuideContentEditorPage />} />
          <Route path="/painting/shelf" element={<PaintShelfPage />} />
          <Route path="/help" element={<Help />} />
        </Routes>
      </main>
      <BackToTop />
    </div>
  );
}

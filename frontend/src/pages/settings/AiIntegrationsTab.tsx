import { useEffect, useState } from "react";
import { Bot, Link2, Boxes, Wand2 } from "lucide-react";
import { api, AiEffort, AiSettings, AiOrganizeSettings, CultsSettings, MmfSettings } from "../../api/client";
import { useAppSettings } from "../../context/AppSettingsContext";
import FlashBanner from "./FlashBanner";
import { useSettingsFlash } from "./useSettingsFlash";

export default function AiIntegrationsTab() {
  const { settings, update } = useAppSettings();
  const { success, error, flash } = useSettingsFlash();

  // Anthropic
  const [aiSettings, setAiSettings] = useState<AiSettings | null>(null);
  const [aiKeyDraft, setAiKeyDraft] = useState("");
  const [editingKey, setEditingKey] = useState(false);

  // Cults3D
  const [cultsSettings, setCultsSettings] = useState<CultsSettings | null>(null);
  const [cultsUser, setCultsUser] = useState("");
  const [cultsKey, setCultsKey] = useState("");
  const [editingCults, setEditingCults] = useState(false);

  // MyMiniFactory
  const [mmfSettings, setMmfSettings] = useState<MmfSettings | null>(null);
  const [mmfKeyDraft, setMmfKeyDraft] = useState("");
  const [editingMmf, setEditingMmf] = useState(false);

  // AI Organizer
  const [organizeSettings, setOrganizeSettings] = useState<AiOrganizeSettings | null>(null);
  const [organizeKeyDraft, setOrganizeKeyDraft] = useState("");
  const [editingOrganizeKey, setEditingOrganizeKey] = useState(false);
  const [organizeModels, setOrganizeModels] = useState<string[]>([]);
  const [organizeModelsLoading, setOrganizeModelsLoading] = useState(false);
  const [organizeModelsError, setOrganizeModelsError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.settings.ai.get()
      .then((s) => { if (alive) setAiSettings(s); })
      .catch(() => {});
    api.settings.cults.get()
      .then((s) => { if (alive) setCultsSettings(s); })
      .catch(() => {});
    api.settings.mmf.get()
      .then((s) => { if (alive) setMmfSettings(s); })
      .catch(() => {});
    api.settings.aiOrganize.get()
      .then((s) => { if (alive) setOrganizeSettings(s); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const saveAiKey = async () => {
    const key = aiKeyDraft.trim();
    if (!key) return;
    try {
      setAiSettings(await api.settings.ai.setKey(key));
      setAiKeyDraft("");
      setEditingKey(false);
      flash("API key saved", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not save the API key", "err");
    }
  };

  const clearAiKey = async () => {
    try {
      setAiSettings(await api.settings.ai.clearKey());
      flash("API key cleared", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not clear the API key", "err");
    }
  };

  const saveAiModel = async (model: string) => {
    try {
      await update({ ai_model: model });
    } catch (e: any) {
      flash(e?.message || "Could not save the model", "err");
    }
  };

  const saveAiEffort = async (effort: AiEffort) => {
    try {
      await update({ ai_effort: effort });
    } catch (e: any) {
      flash(e?.message || "Could not save the effort", "err");
    }
  };

  const saveCultsCredentials = async () => {
    const u = cultsUser.trim();
    const k = cultsKey.trim();
    if (!u || !k) return;
    try {
      setCultsSettings(await api.settings.cults.setCredentials(u, k));
      setCultsUser("");
      setCultsKey("");
      setEditingCults(false);
      flash("Cults3D credentials saved", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not save Cults3D credentials", "err");
    }
  };

  const clearCultsCredentials = async () => {
    try {
      setCultsSettings(await api.settings.cults.clearCredentials());
      flash("Cults3D credentials cleared", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not clear Cults3D credentials", "err");
    }
  };

  const saveMmfKey = async () => {
    const key = mmfKeyDraft.trim();
    if (!key) return;
    try {
      setMmfSettings(await api.settings.mmf.setKey(key));
      setMmfKeyDraft("");
      setEditingMmf(false);
      flash("MyMiniFactory key saved", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not save the MyMiniFactory key", "err");
    }
  };

  const clearMmfKey = async () => {
    try {
      setMmfSettings(await api.settings.mmf.clearKey());
      flash("MyMiniFactory key cleared", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not clear the MyMiniFactory key", "err");
    }
  };

  const fetchOrganizeModels = async (url: string) => {
    const trimmed = url.trim();
    if (!trimmed) return;
    setOrganizeModelsLoading(true);
    setOrganizeModelsError(null);
    try {
      const result = await api.settings.aiOrganize.getModels(trimmed);
      setOrganizeModels(result.models);
    } catch (e: any) {
      setOrganizeModelsError(e?.message || "Could not reach endpoint");
      setOrganizeModels([]);
    } finally {
      setOrganizeModelsLoading(false);
    }
  };

  const saveOrganizeKey = async () => {
    const key = organizeKeyDraft.trim();
    if (!key) return;
    try {
      setOrganizeSettings(await api.settings.aiOrganize.setKey(key));
      setOrganizeKeyDraft("");
      setEditingOrganizeKey(false);
      flash("API key saved", "ok");
      // Re-fetch models — the key may have been required for auth.
      await fetchOrganizeModels(settings.ai_organize_url);
    } catch (e: any) {
      flash(e?.message || "Could not save the organizer API key", "err");
    }
  };

  const clearOrganizeKey = async () => {
    try {
      setOrganizeSettings(await api.settings.aiOrganize.clearKey());
      flash("API key cleared", "ok");
    } catch (e: any) {
      flash(e?.message || "Could not clear the organizer API key", "err");
    }
  };

  return (
    <div>
      <FlashBanner success={success} error={error} />

      {/* Anthropic */}
      <section className="mb-10">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Bot size={14} /> Anthropic API
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Bring your own Anthropic API key to generate guide drafts. The key is stored encrypted
          and never shown again — only that one is set.
        </p>

        <label className="block text-xs text-gray-400 mb-1">API key</label>
        {aiSettings?.key_set && !editingKey ? (
          <div className="flex items-center gap-2 mb-4">
            <span className="text-sm text-gray-300 bg-gray-900 border border-gray-800 rounded px-3 py-2">
              Key set <span className="text-gray-500">••••{aiSettings.key_hint?.replace(/^…/, "")}</span>
            </span>
            <button
              type="button"
              onClick={() => { setEditingKey(true); setAiKeyDraft(""); }}
              className="text-sm text-gray-300 hover:text-white border border-gray-700 rounded px-3 py-2"
            >
              Replace
            </button>
            <button
              type="button"
              onClick={clearAiKey}
              className="text-sm text-rose-300 hover:text-rose-200 border border-gray-700 hover:border-rose-800 rounded px-3 py-2"
            >
              Clear
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 mb-4">
            <input
              type="password"
              aria-label="Anthropic API key"
              value={aiKeyDraft}
              onChange={(e) => setAiKeyDraft(e.target.value)}
              placeholder="sk-ant-…"
              className="flex-1 bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
            />
            <button
              type="button"
              onClick={saveAiKey}
              disabled={!aiKeyDraft.trim()}
              className="text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded px-3 py-2 disabled:opacity-50"
            >
              Save
            </button>
            {aiSettings?.key_set && (
              <button
                type="button"
                onClick={() => { setEditingKey(false); setAiKeyDraft(""); }}
                className="text-sm text-gray-400 hover:text-gray-200 px-2 py-2"
              >
                Cancel
              </button>
            )}
          </div>
        )}

        <div className="flex flex-wrap gap-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1" htmlFor="ai-model">Model</label>
            <select
              id="ai-model"
              value={settings.ai_model || "claude-sonnet-4-6"}
              onChange={(e) => saveAiModel(e.target.value)}
              className="bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
            >
              <option value="claude-opus-4-8">Opus 4.8 — most capable</option>
              <option value="claude-sonnet-4-6">Sonnet 4.6 — balanced (default)</option>
              <option value="claude-haiku-4-5">Haiku 4.5 — fastest</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1" htmlFor="ai-effort">Effort</label>
            <select
              id="ai-effort"
              value={settings.ai_effort}
              onChange={(e) => saveAiEffort(e.target.value as AiEffort)}
              className="bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
            >
              <option value="low">Low — fastest (default)</option>
              <option value="medium">Medium — more reasoning</option>
              <option value="high">High — deepest reasoning</option>
            </select>
          </div>
        </div>
      </section>

      {/* AI Naming & Organizing */}
      <section className="mb-10">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Wand2 size={14} /> AI Naming &amp; Organizing
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Connect any OpenAI-compatible endpoint (Ollama, OpenAI, etc.) to automatically
          normalize part names, assign categories, and link presupported files on a per-model basis.
        </p>

        <label className="flex items-center gap-2 mb-4 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={settings.ai_organize_enabled}
            onChange={(e) => update({ ai_organize_enabled: e.target.checked }).catch(() =>
              flash("Could not update setting", "err")
            )}
            className="accent-indigo-500 w-4 h-4"
          />
          <span className="text-sm text-gray-300">Enable AI naming &amp; organizing</span>
        </label>

        {settings.ai_organize_enabled && (
          <div className="flex flex-col gap-4 pl-6 border-l border-gray-800">
            <div className="flex flex-wrap gap-4">
              <div className="flex-1 min-w-48">
                <label className="block text-xs text-gray-400 mb-1">Base URL</label>
                <input
                  type="text"
                  value={settings.ai_organize_url}
                  onChange={(e) => update({ ai_organize_url: e.target.value }).catch(() =>
                    flash("Could not update URL", "err")
                  )}
                  onBlur={(e) => fetchOrganizeModels(e.target.value)}
                  placeholder="http://localhost:11434"
                  className="w-full bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
                />
                <p className="text-xs text-gray-600 mt-1">Ollama default: <code className="text-gray-500">http://localhost:11434</code></p>
              </div>
              <div className="flex-1 min-w-40">
                <label className="block text-xs text-gray-400 mb-1 flex items-center gap-1.5">
                  Model
                  {organizeModelsLoading && (
                    <span className="text-gray-600 text-xs animate-pulse">fetching…</span>
                  )}
                </label>
                {organizeModels.length > 0 ? (
                  <select
                    value={settings.ai_organize_model}
                    onChange={(e) => update({ ai_organize_model: e.target.value }).catch(() =>
                      flash("Could not update model", "err")
                    )}
                    className="w-full bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
                  >
                    <option value="">-- Select a model --</option>
                    {organizeModels.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                    {settings.ai_organize_model && !organizeModels.includes(settings.ai_organize_model) && (
                      <option value={settings.ai_organize_model}>{settings.ai_organize_model} (current)</option>
                    )}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={settings.ai_organize_model}
                    onChange={(e) => update({ ai_organize_model: e.target.value }).catch(() =>
                      flash("Could not update model", "err")
                    )}
                    placeholder="llama3.2"
                    className="w-full bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
                  />
                )}
                {organizeModelsError && (
                  <p className="text-xs text-rose-400 mt-1">{organizeModelsError}</p>
                )}
              </div>
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">API key <span className="text-gray-600">(optional — Ollama doesn't require one)</span></label>
              {organizeSettings?.key_set && !editingOrganizeKey ? (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-300 bg-gray-900 border border-gray-800 rounded px-3 py-2">
                    Key set <span className="text-gray-500">••••{organizeSettings.key_hint?.replace(/^…/, "")}</span>
                  </span>
                  <button type="button" onClick={() => { setEditingOrganizeKey(true); setOrganizeKeyDraft(""); }}
                    className="text-sm text-gray-300 hover:text-white border border-gray-700 rounded px-3 py-2">
                    Replace
                  </button>
                  <button type="button" onClick={clearOrganizeKey}
                    className="text-sm text-rose-300 hover:text-rose-200 border border-gray-700 hover:border-rose-800 rounded px-3 py-2">
                    Clear
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <input
                    type="password"
                    aria-label="AI organizer API key"
                    value={organizeKeyDraft}
                    onChange={(e) => setOrganizeKeyDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") saveOrganizeKey(); }}
                    placeholder="sk-… or any string"
                    className="flex-1 max-w-sm bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
                  />
                  <button type="button" onClick={saveOrganizeKey} disabled={!organizeKeyDraft.trim()}
                    className="text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded px-3 py-2 disabled:opacity-50">
                    Save
                  </button>
                  {organizeSettings?.key_set && (
                    <button type="button" onClick={() => { setEditingOrganizeKey(false); setOrganizeKeyDraft(""); }}
                      className="text-sm text-gray-400 hover:text-gray-200 px-2 py-2">
                      Cancel
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {/* Cults3D */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Link2 size={14} /> Cults3D
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Connect your Cults3D account to enrich your STL library with creator details,
          model metadata, and thumbnails. API access is gated — request it in{" "}
          <code className="text-gray-500">#api-help</code> on the Cults3D Discord.
          Credentials are stored encrypted and never shown again.
        </p>

        {cultsSettings?.credentials_set && !editingCults ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-300 bg-gray-900 border border-gray-800 rounded px-3 py-2">
              Connected as <span className="text-gray-400">{cultsSettings.hint}</span>
            </span>
            <button
              type="button"
              onClick={() => { setEditingCults(true); setCultsUser(""); setCultsKey(""); }}
              className="text-sm text-gray-300 hover:text-white border border-gray-700 rounded px-3 py-2"
            >
              Replace
            </button>
            <button
              type="button"
              onClick={clearCultsCredentials}
              className="text-sm text-rose-300 hover:text-rose-200 border border-gray-700 hover:border-rose-800 rounded px-3 py-2"
            >
              Disconnect
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-2 max-w-sm">
            <input
              type="text"
              aria-label="Cults3D username"
              value={cultsUser}
              onChange={(e) => setCultsUser(e.target.value)}
              placeholder="Username"
              autoComplete="off"
              className="bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
            />
            <input
              type="password"
              aria-label="Cults3D API key"
              value={cultsKey}
              onChange={(e) => setCultsKey(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") saveCultsCredentials(); }}
              placeholder="API key"
              className="bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
            />
            <div className="flex gap-2">
              <button
                type="button"
                onClick={saveCultsCredentials}
                disabled={!cultsUser.trim() || !cultsKey.trim()}
                className="text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded px-3 py-2 disabled:opacity-50"
              >
                Save
              </button>
              {cultsSettings?.credentials_set && (
                <button
                  type="button"
                  onClick={() => { setEditingCults(false); setCultsUser(""); setCultsKey(""); }}
                  className="text-sm text-gray-400 hover:text-gray-200 px-2 py-2"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>
        )}
      </section>

      {/* MyMiniFactory */}
      <section className="mt-10">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Boxes size={14} /> MyMiniFactory
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Add a MyMiniFactory API key to enrich your STL library from their API — richer
          model metadata, images, tags and designer details than page scraping. Register an
          app at MyMiniFactory Settings → Developer to get a key. Stored encrypted and never
          shown again.
        </p>

        {mmfSettings?.key_set && !editingMmf ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-300 bg-gray-900 border border-gray-800 rounded px-3 py-2">
              Key set <span className="text-gray-500">••••{mmfSettings.key_hint?.replace(/^…/, "")}</span>
            </span>
            <button
              type="button"
              onClick={() => { setEditingMmf(true); setMmfKeyDraft(""); }}
              className="text-sm text-gray-300 hover:text-white border border-gray-700 rounded px-3 py-2"
            >
              Replace
            </button>
            <button
              type="button"
              onClick={clearMmfKey}
              className="text-sm text-rose-300 hover:text-rose-200 border border-gray-700 hover:border-rose-800 rounded px-3 py-2"
            >
              Clear
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 max-w-sm">
            <input
              type="password"
              aria-label="MyMiniFactory API key"
              value={mmfKeyDraft}
              onChange={(e) => setMmfKeyDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") saveMmfKey(); }}
              placeholder="API key"
              className="flex-1 bg-gray-900 border border-gray-800 rounded px-3 py-2 text-sm text-gray-100 focus:border-indigo-600 focus:outline-none"
            />
            <button
              type="button"
              onClick={saveMmfKey}
              disabled={!mmfKeyDraft.trim()}
              className="text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded px-3 py-2 disabled:opacity-50"
            >
              Save
            </button>
            {mmfSettings?.key_set && (
              <button
                type="button"
                onClick={() => { setEditingMmf(false); setMmfKeyDraft(""); }}
                className="text-sm text-gray-400 hover:text-gray-200 px-2 py-2"
              >
                Cancel
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

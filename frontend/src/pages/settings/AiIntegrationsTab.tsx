import { useEffect, useState } from "react";
import { Bot, Link2, Wand2, Plus, Pencil, Trash2, X } from "lucide-react";
import { api, AiApiConfig, CultsSettings, MmfSettings } from "../../api/client";
import { useAppSettings } from "../../context/AppSettingsContext";
import FlashBanner from "./FlashBanner";
import { useSettingsFlash } from "./useSettingsFlash";
import { errMsg } from "../../utils/err";

// ── Types ────────────────────────────────────────────────────────────────────

type ApiType = "anthropic" | "openai";

interface DraftConfig {
  name: string;
  api_type: ApiType;
  url: string;
  model: string;
  effort: string;
  request_timeout: number;
  batch_size: number | null;
  api_key: string;
}

const EMPTY_DRAFT: DraftConfig = {
  name: "",
  api_type: "anthropic",
  url: "",
  model: "",
  effort: "low",
  request_timeout: 10,
  batch_size: null,
  api_key: "",
};

const ANTHROPIC_MODELS = [
  { value: "claude-opus-4-8", label: "Opus 4.8 — most capable" },
  { value: "claude-sonnet-4-6", label: "Sonnet 4.6 — balanced" },
  { value: "claude-haiku-4-5", label: "Haiku 4.5 — fastest" },
];

// ── Shared field styles ───────────────────────────────────────────────────────

const INPUT = "w-full bg-panel border border-border-subtle rounded px-3 py-2 text-sm text-text-primary focus:border-indigo-600 focus:outline-none";
const SELECT = INPUT;
const BTN_PRIMARY = "text-sm bg-accent-end hover:bg-accent-start text-white rounded px-3 py-2 disabled:opacity-50";
const BTN_GHOST = "text-sm text-text-secondary hover:text-text-primary-alt border border-border rounded px-3 py-2";
const BTN_DANGER = "text-sm text-rose-300 hover:text-rose-200 border border-border hover:border-rose-800 rounded px-3 py-2";

// ── Config form (shared between Add and Edit) ─────────────────────────────────

function ConfigForm({
  draft,
  onChange,
  modelList,
  modelListLoading,
  modelListError,
  onFetchModels,
  keySet,
  keyHint,
  onClearKey,
  editingKey,
  onEditKey,
  onCancelKey,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  draft: DraftConfig;
  onChange: (patch: Partial<DraftConfig>) => void;
  modelList: string[];
  modelListLoading: boolean;
  modelListError: string | null;
  onFetchModels: (url: string) => void;
  keySet: boolean;
  keyHint: string | null;
  onClearKey: () => void;
  editingKey: boolean;
  onEditKey: () => void;
  onCancelKey: () => void;
  onSubmit: () => void;
  onCancel: () => void;
  submitLabel: string;
}) {
  return (
    <div className="flex flex-col gap-4">
      {/* Name + Type */}
      <div className="flex flex-wrap gap-4">
        <div className="flex-1 min-w-40">
          <label className="block text-xs text-text-secondary mb-1">Name</label>
          <input
            type="text"
            value={draft.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="e.g. Ollama Local, Anthropic Creative"
            className={INPUT}
          />
        </div>
        <div>
          <label className="block text-xs text-text-secondary mb-1">Type</label>
          <select
            value={draft.api_type}
            onChange={(e) => onChange({ api_type: e.target.value as ApiType })}
            className={SELECT}
          >
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI-compatible</option>
          </select>
        </div>
      </div>

      {/* OpenAI-specific: URL */}
      {draft.api_type === "openai" && (
        <div>
          <label className="block text-xs text-text-secondary mb-1">Base URL</label>
          <input
            type="text"
            value={draft.url}
            onChange={(e) => onChange({ url: e.target.value })}
            onBlur={(e) => onFetchModels(e.target.value)}
            placeholder="http://localhost:11434"
            className={INPUT}
          />
          <p className="text-xs text-text-muted mt-1">Ollama default: <code className="text-text-secondary-alt">http://localhost:11434</code></p>
        </div>
      )}

      {/* Model */}
      <div>
        <label className="block text-xs text-text-secondary mb-1 flex items-center gap-1.5">
          Model
          {modelListLoading && <span className="text-text-muted text-xs animate-pulse">fetching…</span>}
        </label>
        {draft.api_type === "anthropic" ? (
          <select value={draft.model} onChange={(e) => onChange({ model: e.target.value })} className={SELECT}>
            <option value="">-- Select --</option>
            {ANTHROPIC_MODELS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        ) : (
          <select
            value={draft.model}
            onChange={(e) => onChange({ model: e.target.value })}
            disabled={modelListLoading || modelList.length === 0}
            className={SELECT}
          >
            {modelListLoading ? (
              <option value="">Loading…</option>
            ) : modelList.length === 0 ? (
              <option value="">Enter a base URL above to load models</option>
            ) : (
              <>
                <option value="">-- Select a model --</option>
                {modelList.map((m) => <option key={m} value={m}>{m}</option>)}
                {draft.model && !modelList.includes(draft.model) && (
                  <option value={draft.model}>{draft.model} (current)</option>
                )}
              </>
            )}
          </select>
        )}
        {modelListError && <p className="text-xs text-rose-400 mt-1">{modelListError}</p>}
      </div>

      {/* Anthropic-specific: Effort */}
      {draft.api_type === "anthropic" && (
        <div>
          <label className="block text-xs text-text-secondary mb-1">Effort</label>
          <select value={draft.effort} onChange={(e) => onChange({ effort: e.target.value })} className={SELECT}>
            <option value="low">Low — fastest (default)</option>
            <option value="medium">Medium — more reasoning</option>
            <option value="high">High — deepest reasoning</option>
          </select>
        </div>
      )}

      {/* Request timeout — per connection. Remote endpoints (e.g. an Ollama box
          loading a model cold) can take far longer than a local one. */}
      <div>
        <label className="block text-xs text-text-secondary mb-1">
          Timeout <span className="text-text-muted ml-1">(seconds — raise for slow/remote endpoints)</span>
        </label>
        <input
          type="number"
          min={1}
          max={600}
          value={draft.request_timeout}
          onChange={(e) => onChange({ request_timeout: Number(e.target.value) })}
          className={`max-w-[8rem] ${INPUT}`}
        />
      </div>

      {/* AI Organize batch size — files per LLM request/batch. Blank uses the
          service's built-in default (currently 15 for "parts", 5 for "unit"). */}
      <div>
        <label className="block text-xs text-text-secondary mb-1">
          Organize batch size <span className="text-text-muted ml-1">(files per LLM call — blank uses the default)</span>
        </label>
        <input
          type="number"
          min={1}
          max={50}
          placeholder="default"
          value={draft.batch_size ?? ""}
          onChange={(e) => onChange({ batch_size: e.target.value === "" ? null : Number(e.target.value) })}
          className={`max-w-[8rem] ${INPUT}`}
        />
      </div>

      {/* API Key */}
      <div>
        <label className="block text-xs text-text-secondary mb-1">
          API key{draft.api_type === "openai" && <span className="text-text-muted ml-1">(optional — Ollama doesn't need one)</span>}
        </label>
        {keySet && !editingKey ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-text-primary-alt2 bg-panel border border-border-subtle rounded px-3 py-2">
              Key set <span className="text-text-secondary-alt">••••{keyHint?.replace(/^…/, "")}</span>
            </span>
            <button type="button" onClick={onEditKey} className={BTN_GHOST}>Replace</button>
            <button type="button" onClick={onClearKey} className={BTN_DANGER}>Clear</button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <input
              type="password"
              value={draft.api_key}
              onChange={(e) => onChange({ api_key: e.target.value })}
              onKeyDown={(e) => { if (e.key === "Enter") onSubmit(); }}
              placeholder={draft.api_type === "anthropic" ? "sk-ant-…" : "sk-… or any string"}
              className={`flex-1 max-w-sm ${INPUT}`}
            />
            {keySet && (
              <button type="button" onClick={onCancelKey} className="text-sm text-text-secondary hover:text-text-primary-alt px-2 py-2">
                Cancel
              </button>
            )}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          onClick={onSubmit}
          disabled={!draft.name.trim()}
          className={BTN_PRIMARY}
        >
          {submitLabel}
        </button>
        <button type="button" onClick={onCancel} className={BTN_GHOST}>Cancel</button>
      </div>
    </div>
  );
}

// ── Config card (compact + expand-to-edit) ─────────────────────────────────

function ConfigCard({
  config,
  onUpdated,
  onDeleted,
  flash,
}: {
  config: AiApiConfig;
  onUpdated: (c: AiApiConfig) => void;
  onDeleted: (id: number) => void;
  flash: (msg: string, type: "ok" | "err") => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState<DraftConfig>({
    name: config.name,
    api_type: config.api_type,
    url: config.url ?? "",
    model: config.model,
    effort: config.effort ?? "low",
    request_timeout: config.request_timeout ?? 10,
    batch_size: config.batch_size ?? null,
    api_key: "",
  });
  const [modelList, setModelList] = useState<string[]>([]);
  const [modelListLoading, setModelListLoading] = useState(false);
  const [modelListError, setModelListError] = useState<string | null>(null);
  const [editingKey, setEditingKey] = useState(false);
  const [localConfig, setLocalConfig] = useState(config);

  const fetchModels = async (url: string) => {
    if (!url.trim() || draft.api_type !== "openai") return;
    setModelListLoading(true);
    setModelListError(null);
    try {
      const r = await api.settings.aiOrganize.getModels(url);
      setModelList(r.models);
    } catch (e) {
      setModelListError(errMsg(e) || "Could not reach endpoint");
      setModelList([]);
    } finally {
      setModelListLoading(false);
    }
  };

  useEffect(() => {
    if (config.api_type === "openai" && config.url) fetchModels(config.url);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    try {
      const updated = await api.settings.aiApis.update(localConfig.id, {
        name: draft.name.trim(),
        url: draft.api_type === "openai" ? (draft.url.trim() || null) : null,
        model: draft.model,
        effort: draft.api_type === "anthropic" ? (draft.effort || null) : null,
        request_timeout: draft.request_timeout,
        batch_size: draft.batch_size,
        ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
      });
      setLocalConfig(updated);
      onUpdated(updated);
      setDraft((prev) => ({ ...prev, api_key: "" }));
      setEditingKey(false);
      setExpanded(false);
      flash(`"${updated.name}" updated`, "ok");
    } catch (e) {
      flash(errMsg(e) || "Could not save", "err");
    }
  };

  const clearKey = async () => {
    try {
      const updated = await api.settings.aiApis.clearKey(localConfig.id);
      setLocalConfig(updated);
      onUpdated(updated);
      flash("Key cleared", "ok");
    } catch (e) {
      flash(errMsg(e) || "Could not clear key", "err");
    }
  };

  const deleteConfig = async () => {
    try {
      await api.settings.aiApis.delete(localConfig.id);
      onDeleted(localConfig.id);
      flash(`"${localConfig.name}" removed`, "ok");
    } catch (e) {
      flash(errMsg(e) || "Could not delete", "err");
    }
  };

  if (!expanded) {
    return (
      <div className="flex items-center gap-3 px-4 py-3 bg-panel border border-border-subtle rounded-lg">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-text-primary-alt font-medium truncate">{localConfig.name}</span>
            <span className={`shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide ${
              localConfig.api_type === "anthropic"
                ? "bg-violet-900/60 text-violet-300"
                : "bg-sky-900/60 text-sky-300"
            }`}>
              {localConfig.api_type === "anthropic" ? "Anthropic" : "OpenAI-compat"}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-xs text-text-secondary-alt">
            {localConfig.model && <span>{localConfig.model}</span>}
            {localConfig.url && <span className="truncate max-w-[200px]">{localConfig.url}</span>}
            {localConfig.effort && localConfig.api_type === "anthropic" && <span>effort: {localConfig.effort}</span>}
            <span>timeout: {localConfig.request_timeout}s</span>
            {localConfig.batch_size != null && <span>batch: {localConfig.batch_size}</span>}
            <span>{localConfig.key_set ? `Key ••••${localConfig.key_hint?.replace(/^…/, "")}` : "No key"}</span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="shrink-0 text-text-secondary-alt hover:text-text-primary-alt transition-colors p-1"
          title="Edit"
        >
          <Pencil size={14} />
        </button>
        <button
          type="button"
          onClick={deleteConfig}
          className="shrink-0 text-text-muted hover:text-rose-400 transition-colors p-1"
          title="Delete"
        >
          <Trash2 size={14} />
        </button>
      </div>
    );
  }

  return (
    <div className="px-4 py-4 bg-panel border border-indigo-800/50 rounded-lg">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Edit API</span>
        <button type="button" onClick={() => setExpanded(false)} className="text-text-muted hover:text-text-primary-alt2">
          <X size={14} />
        </button>
      </div>
      <ConfigForm
        draft={draft}
        onChange={(p) => setDraft((prev) => ({ ...prev, ...p }))}
        modelList={modelList}
        modelListLoading={modelListLoading}
        modelListError={modelListError}
        onFetchModels={fetchModels}
        keySet={localConfig.key_set}
        keyHint={localConfig.key_hint}
        onClearKey={clearKey}
        editingKey={editingKey}
        onEditKey={() => setEditingKey(true)}
        onCancelKey={() => { setEditingKey(false); setDraft((prev) => ({ ...prev, api_key: "" })); }}
        onSubmit={save}
        onCancel={() => setExpanded(false)}
        submitLabel="Save changes"
      />
    </div>
  );
}

// ── Add-new form card ─────────────────────────────────────────────────────────

function AddConfigCard({
  onCreated,
  flash,
  onCancel,
}: {
  onCreated: (c: AiApiConfig) => void;
  flash: (msg: string, type: "ok" | "err") => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<DraftConfig>(EMPTY_DRAFT);
  const [modelList, setModelList] = useState<string[]>([]);
  const [modelListLoading, setModelListLoading] = useState(false);
  const [modelListError, setModelListError] = useState<string | null>(null);

  const fetchModels = async (url: string) => {
    if (!url.trim() || draft.api_type !== "openai") return;
    setModelListLoading(true);
    setModelListError(null);
    try {
      const r = await api.settings.aiOrganize.getModels(url);
      setModelList(r.models);
    } catch (e) {
      setModelListError(errMsg(e) || "Could not reach endpoint");
      setModelList([]);
    } finally {
      setModelListLoading(false);
    }
  };

  const create = async () => {
    if (!draft.name.trim()) return;
    try {
      const created = await api.settings.aiApis.create({
        name: draft.name.trim(),
        api_type: draft.api_type,
        url: draft.api_type === "openai" ? (draft.url.trim() || null) : null,
        model: draft.model,
        effort: draft.api_type === "anthropic" ? (draft.effort || null) : null,
        request_timeout: draft.request_timeout,
        batch_size: draft.batch_size,
        ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
      });
      flash(`"${created.name}" added`, "ok");
      onCreated(created);
    } catch (e) {
      flash(errMsg(e) || "Could not create", "err");
    }
  };

  return (
    <div className="px-4 py-4 bg-panel border border-dashed border-border rounded-lg">
      <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-4">New API</p>
      <ConfigForm
        draft={draft}
        onChange={(p) => setDraft((prev) => ({ ...prev, ...p }))}
        modelList={modelList}
        modelListLoading={modelListLoading}
        modelListError={modelListError}
        onFetchModels={fetchModels}
        keySet={false}
        keyHint={null}
        onClearKey={() => {}}
        editingKey={false}
        onEditKey={() => {}}
        onCancelKey={() => {}}
        onSubmit={create}
        onCancel={onCancel}
        submitLabel="Add API"
      />
    </div>
  );
}

// ── API selector for AI Functions ─────────────────────────────────────────────

function ApiSelector({
  value,
  configs,
  onChange,
}: {
  value: number | null;
  configs: AiApiConfig[];
  onChange: (id: number | null) => void;
}) {
  return (
    <div className="flex items-center gap-2 mt-2 ml-6">
      <label className="text-xs text-text-secondary-alt shrink-0">Use API</label>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="bg-panel border border-border-subtle rounded px-2 py-1.5 text-sm text-text-primary focus:border-indigo-600 focus:outline-none"
      >
        <option value="">— not configured —</option>
        {configs.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
            {c.api_type === "anthropic" ? " (Anthropic)" : " (OpenAI-compat)"}
          </option>
        ))}
      </select>
      {configs.length === 0 && (
        <span className="text-xs text-text-muted">Add an API above first</span>
      )}
    </div>
  );
}

// ── Main tab ──────────────────────────────────────────────────────────────────

export default function AiIntegrationsTab() {
  const { settings, update } = useAppSettings();
  const { success, error, flash } = useSettingsFlash();

  const [configs, setConfigs] = useState<AiApiConfig[]>([]);
  const [showAddForm, setShowAddForm] = useState(false);

  // Cults3D
  const [cultsSettings, setCultsSettings] = useState<CultsSettings | null>(null);
  const [cultsUser, setCultsUser] = useState("");
  const [cultsKey, setCultsKey] = useState("");
  const [editingCults, setEditingCults] = useState(false);

  // MyMiniFactory
  const [mmfSettings, setMmfSettings] = useState<MmfSettings | null>(null);
  const [mmfKeyDraft, setMmfKeyDraft] = useState("");
  const [editingMmf, setEditingMmf] = useState(false);

  useEffect(() => {
    let alive = true;
    api.settings.aiApis.list()
      .then((cs) => { if (alive) setConfigs(cs); })
      .catch(() => {});
    api.settings.cults.get()
      .then((s) => { if (alive) setCultsSettings(s); })
      .catch(() => {});
    api.settings.mmf.get()
      .then((s) => { if (alive) setMmfSettings(s); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

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
    } catch (e) {
      flash(errMsg(e) || "Could not save Cults3D credentials", "err");
    }
  };

  const clearCultsCredentials = async () => {
    try {
      setCultsSettings(await api.settings.cults.clearCredentials());
      flash("Cults3D credentials cleared", "ok");
    } catch (e) {
      flash(errMsg(e) || "Could not clear Cults3D credentials", "err");
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
    } catch (e) {
      flash(errMsg(e) || "Could not save the MyMiniFactory key", "err");
    }
  };

  const clearMmfKey = async () => {
    try {
      setMmfSettings(await api.settings.mmf.clearKey());
      flash("MyMiniFactory key cleared", "ok");
    } catch (e) {
      flash(errMsg(e) || "Could not clear the MyMiniFactory key", "err");
    }
  };

  return (
    <div>
      <FlashBanner success={success} error={error} />

      {/* ── AI APIs ─────────────────────────────────────────────────────── */}
      <section className="mb-10">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Bot size={14} /> AI APIs
        </h2>
        <p className="text-xs text-text-muted mb-4">
          Configure named AI API connections. Add as many as you need — different models, local
          instances, or separate keys for different purposes. Each AI Function below then picks
          which one to use.
        </p>

        <div className="flex flex-col gap-2 mb-3">
          {configs.map((c) => (
            <ConfigCard
              key={c.id}
              config={c}
              onUpdated={(updated) => setConfigs((prev) => prev.map((x) => x.id === updated.id ? updated : x))}
              onDeleted={(id) => setConfigs((prev) => prev.filter((x) => x.id !== id))}
              flash={flash}
            />
          ))}
        </div>

        {showAddForm ? (
          <AddConfigCard
            onCreated={(c) => {
              setConfigs((prev) => [...prev, c]);
              setShowAddForm(false);
            }}
            flash={flash}
            onCancel={() => setShowAddForm(false)}
          />
        ) : (
          <button
            type="button"
            onClick={() => setShowAddForm(true)}
            className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary-alt border border-dashed border-border hover:border-border-divider rounded-lg px-4 py-2.5 w-full transition-colors"
          >
            <Plus size={14} /> Add API
          </button>
        )}
      </section>

      {/* ── AI Functions ────────────────────────────────────────────────── */}
      <section className="mb-10">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4 flex items-center gap-1.5">
          <Wand2 size={14} /> AI Functions
        </h2>

        {/* Guide Drafts */}
        <div className="mb-6 pb-6 border-b border-border-subtle/60">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={settings.ai_guides_enabled}
              onChange={(e) => update({ ai_guides_enabled: e.target.checked }).catch(() =>
                flash("Could not update setting", "err")
              )}
              className="accent-indigo-500 w-4 h-4"
            />
            <span className="text-sm text-text-primary-alt2">AI Guide Drafts</span>
          </label>
          <p className="text-xs text-text-muted mt-1 ml-6">
            Generate painting guide drafts with an AI. The draft is always reviewed before saving.
          </p>
          {settings.ai_guides_enabled && (
            <ApiSelector
              value={settings.ai_guides_api}
              configs={configs}
              onChange={(id) => update({ ai_guides_api: id }).catch(() => flash("Could not update setting", "err"))}
            />
          )}
        </div>

        {/* Naming & Organizing */}
        <div>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={settings.ai_organize_enabled}
              onChange={(e) => update({ ai_organize_enabled: e.target.checked }).catch(() =>
                flash("Could not update setting", "err")
              )}
              className="accent-indigo-500 w-4 h-4"
            />
            <span className="text-sm text-text-primary-alt2">AI Naming &amp; Organizing</span>
          </label>
          <p className="text-xs text-text-muted mt-1 ml-6">
            Automatically normalize part names, assign categories, and link presupported files on a per-model basis.
          </p>
          {settings.ai_organize_enabled && (
            <ApiSelector
              value={settings.ai_organize_api}
              configs={configs}
              onChange={(id) => update({ ai_organize_api: id }).catch(() => flash("Could not update setting", "err"))}
            />
          )}
        </div>
      </section>

      {/* ── Metadata ────────────────────────────────────────────────────── */}
      <div className="border-t border-border-subtle mt-2 mb-8 pt-8">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-1 flex items-center gap-1.5">
          <Link2 size={14} /> Metadata
        </h2>
        <p className="text-xs text-text-muted mb-6">
          Third-party integrations for enriching your library with creator details, metadata, and thumbnails.
        </p>
      </div>

      {/* ── Cults3D ─────────────────────────────────────────────────────── */}
      <section className="mb-10">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-1">
          Cults3D
        </h2>
        <p className="text-xs text-text-muted mb-4">
          Connect your Cults3D account to enrich your STL library with creator details,
          model metadata, and thumbnails. API access is gated — request it in{" "}
          <code className="text-text-secondary-alt">#api-help</code> on the Cults3D Discord.
          Credentials are stored encrypted and never shown again.
        </p>

        {cultsSettings?.credentials_set && !editingCults ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-text-primary-alt2 bg-panel border border-border-subtle rounded px-3 py-2">
              Connected as <span className="text-text-secondary">{cultsSettings.hint}</span>
            </span>
            <button type="button" onClick={() => { setEditingCults(true); setCultsUser(""); setCultsKey(""); }} className={BTN_GHOST}>Replace</button>
            <button type="button" onClick={clearCultsCredentials} className={BTN_DANGER}>Disconnect</button>
          </div>
        ) : (
          <div className="flex flex-col gap-2 max-w-sm">
            <input type="text" aria-label="Cults3D username" value={cultsUser} onChange={(e) => setCultsUser(e.target.value)}
              placeholder="Username" autoComplete="off" className={INPUT} />
            <input type="password" aria-label="Cults3D API key" value={cultsKey} onChange={(e) => setCultsKey(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") saveCultsCredentials(); }} placeholder="API key" className={INPUT} />
            <div className="flex gap-2">
              <button type="button" onClick={saveCultsCredentials} disabled={!cultsUser.trim() || !cultsKey.trim()} className={BTN_PRIMARY}>Save</button>
              {cultsSettings?.credentials_set && (
                <button type="button" onClick={() => { setEditingCults(false); setCultsUser(""); setCultsKey(""); }} className={BTN_GHOST}>Cancel</button>
              )}
            </div>
          </div>
        )}
      </section>

      {/* ── MyMiniFactory ───────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-1">
          MyMiniFactory
        </h2>
        <p className="text-xs text-text-muted mb-4">
          Add a MyMiniFactory API key to enrich your STL library from their API — richer
          model metadata, images, tags and designer details than page scraping. Register an
          app at MyMiniFactory Settings → Developer to get a key. Stored encrypted and never
          shown again.
        </p>

        {mmfSettings?.key_set && !editingMmf ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-text-primary-alt2 bg-panel border border-border-subtle rounded px-3 py-2">
              Key set <span className="text-text-secondary-alt">••••{mmfSettings.key_hint?.replace(/^…/, "")}</span>
            </span>
            <button type="button" onClick={() => { setEditingMmf(true); setMmfKeyDraft(""); }} className={BTN_GHOST}>Replace</button>
            <button type="button" onClick={clearMmfKey} className={BTN_DANGER}>Clear</button>
          </div>
        ) : (
          <div className="flex items-center gap-2 max-w-sm">
            <input type="password" aria-label="MyMiniFactory API key" value={mmfKeyDraft} onChange={(e) => setMmfKeyDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") saveMmfKey(); }} placeholder="API key" className={`flex-1 ${INPUT}`} />
            <button type="button" onClick={saveMmfKey} disabled={!mmfKeyDraft.trim()} className={BTN_PRIMARY}>Save</button>
            {mmfSettings?.key_set && (
              <button type="button" onClick={() => { setEditingMmf(false); setMmfKeyDraft(""); }} className="text-sm text-text-secondary hover:text-text-primary-alt px-2 py-2">Cancel</button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

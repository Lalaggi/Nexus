import { useEffect, useState } from 'react';
import {
  BarChart3,
  Check,
  ChevronRight,
  Code,
  Copy,
  Delete,
  ExternalLink,
  FileText,
  KeyRound,
  Loader2,
  Plus,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Trash2,
  User,
  X,
} from 'lucide-react';
import type { CustomModel, SettingsSnapshot } from '../types';
import {
  addCustomModel,
  createNote,
  deleteCustomModel,
  deleteNote,
  listCustomModels,
  listNotes,
  type Note,
} from '../api';

export interface SettingsPatch {
  provider: 'auto' | 'nim' | 'openrouter';
  user_name: string;
  temperature: number;
  nim_api_key?: string;
  openrouter_api_key?: string;
  custom_instructions?: string;
  custom_model_id?: string;
  clear_nim?: boolean;
  clear_openrouter?: boolean;
}

export interface TestResult {
  ok: boolean;
  detail?: string;
  error?: string;
  label?: string;
  model_visible?: boolean;
}

type Category = 'provider' | 'personalisation' | 'stats';

const CATEGORIES: Array<{ id: Category; label: string; icon: React.ElementType }> = [
  { id: 'provider', label: 'Provider', icon: KeyRound },
  { id: 'personalisation', label: 'Personalisation', icon: User },
  { id: 'stats', label: 'Stats', icon: BarChart3 },
];

export default function SettingsDialog({
  open,
  settings,
  searxngOk,
  onClose,
  onSave,
  onTest,
  onNotify,
  onSignOut,
}: {
  open: boolean;
  settings: SettingsSnapshot | null;
  searxngOk: boolean | null;
  onClose: () => void;
  onSave: (patch: SettingsPatch) => Promise<void>;
  onTest: (provider: string) => Promise<TestResult>;
  onNotify: (message: string) => void;
  onSignOut?: () => void;
}) {
  const [provider, setProvider] = useState<'auto' | 'nim' | 'openrouter'>('auto');
  const [userName, setUserName] = useState('');
  const [temperature, setTemperature] = useState(0.6);
  const [nimKey, setNimKey] = useState('');
  const [openrouterKey, setOpenrouterKey] = useState('');
  const [customInstructions, setCustomInstructions] = useState('');
  const [clearNim, setClearNim] = useState(false);
  const [clearOpenrouter, setClearOpenrouter] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);
  const [category, setCategory] = useState<Category>('provider');
  const [customModelId, setCustomModelId] = useState('');

  // Custom models
  const [customModels, setCustomModels] = useState<CustomModel[]>([]);
  const [newModelName, setNewModelName] = useState('');
  const [newModelId, setNewModelId] = useState('');
  const [addingModel, setAddingModel] = useState(false);

  // Notes
  const [notes, setNotes] = useState<Note[]>([]);
  const [newNoteKey, setNewNoteKey] = useState('');
  const [newNoteValue, setNewNoteValue] = useState('');
  const [addingNote, setAddingNote] = useState(false);

  useEffect(() => {
    if (!open || !settings) return;
    setProvider(settings.provider);
    setUserName(settings.user_name);
    setTemperature(settings.temperature);
    setCustomInstructions(settings.custom_instructions);
    setCustomModelId(settings.custom_model_id);
    setNimKey('');
    setOpenrouterKey('');
    setClearNim(false);
    setClearOpenrouter(false);
    setTest(null);
    setCategory('provider');
    void refreshCustomModels();
    void refreshNotes();
  }, [open, settings]);

  const refreshNotes = async () => {
    try {
      const noteList = await listNotes();
      setNotes(noteList);
    } catch {
      /* ignore */
    }
  };

  const refreshCustomModels = async () => {
    try {
      const models = await listCustomModels();
      setCustomModels(models);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !settings) return null;

  const sandbox = settings.sandbox;

  const save = async () => {
    setSaving(true);
    try {
      await onSave({
        provider,
        user_name: userName.trim() || settings.user_name,
        temperature,
        nim_api_key: nimKey.trim() || undefined,
        openrouter_api_key: openrouterKey.trim() || undefined,
        custom_instructions: customInstructions.trim() || undefined,
        custom_model_id: customModelId.trim() || undefined,
        clear_nim: clearNim,
        clear_openrouter: clearOpenrouter,
      });
      setNimKey('');
      setOpenrouterKey('');
      setClearNim(false);
      setClearOpenrouter(false);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      setTest(await onTest(provider));
    } catch (error) {
      setTest({ ok: false, error: String(error) });
    } finally {
      setTesting(false);
    }
  };

  const addModel = async () => {
    const name = newModelName.trim();
    const modelId = newModelId.trim();
    if (!name || !modelId) return;
    setAddingModel(true);
    try {
      const result = await addCustomModel(name, modelId);
      if (result) {
        setNewModelName('');
        setNewModelId('');
        setCustomModels((prev) => [...prev, result]);
      }
    } catch {
      /* error shown by API or could add toast */
    } finally {
      setAddingModel(false);
    }
  };

  const removeModel = async (modelId: string) => {
    try {
      await deleteCustomModel(modelId);
      setCustomModels((prev) => prev.filter((m) => m.model_id !== modelId));
    } catch {
      /* ignore */
    }
  };

  const addNote = async () => {
    const key = newNoteKey.trim();
    const value = newNoteValue.trim();
    if (!key || !value) return;
    setAddingNote(true);
    try {
      const note = await createNote(key, value);
      setNotes((prev) => [...prev, note]);
      setNewNoteKey('');
      setNewNoteValue('');
    } catch (error) {
      onNotify(error instanceof Error ? error.message : 'Could not add note.');
    } finally {
      setAddingNote(false);
    }
  };

  const removeNote = async (key: string) => {
    try {
      await deleteNote(key);
      setNotes((prev) => prev.filter((n) => n.key !== key));
    } catch (error) {
      onNotify(error instanceof Error ? error.message : 'Could not remove note.');
    }
  };

  const Icon = CATEGORIES.find((c) => c.id === category)?.icon ?? KeyRound;

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label="Settings" onClick={(event) => event.stopPropagation()}>
        <header className="dialog-head">
          <div>
            <span className="sheet-kicker">Configuration</span>
            <h2>Settings</h2>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close settings">
            <X size={19} />
          </button>
        </header>

        <div className="dialog-body settings-layout">
          <nav className="settings-sidebar">
            {CATEGORIES.map((cat) => {
              const active = category === cat.id;
              const CatIcon = cat.icon;
              return (
                <button
                  key={cat.id}
                  type="button"
                  className={`settings-cat ${active ? 'is-active' : ''}`}
                  onClick={() => setCategory(cat.id)}
                >
                  <CatIcon size={15} />
                  <span>{cat.label}</span>
                  {active && <ChevronRight size={12} />}
                </button>
              );
            })}
          </nav>

          <main className="settings-content">
            {category === 'provider' && (
              <ProviderPanel
                settings={settings}
                provider={provider}
                setProvider={setProvider}
                nimKey={nimKey}
                setNimKey={setNimKey}
                openrouterKey={openrouterKey}
                setOpenrouterKey={setOpenrouterKey}
                customModelId={customModelId}
                setCustomModelId={setCustomModelId}
                clearNim={clearNim}
                setClearNim={setClearNim}
                clearOpenrouter={clearOpenrouter}
                setClearOpenrouter={setClearOpenrouter}
                runTest={runTest}
                testing={testing}
                test={test}
                customModels={customModels}
                newModelName={newModelName}
                setNewModelName={setNewModelName}
                newModelId={newModelId}
                setNewModelId={setNewModelId}
                addingModel={addingModel}
                addModel={addModel}
                removeModel={removeModel}
              />
            )}
            {category === 'personalisation' && (
              <PersonalisationPanel
                settings={settings}
                userName={userName}
                setUserName={setUserName}
                temperature={temperature}
                setTemperature={setTemperature}
                customInstructions={customInstructions}
                setCustomInstructions={setCustomInstructions}
                notes={notes}
                newNoteKey={newNoteKey}
                setNewNoteKey={setNewNoteKey}
                newNoteValue={newNoteValue}
                setNewNoteValue={setNewNoteValue}
                addingNote={addingNote}
                addNote={addNote}
                removeNote={removeNote}
              />
            )}
            {category === 'stats' && (
              <StatsPanel settings={settings} sandbox={sandbox} searxngOk={searxngOk} />
            )}
          </main>
        </div>

        <footer className="dialog-foot">
          <span className="dialog-hint">Changes apply to new messages.</span>
          <div className="dialog-actions">
            {onSignOut && (
              <button type="button" className="btn-ghost" onClick={() => { onClose(); onSignOut(); }}>
                Change server
              </button>
            )}
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="btn-primary" onClick={save} disabled={saving}>
              {saving ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
              Save changes
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function ProviderPanel({
  settings,
  provider,
  setProvider,
  nimKey,
  setNimKey,
  openrouterKey,
  setOpenrouterKey,
  customModelId,
  setCustomModelId,
  clearNim,
  setClearNim,
  clearOpenrouter,
  setClearOpenrouter,
  runTest,
  testing,
  test,
  customModels,
  newModelName,
  setNewModelName,
  newModelId,
  setNewModelId,
  addingModel,
  addModel,
  removeModel,
}: {
  settings: SettingsSnapshot;
  provider: 'auto' | 'nim' | 'openrouter';
  setProvider: (value: 'auto' | 'nim' | 'openrouter') => void;
  nimKey: string;
  setNimKey: (value: string) => void;
  openrouterKey: string;
  setOpenrouterKey: (value: string) => void;
  customModelId: string;
  setCustomModelId: (value: string) => void;
  clearNim: boolean;
  setClearNim: (value: boolean) => void;
  clearOpenrouter: boolean;
  setClearOpenrouter: (value: boolean) => void;
  runTest: () => void;
  testing: boolean;
  test: TestResult | null;
  customModels: CustomModel[];
  newModelName: string;
  setNewModelName: (value: string) => void;
  newModelId: string;
  setNewModelId: (value: string) => void;
  addingModel: boolean;
  addModel: () => void;
  removeModel: (modelId: string) => void;
}) {
  return (
    <section className="settings-section">
      <div className="section-title">
        <KeyRound size={17} />
        <h3>Model provider</h3>
      </div>
      <p className="section-note">
        One curated model (Nemotron 3.5 VL Super), served by either NVIDIA NIM or OpenRouter. Auto
        uses NIM when a key is present, then falls back to OpenRouter.
      </p>

      <div className="provider-grid">
        {(
          [
            ['auto', 'Auto', 'Best available key'],
            ['nim', 'NVIDIA NIM', 'Free developer credits'],
            ['openrouter', 'OpenRouter', 'Free :free endpoint'],
          ] as const
        ).map(([value, label, hint]) => (
          <button
            key={value}
            type="button"
            className={`provider-card ${provider === value ? 'is-active' : ''}`}
            onClick={() => setProvider(value)}
          >
            <span className="provider-check">{provider === value && <Check size={13} />}</span>
            <strong>{label}</strong>
            <span>{hint}</span>
          </button>
        ))}
      </div>

      <div className="key-grid">
        <label className="field">
          <span className="field-label">
            NVIDIA NIM API key
            {settings.keys.nim.set && !clearNim && <em>saved {settings.keys.nim.hint}</em>}
          </span>
          <input
            type="password"
            value={nimKey}
            onChange={(event) => {
              setNimKey(event.target.value);
              if (event.target.value) setClearNim(false);
            }}
            placeholder={settings.keys.nim.set ? 'Paste a new key to replace' : 'nvapi-…'}
            autoComplete="off"
            spellCheck={false}
          />
          <span className="field-foot">
            <a href={settings.providers.find((p) => p.id === 'nim')?.docs} target="_blank" rel="noreferrer">
              Get a free NIM key <ExternalLink size={11} />
            </a>
            {settings.keys.nim.set && (
              <button
                type="button"
                className={clearNim ? 'danger' : ''}
                onClick={() => setClearNim(!clearNim)}
              >
                {clearNim ? 'Will be removed' : 'Remove'}
              </button>
            )}
          </span>
        </label>

        <label className="field">
          <span className="field-label">
            OpenRouter API key
            {settings.keys.openrouter.set && !clearOpenrouter && (
              <em>saved {settings.keys.openrouter.hint}</em>
            )}
          </span>
          <input
            type="password"
            value={openrouterKey}
            onChange={(event) => {
              setOpenrouterKey(event.target.value);
              if (event.target.value) setClearOpenrouter(false);
            }}
            placeholder={settings.keys.openrouter.set ? 'Paste a new key to replace' : 'sk-or-…'}
            autoComplete="off"
            spellCheck={false}
          />
          <span className="field-foot">
            <a
              href={settings.providers.find((p) => p.id === 'openrouter')?.docs}
              target="_blank"
              rel="noreferrer"
            >
              Get an OpenRouter key <ExternalLink size={11} />
            </a>
            {settings.keys.openrouter.set && (
              <button
                type="button"
                className={clearOpenrouter ? 'danger' : ''}
                onClick={() => setClearOpenrouter(!clearOpenrouter)}
              >
                {clearOpenrouter ? 'Will be removed' : 'Remove'}
              </button>
            )}
          </span>
        </label>
      </div>

      <label className="field">
        <span className="field-label">Default model ID</span>
        <input
          type="text"
          value={customModelId}
          onChange={(event) => setCustomModelId(event.target.value)}
          placeholder="e.g. nvidia/nemotron-3.5-super-vl-120b-a12b"
          spellCheck={false}
        />
        <span className="field-foot">
          Override the default model ID. Leave empty to use the provider default.
        </span>
      </label>

      <div className="section-title" style={{ marginTop: 20 }}>
        <Plus size={17} />
        <h3>Add custom model</h3>
      </div>
      <p className="section-note">
        Add any model ID from NIM or OpenRouter so it appears in the message box model picker.
      </p>
      <div className="two-col">
        <label className="field">
          <span className="field-label">Name</span>
          <input
            type="text"
            value={newModelName}
            onChange={(event) => setNewModelName(event.target.value)}
            placeholder="e.g. My Nemotron"
          />
        </label>
        <label className="field">
          <span className="field-label">Model ID</span>
          <input
            type="text"
            value={newModelId}
            onChange={(event) => setNewModelId(event.target.value)}
            placeholder="e.g. nvidia/nemotron-3.5-super-vl-120b-a12b"
          />
        </label>
      </div>
      <div className="test-row">
        <button
          type="button"
          className="btn-tonal"
          onClick={addModel}
          disabled={addingModel || !newModelName.trim() || !newModelId.trim()}
        >
          {addingModel ? <Loader2 size={15} className="spin" /> : <Plus size={15} />}
          Add model
        </button>
      </div>

      {customModels.length > 0 && (
        <div className="settings-section">
          <div className="section-title">
            <FileText size={17} />
            <h3>Your custom models</h3>
          </div>
          <div className="custom-model-list">
            {customModels.map((model) => (
              <div key={model.model_id} className="custom-model-item">
                <span className="custom-model-name">{model.name}</span>
                <code className="custom-model-id">{model.model_id}</code>
                <button
                  type="button"
                  className="icon-btn danger"
                  onClick={() => removeModel(model.model_id)}
                  aria-label={`Remove ${model.name}`}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="test-row">
        <button type="button" className="btn-tonal" onClick={runTest} disabled={testing}>
          {testing ? <Loader2 size={15} className="spin" /> : <KeyRound size={15} />}
          Test connection
        </button>
        {test && (
          <span className={`test-result ${test.ok ? 'ok' : 'bad'}`}>
            {test.ok ? <Check size={14} /> : <ShieldAlert size={14} />}
            {test.ok ? test.detail : test.error}
          </span>
        )}
      </div>
    </section>
  );
}

function PersonalisationPanel({
  settings,
  userName,
  setUserName,
  temperature,
  setTemperature,
  customInstructions,
  setCustomInstructions,
  notes,
  newNoteKey,
  setNewNoteKey,
  newNoteValue,
  setNewNoteValue,
  addingNote,
  addNote,
  removeNote,
}: {
  settings: SettingsSnapshot;
  userName: string;
  setUserName: (value: string) => void;
  temperature: number;
  setTemperature: (value: number) => void;
  customInstructions: string;
  setCustomInstructions: (value: string) => void;
  notes: Note[];
  newNoteKey: string;
  setNewNoteKey: (value: string) => void;
  newNoteValue: string;
  setNewNoteValue: (value: string) => void;
  addingNote: boolean;
  addNote: () => void;
  removeNote: (key: string) => void;
}) {
  return (
    <>
      <section className="settings-section">
        <div className="section-title">
          <User size={17} />
          <h3>Assistant</h3>
        </div>
        <div className="two-col">
          <label className="field">
            <span className="field-label">Your name</span>
            <input
              type="text"
              value={userName}
              onChange={(event) => setUserName(event.target.value)}
              maxLength={60}
            />
          </label>
          <label className="field">
            <span className="field-label">
              Temperature <em>{temperature.toFixed(1)}</em>
            </span>
            <input
              type="range"
              min={0}
              max={1.5}
              step={0.1}
              value={temperature}
              onChange={(event) => setTemperature(Number(event.target.value))}
            />
          </label>
        </div>
        <p className="section-note">
          {settings.model.name} · {settings.model.subtitle}. Up to {settings.max_tool_steps} tool
          steps per turn.
        </p>
      </section>

      <section className="settings-section">
        <div className="section-title">
          <FileText size={17} />
          <h3>Custom instructions / About me</h3>
        </div>
        <textarea
          className="custom-instructions"
          value={customInstructions}
          onChange={(event) => setCustomInstructions(event.target.value)}
          rows={6}
          placeholder="e.g. You mainly use nvim as your code editor. Never recommend nano. Prefer concise answers."
          spellCheck={false}
        />
        <p className="section-note">
          Permanent instructions that are included in every conversation. Use these to set lasting
          preferences (for example, your preferred editor, operating system, or answer style). Keep
          it short — these are sent with every message.
        </p>
      </section>

      <section className="settings-section" style={{ marginTop: 20 }}>
        <div className="section-title">
          <ShieldAlert size={17} />
          <h3>User notes (model memory)</h3>
        </div>
        <p className="section-note">
          These are facts the assistant remembers about you across conversations. The model may
          have written some of these itself — review and remove anything incorrect or outdated.
        </p>
        {notes.length > 0 ? (
          <div className="custom-model-list">
            {notes.map((note) => (
              <div key={note.key} className="custom-model-item">
                <span className="custom-model-name">{note.key}</span>
                <span className="custom-model-id" title={note.value}>
                  {note.value}
                </span>
                <button
                  type="button"
                  className="icon-btn danger"
                  onClick={() => removeNote(note.key)}
                  aria-label={`Remove note ${note.key}`}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="section-note">No user notes saved yet.</p>
        )}
        <div className="two-col" style={{ marginTop: 10 }}>
          <label className="field">
            <span className="field-label">Key</span>
            <input
              type="text"
              value={newNoteKey}
              onChange={(event) => setNewNoteKey(event.target.value)}
              placeholder="e.g. editor"
              spellCheck={false}
            />
          </label>
          <label className="field">
            <span className="field-label">Value</span>
            <input
              type="text"
              value={newNoteValue}
              onChange={(event) => setNewNoteValue(event.target.value)}
              placeholder="e.g. prefers neovim"
              spellCheck={false}
            />
          </label>
        </div>
        <div className="test-row">
          <button
            type="button"
            className="btn-tonal"
            onClick={addNote}
            disabled={addingNote || !newNoteKey.trim() || !newNoteValue.trim()}
          >
            {addingNote ? <Loader2 size={15} className="spin" /> : <Plus size={15} />}
            Add note
          </button>
        </div>
      </section>
    </>
  );
}

function StatsPanel({
  settings,
  sandbox,
  searxngOk,
}: {
  settings: SettingsSnapshot;
  sandbox: SettingsSnapshot['sandbox'];
  searxngOk: boolean | null;
}) {
  return (
    <>
      <section className="settings-section">
        <div className="section-title">
          <Terminal size={17} />
          <h3>Code sandbox</h3>
          <span className={`status-pill ${sandbox.available ? 'good' : 'warn'}`}>
            {sandbox.available ? <ShieldCheck size={13} /> : <ShieldAlert size={13} />}
            {sandbox.available ? 'Ready' : 'Not ready'}
          </span>
        </div>
        <p className="section-note">{sandbox.detail}</p>
        <div className="kv">
          <span>Mode</span>
          <code>{sandbox.mode}</code>
        </div>
        {sandbox.version && (
          <div className="kv">
            <span>Runtime</span>
            <code>{sandbox.version}</code>
          </div>
        )}
        <div className="kv">
          <span>Image</span>
          <code>{sandbox.image_name}</code>
        </div>
        {!sandbox.available && (
          <div className="command-box">
            <code>./scripts/build-sandbox.sh</code>
          </div>
        )}
        <p className="section-note tiny">
          Rootless Podman · all capabilities dropped · read-only root · memory and PID limits ·
          LAN/host egress blocked by nftables (when dedicated user is set up).
        </p>
      </section>

      <section className="settings-section">
        <div className="section-title">
          <BarChart3 size={17} />
          <h3>Storage & search</h3>
        </div>
        <div className="kv">
          <span>Uploads</span>
          <code>{settings.paths.uploads}</code>
        </div>
        <div className="kv">
          <span>Outputs</span>
          <code>{settings.paths.outputs}</code>
        </div>
        <div className="kv">
          <span>SearXNG</span>
          <span className={`inline-status ${searxngOk === false ? 'bad' : 'good'}`}>
            {searxngOk === null ? 'Checking…' : searxngOk ? 'Connected' : 'Unreachable'}
          </span>
        </div>
        <p className="section-note tiny">
          API keys are stored in the local SQLite database. For extra safety set
          <code> NVIDIA_API_KEY </code> or <code> OPENROUTER_API_KEY </code> in <code>.env</code>{' '}
          instead.
        </p>
      </section>
    </>
  );
}

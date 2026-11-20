import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BarChart3,
  Badge,
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
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Star,
  Terminal,
  Trash2,
  User,
  X,
} from 'lucide-react';
import type { CatalogModel, CustomModel, ProviderInfo, SettingsSnapshot } from '../types';
import {
  addCatalogModel,
  addCustomModel,
  createNote,
  deleteCatalogModel,
  deleteCustomModel,
  deleteNote,
  listCatalogModels,
  listCustomModels,
  listNotes,
  setCatalogModelDefault,
  syncCatalogModels,
  toggleCatalogModel,
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

type Category = 'provider' | 'personalisation' | 'stats' | 'app';

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
  // Which category panel is active on desktop (two-column layout).
  const [category, setCategory] = useState<Category>('provider');
  // Which cards are expanded on mobile (independent collapsible sections).
  const [openCards, setOpenCards] = useState<Record<Category, boolean>>({
    provider: true,
    personalisation: false,
    stats: false,
    app: false,
  });
  // Narrow-screen (phone) layout: below ~901px we use a bottom sheet + cards.
  const [narrow, setNarrow] = useState(typeof window !== 'undefined' && window.innerWidth <= 900);
  // One ref per collapsible card so we can measure content height for animation.
  const cardRefs = {
    provider: useRef<HTMLDetailsElement>(null),
    personalisation: useRef<HTMLDetailsElement>(null),
    stats: useRef<HTMLDetailsElement>(null),
    app: useRef<HTMLDetailsElement>(null),
  };

  // Smoothly expand/collapse a card's body by measuring its content height.
  const animateCard = useCallback((id: Category, isOpen: boolean) => {
    const el = cardRefs[id].current;
    if (!el) return;
    const body = el.querySelector('.settings-card-body') as HTMLElement | null;
    if (!body) return;
    if (isOpen) {
      body.style.maxHeight = `${body.scrollHeight}px`;
    } else {
      body.style.maxHeight = '0';
    }
  }, []);

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth <= 900);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const [customModelId, setCustomModelId] = useState('');

  // Model catalog
  const [catalogModels, setCatalogModels] = useState<CatalogModel[]>([]);
  const [catalogSearch, setCatalogSearch] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [addModelProvider, setAddModelProvider] = useState<'nim' | 'openrouter'>('nim');
  const [addModelId, setAddModelId] = useState('');
  const [addModelName, setAddModelName] = useState('');
  const [addingCatalogModel, setAddingCatalogModel] = useState(false);

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
    setCatalogModels(settings.models);
    void refreshCustomModels();
    void refreshNotes();
    // Animate any initially-open cards so they render at full height.
    Object.entries(openCards).forEach(([id, isOpen]) => {
      if (isOpen) animateCard(id as Category, true);
    });
  }, [open, settings, animateCard]);

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

  const handleSyncCatalog = async () => {
    setSyncing(true);
    try {
      await syncCatalogModels();
      onNotify('Model catalog synced from OpenRouter.');
    } catch (error) {
      onNotify(error instanceof Error ? error.message : 'Catalog sync failed.');
    } finally {
      setSyncing(false);
    }
  };

  const handleToggleCatalog = async (catalog_id: string, enabled: boolean) => {
    setCatalogModels(
      catalogModels.map((m) =>
        m.id === catalog_id ? { ...m, enabled } : m,
      ),
    );
    try {
      await toggleCatalogModel(catalog_id, enabled);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : 'Could not update model.');
    }
  };

  const handleSetDefaultCatalog = async (catalog_id: string) => {
    setCatalogModels(
      catalogModels.map((m) => ({ ...m, is_default: m.id === catalog_id })),
    );
    try {
      await setCatalogModelDefault(catalog_id);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : 'Could not set default model.');
    }
  };

  const handleAddCatalogModel = async () => {
    const provider = addModelProvider;
    const modelId = addModelId.trim();
    const name = addModelName.trim() || undefined;
    if (!modelId) return;
    setAddingCatalogModel(true);
    try {
      const entry = await addCatalogModel({ provider, model_id: modelId, name });
      setCatalogModels((prev) => [...prev, entry]);
      setAddModelId('');
      setAddModelName('');
      onNotify(`Added ${entry.name} to the catalog.`);
    } catch (error) {
      onNotify(error instanceof Error ? error.message : 'Could not add model.');
    } finally {
      setAddingCatalogModel(false);
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

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        onClick={(event) => event.stopPropagation()}
      >
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
          {narrow ? (
            <div className="settings-cards">
              <details
                ref={cardRefs.provider}
                className="settings-card"
                open={openCards.provider}
                onToggle={(event) => {
                  const isOpen = (event.target as HTMLDetailsElement).open;
                  setOpenCards((prev) => ({ ...prev, provider: isOpen }));
                  animateCard('provider', isOpen);
                }}
              >
                <summary className="settings-card-summary">
                  <KeyRound size={16} />
                  <span>Provider</span>
                </summary>
                <div className="settings-card-body">
                  <ProviderPanel
                    settings={settings}
                    provider={provider}
                    setProvider={setProvider}
                    nimKey={nimKey}
                    setNimKey={setNimKey}
                    openrouterKey={openrouterKey}
                    setOpenrouterKey={setOpenrouterKey}
                    clearNim={clearNim}
                    setClearNim={setClearNim}
                    clearOpenrouter={clearOpenrouter}
                    setClearOpenrouter={setClearOpenrouter}
                    runTest={runTest}
                    testing={testing}
                    test={test}
                  />
                  <ModelCatalogPanel
                    settings={settings}
                    catalogModels={catalogModels}
                    setCatalogModels={setCatalogModels}
                    catalogSearch={catalogSearch}
                    setCatalogSearch={setCatalogSearch}
                    syncing={syncing}
                    handleSyncCatalog={handleSyncCatalog}
                    handleToggleCatalog={handleToggleCatalog}
                    handleSetDefaultCatalog={handleSetDefaultCatalog}
                    handleAddCatalogModel={handleAddCatalogModel}
                    addModelProvider={addModelProvider}
                    setAddModelProvider={setAddModelProvider}
                    addModelId={addModelId}
                    setAddModelId={setAddModelId}
                    addModelName={addModelName}
                    setAddModelName={setAddModelName}
                    addingCatalogModel={addingCatalogModel}
                  />
                </div>
              </details>

              <details
                ref={cardRefs.personalisation}
                className="settings-card"
                open={openCards.personalisation}
                onToggle={(event) => {
                  const isOpen = (event.target as HTMLDetailsElement).open;
                  setOpenCards((prev) => ({ ...prev, personalisation: isOpen }));
                  animateCard('personalisation', isOpen);
                }}
              >
                <summary className="settings-card-summary">
                  <User size={16} />
                  <span>Personalisation</span>
                </summary>
                <div className="settings-card-body">
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
                </div>
              </details>

              <details
                ref={cardRefs.stats}
                className="settings-card"
                open={openCards.stats}
                onToggle={(event) => {
                  const isOpen = (event.target as HTMLDetailsElement).open;
                  setOpenCards((prev) => ({ ...prev, stats: isOpen }));
                  animateCard('stats', isOpen);
                }}
              >
                <summary className="settings-card-summary">
                  <BarChart3 size={16} />
                  <span>Stats</span>
                </summary>
                <div className="settings-card-body">
                  <StatsPanel settings={settings} sandbox={sandbox} searxngOk={searxngOk} />
                </div>
              </details>

              {/* Mobile-only: App Settings card with Change Server / sign out. */}
              <details
                ref={cardRefs.app}
                className="settings-card"
                open={openCards.app}
                onToggle={(event) => {
                  const isOpen = (event.target as HTMLDetailsElement).open;
                  setOpenCards((prev) => ({ ...prev, app: isOpen }));
                  animateCard('app', isOpen);
                }}
              >
                <summary className="settings-card-summary">
                  <Code size={16} />
                  <span>App Settings</span>
                </summary>
                <div className="settings-card-body">
                  {onSignOut && (
                    <div className="settings-section">
                      <div className="section-title">
                        <ExternalLink size={16} />
                        <h3>Server</h3>
                      </div>
                      <button
                        type="button"
                        className="btn-ghost"
                        onClick={() => { onClose(); onSignOut(); }}
                      >
                        Change server
                      </button>
                    </div>
                  )}
                </div>
              </details>
            </div>
          ) : (
            <>
              {/* Desktop/tablet: keep the existing two-column sidebar layout. */}
              <nav className="settings-sidebar">
                {CATEGORIES.filter((cat) => cat.id !== 'app').map((cat) => {
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
                  <>
                    <ProviderPanel
                      settings={settings}
                      provider={provider}
                      setProvider={setProvider}
                      nimKey={nimKey}
                      setNimKey={setNimKey}
                      openrouterKey={openrouterKey}
                      setOpenrouterKey={setOpenrouterKey}
                      clearNim={clearNim}
                      setClearNim={setClearNim}
                      clearOpenrouter={clearOpenrouter}
                      setClearOpenrouter={setClearOpenrouter}
                      runTest={runTest}
                      testing={testing}
                      test={test}
                    />
                    <ModelCatalogPanel
                      settings={settings}
                      catalogModels={catalogModels}
                      setCatalogModels={setCatalogModels}
                      catalogSearch={catalogSearch}
                      setCatalogSearch={setCatalogSearch}
                      syncing={syncing}
                      handleSyncCatalog={handleSyncCatalog}
                      handleToggleCatalog={handleToggleCatalog}
                      handleSetDefaultCatalog={handleSetDefaultCatalog}
                      handleAddCatalogModel={handleAddCatalogModel}
                      addModelProvider={addModelProvider}
                      setAddModelProvider={setAddModelProvider}
                      addModelId={addModelId}
                      setAddModelId={setAddModelId}
                      addModelName={addModelName}
                      setAddModelName={setAddModelName}
                      addingCatalogModel={addingCatalogModel}
                    />
                  </>
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
            </>
          )}
        </div>

        <footer className="dialog-foot">
          <div className="dialog-actions">
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
  clearNim,
  setClearNim,
  clearOpenrouter,
  setClearOpenrouter,
  runTest,
  testing,
  test,
}: {
  settings: SettingsSnapshot;
  provider: 'auto' | 'nim' | 'openrouter';
  setProvider: (value: 'auto' | 'nim' | 'openrouter') => void;
  nimKey: string;
  setNimKey: (value: string) => void;
  openrouterKey: string;
  setOpenrouterKey: (value: string) => void;
  clearNim: boolean;
  setClearNim: (value: boolean) => void;
  clearOpenrouter: boolean;
  setClearOpenrouter: (value: boolean) => void;
  runTest: () => void;
  testing: boolean;
  test: TestResult | null;
}) {
  return (
    <section className="settings-section provider-section">
      <div className="section-title">
        <KeyRound size={17} />
        <h3>Model provider</h3>
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

function ModelCatalogPanel({
  settings,
  catalogModels,
  setCatalogModels,
  catalogSearch,
  setCatalogSearch,
  syncing,
  handleSyncCatalog,
  handleToggleCatalog,
  handleSetDefaultCatalog,
  handleAddCatalogModel,
  addModelProvider,
  setAddModelProvider,
  addModelId,
  setAddModelId,
  addModelName,
  setAddModelName,
  addingCatalogModel,
}: {
  settings: SettingsSnapshot | null;
  catalogModels: CatalogModel[];
  setCatalogModels: (value: CatalogModel[]) => void;
  catalogSearch: string;
  setCatalogSearch: (value: string) => void;
  syncing: boolean;
  handleSyncCatalog: () => void;
  handleToggleCatalog: (catalog_id: string, enabled: boolean) => void;
  handleSetDefaultCatalog: (catalog_id: string) => void;
  handleAddCatalogModel: () => void;
  addModelProvider: 'nim' | 'openrouter';
  setAddModelProvider: React.Dispatch<React.SetStateAction<'nim' | 'openrouter'>>;
  addModelId: string;
  setAddModelId: React.Dispatch<React.SetStateAction<string>>;
  addModelName: string;
  setAddModelName: React.Dispatch<React.SetStateAction<string>>;
  addingCatalogModel: boolean;
}) {
  const providerById = new Map<string, ProviderInfo>(
    (settings?.providers ?? []).map((p) => [p.id, p]),
  );
  const available = new Set<string>(
    (settings?.providers ?? []).filter((p) => p.available).map((p) => p.id),
  );
  const q = catalogSearch.trim().toLowerCase();

  const providerName = (id: string) => providerById.get(id)?.label ?? id;

  const defaultModel = catalogModels.find((m) => m.is_default);
  const enabledModels = catalogModels.filter((m) => m.enabled && !m.is_default);
  const disabledModels = catalogModels.filter((m) => !m.enabled);

  const sortByName = (a: CatalogModel, b: CatalogModel) =>
    a.name.localeCompare(b.name);

  const [showAll, setShowAll] = useState(false);

  // When searching, show all matching models regardless of enabled state.
  // Otherwise: default first, then enabled alphabetical, then disabled
  // (only when Show all has been clicked).
  const visibleCatalog = useMemo(() => {
    const hasSearch = q.length > 0;
    let items: CatalogModel[] = [];
    if (defaultModel) items.push(defaultModel);
    items = items.concat(enabledModels.sort(sortByName));
    if (hasSearch || showAll) {
      items = items.concat(disabledModels.sort(sortByName));
    }
    if (!hasSearch) return items;
    return items.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.model_id.toLowerCase().includes(q) ||
        m.provider.toLowerCase().includes(q),
    );
  }, [catalogModels, defaultModel, enabledModels, disabledModels, showAll, q]);

  const starTitle = (model: CatalogModel) => {
    if (!model.enabled) return 'Enable this model to make it the default';
    return model.is_default ? 'Default model' : 'Set as default';
  };

  return (
    <section className="settings-section catalog-section">
      <div className="section-title">
        <FileText size={17} />
        <h3>Model catalog</h3>
      </div>
      <p className="section-note">
        Enable the models you want to use and pick a default (filled star). Only
        enabled models appear in the message composer. The model ID shown is
        what's sent to the provider API — it is never renamed.
      </p>
      <div className="catalog-toolbar">
        <button
          type="button"
          className="btn-tonal"
          onClick={handleSyncCatalog}
          disabled={syncing}
        >
          {syncing ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
          Sync from OpenRouter
        </button>
        <div className="catalog-search">
          <Search size={16} />
          <input
            type="text"
            value={catalogSearch}
            onChange={(event) => setCatalogSearch(event.target.value)}
            placeholder="Search for a model…"
          />
        </div>
      </div>
      {visibleCatalog.length === 0 ? (
        <p className="section-note">No models match your search.</p>
      ) : (
        <>
          {visibleCatalog.map((model) => {
            const isDefault = model.is_default;
            const isEnabled = model.enabled;
            const showStar = isEnabled && !isDefault;
            const provider = providerName(model.provider);
            return (
              <div
                key={model.id}
                className={`catalog-card ${isEnabled ? '' : 'catalog-card-disabled'}`}
              >
                <div className="catalog-card-row1">
                  <span className="catalog-card-name">{model.name}</span>
                  <button
                    type="button"
                    className={`catalog-star ${isDefault ? 'filled' : ''}`}
                    disabled={!isEnabled}
                    onClick={() => {
                      if (!isEnabled) return;
                      handleSetDefaultCatalog(model.id);
                    }}
                    aria-label={starTitle(model)}
                    title={starTitle(model)}
                  >
                    {isDefault ? (
                      <Star size={16} className="star-filled" />
                    ) : showStar ? (
                      <Star size={16} className="star-empty" />
                    ) : null}
                  </button>
                </div>
                <div className="catalog-card-row2">
                  <code className="catalog-card-id">{model.model_id}</code>
                  <label className="catalog-toggle">
                    <input
                      type="checkbox"
                      checked={isEnabled}
                      onChange={(event) =>
                        handleToggleCatalog(model.id, event.target.checked)
                      }
                      disabled={!available.has(model.provider)}
                    />
                    <span className="catalog-toggle-thumb" />
                  </label>
                  <span className="catalog-card-provider">{provider}</span>
                </div>
              </div>
            );
          })}
          {!q && disabledModels.length > 0 && (
            <button
              type="button"
              className="btn-tonal catalog-show-all"
              onClick={() => setShowAll(!showAll)}
            >
              {showAll ? 'Hide all models' : `Show all models (${disabledModels.length} disabled)`}
            </button>
          )}
        </>
      )}

      <div className="catalog-add">
        <div className="section-title" style={{ marginTop: 24 }}>
          <Plus size={17} />
          <h3>Add model to catalog</h3>
        </div>
        <p className="section-note">
          Manually add any model ID from NVIDIA NIM or OpenRouter (useful for
          providers without a public model list). The model is added disabled.
        </p>
        <div className="two-col">
          <label className="field">
            <span className="field-label">Provider</span>
            <select
              value={addModelProvider}
              onChange={(event) => setAddModelProvider(event.target.value as 'nim' | 'openrouter')}
            >
              <option value="nim">NVIDIA NIM</option>
              <option value="openrouter">OpenRouter</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">Model ID</span>
            <input
              type="text"
              value={addModelId}
              onChange={(event) => setAddModelId(event.target.value)}
              placeholder="e.g. nvidia/nemotron-3.5-super-vl-120b-a12b"
            />
          </label>
        </div>
        <label className="field">
          <span className="field-label">Display name (optional)</span>
          <input
            type="text"
            value={addModelName}
            onChange={(event) => setAddModelName(event.target.value)}
            placeholder="e.g. Nemotron 3.5 Super VL"
          />
        </label>
        <div className="test-row">
          <button
            type="button"
            className="btn-tonal"
            onClick={handleAddCatalogModel}
            disabled={addingCatalogModel || !addModelId.trim()}
          >
            {addingCatalogModel ? (
              <Loader2 size={15} className="spin" />
            ) : (
              <Plus size={15} />
            )}
            Add model
          </button>
        </div>
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
          <h3>Nexus</h3>
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
          Default: {settings.default_model?.name ?? 'Nemotron 3.5 Super VL'}. Up to
          {settings.max_tool_steps} tool steps per turn.
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
          These are facts the nexus remembers about you across conversations. The model may
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

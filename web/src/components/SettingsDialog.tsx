import { useEffect, useState } from 'react';
import {
  Check,
  Cpu,
  ExternalLink,
  HardDrive,
  KeyRound,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  X,
} from 'lucide-react';
import type { SettingsSnapshot } from '../types';

export interface SettingsPatch {
  provider: 'auto' | 'nim' | 'openrouter';
  user_name: string;
  temperature: number;
  nim_api_key?: string;
  openrouter_api_key?: string;
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

export default function SettingsDialog({
  open,
  settings,
  searxngOk,
  onClose,
  onSave,
  onTest,
}: {
  open: boolean;
  settings: SettingsSnapshot | null;
  searxngOk: boolean | null;
  onClose: () => void;
  onSave: (patch: SettingsPatch) => Promise<void>;
  onTest: (provider: string) => Promise<TestResult>;
}) {
  const [provider, setProvider] = useState<'auto' | 'nim' | 'openrouter'>('auto');
  const [userName, setUserName] = useState('');
  const [temperature, setTemperature] = useState(0.6);
  const [nimKey, setNimKey] = useState('');
  const [openrouterKey, setOpenrouterKey] = useState('');
  const [clearNim, setClearNim] = useState(false);
  const [clearOpenrouter, setClearOpenrouter] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);

  useEffect(() => {
    if (!open || !settings) return;
    setProvider(settings.provider);
    setUserName(settings.user_name);
    setTemperature(settings.temperature);
    setNimKey('');
    setOpenrouterKey('');
    setClearNim(false);
    setClearOpenrouter(false);
    setTest(null);
  }, [open, settings]);

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

        <div className="dialog-body">
          <section className="settings-section">
            <div className="section-title">
              <Cpu size={17} />
              <h3>Model provider</h3>
            </div>
            <p className="section-note">
              One curated model, served by either provider. Auto uses NVIDIA NIM when a key is
              present, then falls back to OpenRouter.
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
                      onClick={() => setClearNim((value) => !value)}
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
                      onClick={() => setClearOpenrouter((value) => !value)}
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

          <section className="settings-section">
            <div className="section-title">
              <KeyRound size={17} />
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
              <Terminal size={17} />
              <h3>Code sandbox</h3>
              <span className={`status-pill ${sandbox.available ? 'good' : 'warn'}`}>
                {sandbox.available ? <ShieldCheck size={13} /> : <ShieldAlert size={13} />}
                {sandbox.available ? 'Ready' : 'Not ready'}
              </span>
            </div>
            <p className="section-note">{sandbox.detail}</p>
            <div className="kv">
              <span>Image</span>
              <code>{sandbox.image_name}</code>
            </div>
            {sandbox.version && (
              <div className="kv">
                <span>Runtime</span>
                <code>{sandbox.version}</code>
              </div>
            )}
            {!sandbox.available && (
              <div className="command-box">
                <code>./scripts/build-sandbox.sh</code>
              </div>
            )}
            <p className="section-note tiny">
              Rootless Podman · no network · all capabilities dropped · read-only root · memory and
              PID limits.
            </p>
          </section>

          <section className="settings-section">
            <div className="section-title">
              <HardDrive size={17} />
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
        </div>

        <footer className="dialog-foot">
          <span className="dialog-hint">Changes apply to new messages.</span>
          <div className="dialog-actions">
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

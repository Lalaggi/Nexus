import { useState } from 'react';
import { ArrowRight, LockKeyhole } from 'lucide-react';
import { Brandmark } from './Brandmark';

export default function Login({ onLogin }: { onLogin: (password: string) => Promise<void> }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await onLogin(password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <Brandmark size={54} />
        <span className="sheet-kicker">Self-hosted</span>
        <h1>Welcome back</h1>
        <p>This Nexus instance is password protected.</p>
        <label className="field">
          <span className="field-label">
            <LockKeyhole size={13} /> Password
          </span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
            autoComplete="current-password"
            placeholder="Password"
          />
        </label>
        {error && <div className="message-error">{error}</div>}
        <button type="submit" className="btn-primary full" disabled={busy || !password}>
          {busy ? 'Unlocking…' : 'Unlock'}
          <ArrowRight size={16} />
        </button>
      </form>
    </div>
  );
}

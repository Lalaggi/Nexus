import { useState } from 'react';
import { ArrowRight, Loader2, Server, ShieldCheck, Wifi } from 'lucide-react';
import { Brandmark } from './Brandmark';
import { normalizeServerUrl, probeServer } from '../server';

export default function Connect({
  initialUrl = '',
  onConnect,
}: {
  initialUrl?: string;
  onConnect: (url: string) => Promise<void>;
}) {
  const [value, setValue] = useState(initialUrl);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [version, setVersion] = useState('');

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setVersion('');
    const base = normalizeServerUrl(value);
    if (!base) {
      setError('Enter a full address, for example http://192.168.1.20:8848');
      return;
    }
    setBusy(true);
    try {
      const health = await probeServer(base);
      console.log('[Connect] probe OK:', base, health);
      setVersion(health.version ? `Assistant ${health.version}` : 'Assistant server');
      await onConnect(base);
    } catch (err) {
      console.error('[Connect] probe failed:', base, err);
      if (err instanceof DOMException && err.name === 'AbortError') {
        setError(
          'The server did not respond. Check the address and your Wi-Fi/Tailscale connection.',
        );
      } else if (err instanceof TypeError) {
        setError(
          'Could not reach that server. Make sure the server is running on 0.0.0.0 (not 127.0.0.1), the address is reachable from this device (try opening it in the device browser), and port 8848 is not blocked by a firewall.',
        );
      } else {
        setError(err instanceof Error ? err.message : 'Could not reach that server.');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-screen connect-screen">
      <form className="login-card connect-card" onSubmit={submit}>
        <Brandmark size={54} />
        <span className="sheet-kicker">Assistant for Android</span>
        <h1>Connect to your server</h1>
        <p>
          Enter the address of your self-hosted Assistant. The app remembers it and talks to that
          server directly.
        </p>

        <label className="field">
          <span className="field-label">
            <Server size={13} /> Server address
          </span>
          <input
            type="url"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="http://192.168.1.20:8848"
            inputMode="url"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            autoFocus
          />
        </label>

        {error && <div className="message-error">{error}</div>}
        {version && (
          <div className="connect-ok">
            <ShieldCheck size={14} />
            <span>Connected to {version}</span>
          </div>
        )}

        <button type="submit" className="btn-primary full" disabled={busy || !value.trim()}>
          {busy ? <Loader2 size={16} className="spin" /> : <Wifi size={16} />}
          {busy ? 'Checking…' : 'Connect'}
          {!busy && <ArrowRight size={16} />}
        </button>

        <div className="connect-tips">
          <p>
            <strong>On your home network</strong> use the machine's LAN address, for example
            <code> http://192.168.1.20:8848</code>.
          </p>
          <p>
            <strong>Over Tailscale</strong> use the machine's Tailscale address or MagicDNS name.
          </p>
          <p>
            <strong>Public access</strong> should go through a reverse proxy with HTTPS. Plain HTTP
            sends your password and chats unencrypted.
          </p>
        </div>
      </form>
    </div>
  );
}

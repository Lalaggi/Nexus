import { Capacitor } from '@capacitor/core';
import { Browser } from '@capacitor/browser';

/**
 * The web build is served by the Nexus backend, so every URL can stay
 * relative. The Android build is a self-contained bundle on http://localhost
 * and must be pointed at a server the first time it runs.
 */
export const IS_NATIVE = Capacitor.isNativePlatform();

const SERVER_KEY = 'nexus.server_url';
const TOKEN_KEY = 'nexus.session_token';

const BUILTIN_SERVER = normalizeServerUrl(
  (import.meta.env.VITE_ASSISTANT_SERVER as string | undefined) ?? '',
);

function read(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? '';
  } catch {
    return '';
  }
}

function write(key: string, value: string) {
  try {
    if (value) window.localStorage.setItem(key, value);
    else window.localStorage.removeItem(key);
  } catch {
    /* storage can be disabled; the app still works for this session */
  }
}

/** Accepts "host:port", "https://host", and trailing slashes. */
export function normalizeServerUrl(input: string): string {
  let value = input.trim();
  if (!value) return '';
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) value = `http://${value}`;
  try {
    const url = new URL(value);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return '';
    url.hash = '';
    url.search = '';
    return url.toString().replace(/\/+$/, '');
  } catch {
    return '';
  }
}

export function getServerUrl(): string {
  if (!IS_NATIVE) return '';
  return normalizeServerUrl(read(SERVER_KEY) || BUILTIN_SERVER);
}

export function saveServerUrl(input: string): string {
  const normalized = normalizeServerUrl(input);
  write(SERVER_KEY, normalized);
  return normalized;
}

export function forgetServerUrl() {
  write(SERVER_KEY, '');
}

export function getToken(): string {
  return IS_NATIVE ? read(TOKEN_KEY) : '';
}

export function rememberToken(token: string) {
  if (IS_NATIVE) write(TOKEN_KEY, token);
}

export function forgetToken() {
  write(TOKEN_KEY, '');
}

export function isConfigured(): boolean {
  return !IS_NATIVE || Boolean(getServerUrl());
}

/** Rewrite an API path for the current platform. */
export function apiUrl(path: string): string {
  if (/^(https?:|blob:|data:)/i.test(path)) return path;
  if (!IS_NATIVE) return path;
  const base = getServerUrl();
  if (!base) return path;
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Absolute URL for a file the server serves. Images, iframes, and download
 * links cannot attach an Authorization header, so the token travels in the
 * query string for native builds.
 */
export function fileUrl(path: string, params?: Record<string, string>): string {
  const absolute = apiUrl(path);
  let url: URL;
  try {
    url = /^https?:\/\//i.test(absolute)
      ? new URL(absolute)
      : new URL(absolute, window.location.origin);
  } catch {
    return absolute;
  }
  if (params) {
    for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value);
  }
  const token = getToken();
  if (token) url.searchParams.set('access_token', token);
  return url.toString();
}

export function downloadUrl(path: string): string {
  return fileUrl(path, { download: '1' });
}

/** Deep-resolve relative file URLs in API payloads for the native bundle. */
export function withFileUrls<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => withFileUrls(item)) as unknown as T;
  }
  if (value && typeof value === 'object') {
    const result: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (key === 'url' && typeof item === 'string' && item.startsWith('/api/')) {
        result[key] = fileUrl(item);
      } else {
        result[key] = withFileUrls(item);
      }
    }
    return result as T;
  }
  return value;
}

export interface ProbeResult {
  version?: string;
  ok: boolean;
}

/** Check a URL before saving it, so a typo does not lock the user out. */
export async function probeServer(input: string): Promise<ProbeResult> {
  const base = normalizeServerUrl(input);
  if (!base) throw new Error('Enter a valid http:// or https:// URL.');
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(`${base}/api/health`, {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`Server answered HTTP ${response.status}.`);
    const data = (await response.json()) as { ok?: boolean; version?: string };
    if (data?.ok !== true) {
      throw new Error('That URL does not look like an Nexus server.');
    }
    return { ok: true, version: data.version };
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The server did not respond. Check the address and your network.');
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export function serverHost(): string {
  const base = getServerUrl();
  if (!base) return '';
  try {
    return new URL(base).host;
  } catch {
    return base;
  }
}

/** Open an external (non-file) URL in the system browser on native, or a new tab on web. */
export async function openExternal(url: string): Promise<void> {
  try {
    const parsed = new URL(url);
    if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') && IS_NATIVE) {
      await Browser.open({ url });
      return;
    }
  } catch {
    /* not a URL we can parse; fall back */
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}

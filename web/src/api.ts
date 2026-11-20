import type { Attachment, CatalogModel, CustomModel, StreamEvent } from './types';
import { apiUrl, authHeaders, fileUrl, withFileUrls } from './server';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    return typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data);
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

const DEFAULT_API_TIMEOUT_MS = 15000;

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const timeoutMs = init?.signal ? 0 : DEFAULT_API_TIMEOUT_MS;
  const controller = timeoutMs ? new AbortController() : undefined;
  const timer = timeoutMs ? window.setTimeout(() => controller?.abort(), timeoutMs) : undefined;
  try {
    const response = await fetch(apiUrl(path), {
      ...init,
      signal: controller?.signal ?? init?.signal,
      headers: {
        ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...authHeaders(),
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) {
      throw new ApiError(await readError(response), response.status);
    }
    if (response.status === 204) return undefined as T;
    return withFileUrls((await response.json()) as T);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`Request to ${path} timed out after ${DEFAULT_API_TIMEOUT_MS / 1000}s.`);
    }
    throw error;
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

export async function streamRequest(
  path: string,
  init: RequestInit,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(apiUrl(path), {
    ...init,
    signal,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...authHeaders(),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  if (!response.body) throw new ApiError('Streaming is not supported by this browser.', 0);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        for (const rawLine of block.split('\n')) {
          const line = rawLine.trim();
          if (!line || line.startsWith(':')) continue;
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload || payload === '[DONE]') continue;
          try {
            onEvent(withFileUrls(JSON.parse(payload) as StreamEvent));
          } catch {
            // A malformed keepalive should never break the conversation.
          }
        }
        boundary = buffer.indexOf('\n\n');
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function uploadFile(file: File): Promise<Attachment> {
  const form = new FormData();
  form.append('file', file);
  const response = await fetch(apiUrl('/api/uploads'), {
    method: 'POST',
    body: form,
    headers: authHeaders(),
  });
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  const data = withFileUrls(await response.json());
  return {
    id: data.id,
    name: data.name,
    mime: data.mime,
    size: data.size,
    url: data.url,
    kind: 'uploads',
    has_text: data.has_text,
  };
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** index;
  return `${index === 0 ? value : value.toFixed(1)} ${units[index]}`;
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const delta = Math.max(0, Date.now() - then);
  const minutes = Math.floor(delta / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days}d`;
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

export interface FileTarget {
  kind: 'outputs' | 'uploads';
  path: string;
  name: string;
  url: string;
  mime?: string;
  size?: number;
}

/** Turn a model-produced file:// link into something the preview panel can open. */
export function fileTargetFromHref(href: string): FileTarget | null {
  let raw = href;
  if (raw.startsWith('file://')) raw = raw.slice('file://'.length);
  try {
    raw = decodeURIComponent(raw);
  } catch {
    // Malformed percent escapes are treated as a plain path.
  }
  let kind: 'outputs' | 'uploads' | null = null;
  let path = '';
  for (const candidate of ['outputs', 'useruploads']) {
    const marker = `/${candidate}/`;
    const index = raw.indexOf(marker);
    if (index !== -1) {
      kind = candidate === 'outputs' ? 'outputs' : 'uploads';
      path = raw.slice(index + marker.length);
      break;
    }
  }
  if (!kind && (raw.startsWith('/mnt/outputs/') || raw.startsWith('/mnt/useruploads/'))) {
    kind = raw.startsWith('/mnt/outputs/') ? 'outputs' : 'uploads';
    path = raw.replace('/mnt/outputs/', '').replace('/mnt/useruploads/', '');
  }
  if (!kind) {
    const marker = '/outputs/';
    const index = raw.indexOf(marker);
    if (index !== -1) {
      kind = 'outputs';
      path = raw.slice(index + marker.length);
    }
  }
  if (!kind || !path) return null;
  const clean = path.replace(/^\/+/, '');
  const name = clean.split('/').pop() || clean;
  return {
    kind,
    path: clean,
    name,
    url: fileUrl(`/api/files/${kind}/${clean.split('/').map(encodeURIComponent).join('/')}`),
  };
}

export function attachmentKind(mime: string): 'image' | 'pdf' | 'text' | 'other' {
  if (mime.startsWith('image/')) return 'image';
  if (mime === 'application/pdf') return 'pdf';
  if (mime.startsWith('text/') || mime.includes('json') || mime.includes('xml')) return 'text';
  return 'other';
}

export async function listCustomModels(): Promise<CustomModel[]> {
  return api<CustomModel[]>('/api/models/custom');
}

export async function addCustomModel(name: string, model_id: string): Promise<CustomModel> {
  return api<CustomModel>('/api/models/custom', {
    method: 'POST',
    body: JSON.stringify({ name, model_id }),
  });
}

export async function deleteCustomModel(model_id: string): Promise<void> {
  return api(`/api/models/custom/${encodeURIComponent(model_id)}`, {
    method: 'DELETE',
  });
}

/* ------------------------------------------------------------------ model catalog */

export async function listCatalogModels(): Promise<CatalogModel[]> {
  return api<CatalogModel[]>('/api/models/catalog');
}

export interface CatalogToggleBody {
  enabled: boolean;
}

export async function toggleCatalogModel(
  catalog_id: string,
  enabled: boolean,
): Promise<CatalogModel> {
  return api<CatalogModel>(`/api/models/catalog/${encodeURIComponent(catalog_id)}/toggle`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  });
}

export async function setCatalogModelDefault(catalog_id: string): Promise<CatalogModel> {
  return api<CatalogModel>(`/api/models/catalog/${encodeURIComponent(catalog_id)}/default`, {
    method: 'PATCH',
  });
}

export async function deleteCatalogModel(catalog_id: string): Promise<void> {
  return api(`/api/models/catalog/${encodeURIComponent(catalog_id)}`, {
    method: 'DELETE',
  });
}

export async function syncCatalogModels(): Promise<{ ok: boolean; synced: number }> {
  return api<{ ok: boolean; synced: number }>('/api/models/catalog/sync', {
    method: 'POST',
  });
}

export interface CatalogAddBody {
  provider: string;
  model_id: string;
  name?: string;
}

export async function addCatalogModel(
  body: CatalogAddBody,
): Promise<CatalogModel> {
  return api<CatalogModel>('/api/models/catalog', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/* ------------------------------------------------------------------ notes */

export interface Note {
  id: string;
  key: string;
  value: string;
  created_at: string;
  updated_at: string;
}

export async function listNotes(): Promise<Note[]> {
  return api<Note[]>('/api/notes');
}

export async function createNote(key: string, value: string): Promise<Note> {
  return api<Note>('/api/notes', {
    method: 'POST',
    body: JSON.stringify({ key, value }),
  });
}

export async function updateNote(key: string, value: string): Promise<Note> {
  return api<Note>(`/api/notes/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    body: JSON.stringify({ value }),
  });
}

export async function deleteNote(key: string): Promise<void> {
  return api(`/api/notes/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  });
}

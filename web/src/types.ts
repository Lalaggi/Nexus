/*
 * Copyright (C) 2026 Ellie Wells <elilovescomputers@gmail.com>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

export type Role = 'user' | 'assistant';

export interface Chat {
  id: string;
  title: string;
  goal: string;
  model: string;
  provider: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
  preview?: string;
}

export interface Attachment {
  id: string;
  name: string;
  mime: string;
  size: number;
  url: string;
  kind?: string;
  has_text?: boolean;
}

export interface ToolEvent {
  id: string;
  name: string;
  args: Record<string, unknown>;
  ok?: boolean;
  summary?: string;
  duration?: number;
  data?: {
    results?: Array<{ title: string; url: string; snippet?: string; engine?: string }>;
    url?: string;
    title?: string;
    files?: Array<{ name: string; path: string; url: string }>;
    exit_code?: number;
    stdout?: string;
    stderr?: string;
    query?: string;
    content?: string;
    goal?: string;
    task?: {
      id?: string;
      title?: string;
      detail?: string;
      status?: string;
    };
    tasks?: Array<{ id: string; title: string; detail?: string; status: string }>;
  };
  status?: 'running' | 'done';
}

export type VersionSource = 'original' | 'edit' | 'regenerate' | 'draft';
export type VersionStatus = 'complete' | 'streaming' | 'error';

export interface MessageVersion {
  id: string;
  message_id?: string;
  version: number;
  content: string;
  reasoning: string;
  tool_events: ToolEvent[];
  attachments: Attachment[];
  duration_ms?: number;
  status?: VersionStatus;
  source?: VersionSource;
  reply_to_version_id?: string;
  created_at?: string;
}

export interface Message {
  id: string;
  chat_id?: string;
  role: Role;
  content: string;
  reasoning: string;
  tool_events: ToolEvent[];
  attachments: Attachment[];
  created_at: string;
  duration_ms?: number;
  seq?: number;
  error?: string;
  retry?: RetryStatus;
  versions?: MessageVersion[];
  active_version_id?: string;
  version?: number;
}

export interface RetryStatus {
  attempt: number;
  max_attempts: number;
  delay_ms: number;
  message?: string;
}

export type TaskStatus = 'pending' | 'in_progress' | 'done' | 'blocked';

export interface TaskItem {
  id: string;
  chat_id: string;
  title: string;
  detail: string;
  status: TaskStatus;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface FileItem {
  name: string;
  path: string;
  size: number;
  mtime: number;
  url: string;
  kind: 'outputs' | 'uploads';
  mime: string;
}

export type ProviderId = 'nim' | 'openrouter';

export interface ProviderInfo {
  id: ProviderId;
  label: string;
  available: boolean;
  key_hint: string;
  docs: string;
}

export interface CatalogModel {
  id: string;            // catalog row id
  provider: ProviderId;
  model_id: string;      // id sent to the provider API
  name: string;          // display name
  enabled: boolean;
  is_default: boolean;
  source: 'default' | 'discovered' | 'custom';
}

export interface SandboxStatus {
  available: boolean;
  podman: boolean;
  image: boolean;
  image_name: string;
  mode: string;
  version?: string;
  detail: string;
}

export interface SettingsSnapshot {
  provider: 'auto' | 'nim' | 'openrouter';
  providers: ProviderInfo[];
  models: CatalogModel[];
  default_model: CatalogModel | null;
  custom_models: Array<{ id: string; name: string; model_id: string }>;
  keys: {
    nim: { set: boolean; hint: string };
    openrouter: { set: boolean; hint: string };
  };
  user_name: string;
  assistant_name: string;
  temperature: number;
  custom_instructions: string;
  custom_model_id: string;
  max_tool_steps: number;
  sandbox: SandboxStatus;
  paths: { uploads: string; outputs: string; data: string };
  searxng_url: string;
  auth_required: boolean;
}

export interface CustomModel {
  id: string;
  name: string;
  model_id: string;
}

export interface StreamEvent {
  type: string;
  [key: string]: unknown;
}

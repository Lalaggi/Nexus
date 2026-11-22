# Architecture

Nexus is a single FastAPI process serving a React UI. This document describes the architecture and data flow.

## Components

```
+----------------+      HTTP/SSE      +-------------------------+
|  React UI      | <================> |  FastAPI backend        |
|  (web/src)     |      /api          |  (src/nexus)            |
+----------------+                    +-------------------------+
                                                 |
                                      +----------v----------+
                                      |  SQLite database    |
                                      |  (data/nexus.db)    |
                                      +----------+----------+
                                                 |
                                      +----------v----------+
                                      |  Provider API       |
                                      |  (NIM / OpenRouter) |
                                      +----------+----------+
                                                 |
                                      +----------v----------+
                                      |  SearXNG (search)   |
                                      |  Podman (sandbox)   |
                                      +---------------------+
```

## Backend (`src/nexus/`)

| Module | Responsibility |
|--------|--------------|
| `config.py` | Runtime configuration and filesystem layout (`ASSISTANT_*` env vars) |
| `main.py` | FastAPI app, lifespan, CORS, auth middleware, security headers, SPA serving |
| `__main__.py` | CLI entry point (`uv run nexus`) |
| `db.py` | SQLite persistence (aiosqlite), schema, migrations, encryption |
| `crypto.py` | Fernet at-rest encryption for sensitive DB fields |
| `agent.py` | Streaming tool-use loop: context building, tool calling, SSE emission, title generation |
| `providers.py` | Model catalog routing + provider resolution, OpenAI-compatible streaming client, retry policy |
| `retry.py` | Retry/rate-limit handling: `RetryPolicy`, `parse_retry_after_ms`, `is_retryable`, `next_delay` |
| `prompt.py` | System prompt |
| `media.py` | Render images/PDF pages as native visual content |
| `routes/chats.py` | Chat, message, task, version, and SSE-stream endpoints |
| `routes/files.py` | Upload handling and read-only file serving |
| `routes/notes.py` | User notes CRUD |
| `routes/settings.py` | Settings, health, auth, model catalog, custom models |
| `tools/base.py` | Tool registry, `Tool`, `ToolContext`, `ToolResult` |
| `tools/files.py` | `write_file`, `read_file`, `list_files` |
| `tools/sandbox.py` | Isolated Podman container execution |
| `tools/search.py` | SearXNG web search |
| `tools/tasks.py` | Goal/task tools |
| `tools/notes.py` | User notes tools |
| `tools/webfetch.py` | Web page fetch + extraction |

## Frontend (`web/src/`)

React + TypeScript + Vite, packaged with Capacitor for Android.

| File | Responsibility |
|------|--------------|
| `App.tsx` | Composition root: boot/auth, chat loading, streaming, settings wiring |
| `api.ts` | API client (`streamRequest`, `uploadFile`, fetch helpers) |
| `server.ts` | Server URL/token storage (native + web) |
| `useGesture.ts` | Drag-follow touch gesture hook |
| `types.ts` | TypeScript interfaces (Chat, Message, ToolEvent, SettingsSnapshot, ...) |
| `styles.css` | Global styles |
| `components/` | `ChatView`, `MessageView`, `Composer`, `Sidebar`, `SettingsDialog`, `TasksPanel`, `ToolTimeline`, `VersionSwitcher`, `FilePreview`, `Markdown`, `Connect`, `Login`, `Welcome`, `Brandmark`, `NexusIcons` |

## Data flow — one chat turn

1. Frontend `POST /api/chats/{chat_id}/messages` with content + attachments, plus optional `model` and `provider`.
2. Backend resolves the chat's model/provider against the model catalog (`model_catalog` table) and streams from the chosen provider.
3. `agent.run_turn` builds context from the database (recent window, up to 350k chars, ≤70 messages, ≤6 images), adds the system prompt (with user notes and custom instructions), and streams from the provider.
4. On tool calls, the backend executes the tool, emits `tool_call`/`tool_result` SSE events, appends tool messages to the context, and continues the loop (up to `max_tool_steps`).
5. On completion, `update_message` writes the active version, a title is generated on the first turn, and a `done` event is emitted with version info.
6. Frontend renders deltas, reasoning, tool events, and the version switcher.

## Database

SQLite with WAL journal, foreign keys, and secure_delete. Tables: `chats`, `messages`, `message_versions`, `tasks`, `uploads`, `settings`, `user_notes`, `custom_models`, `model_catalog`. Sensitive columns are encrypted at rest. Migrations run on startup (duration_ms column, message_versions table, plaintext encryption, model_catalog table).

### Model catalog

Nexus is model-agnostic. Instead of a hardcoded registry, available models live in the `model_catalog` table (`provider`, `model_id`, `name`, `enabled`, `is_default`, `source`). Nemotron 3.5 Super VL is seeded as **enabled + default** on NIM and **enabled** on OpenRouter so a fresh instance works out of the box. Users search the catalog, enable models they want, and pick one as default; only enabled models appear in the message composer dropdown. The catalog can be synced from both providers' OpenAI-compatible `/models` endpoints via `POST /api/models/catalog/sync`, or entries can be added manually.

## Versioning

Messages are versioned: `messages.active_version_id` points to a row in `message_versions`. Edits and regenerates append versions (`source`: `original`/`edit`/`regenerate`/`draft`); `reply_to_version_id` links an assistant reply to the user version it answered, so switching either side of an edited turn moves both together.

## Config layout

- `data/nexus.db` — SQLite database
- `data/home/useruploads/` — uploads (per chat)
- `data/home/outputs/` — generated files (per chat)
- `data/home/.workspaces/` — per-chat scratch
- `~/.config/nexus/secret.key` — encryption key (if not using `ASSISTANT_ENCRYPTION_KEY`)
- `.env` — runtime configuration (gitignored)

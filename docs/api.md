# HTTP API reference

Nexus is a single FastAPI process serving a REST API with JSON bodies and Server-Sent Events (SSE) for streaming turns. All endpoints are prefixed with `/api`.

## Authentication

When `ASSISTANT_PASSWORD` is set, all `/api/` endpoints (except `/api/login`, `/api/auth`, `/api/health`) require a session cookie `assistant_session` or an `Authorization: Bearer <token>` header. The token is obtained from `POST /api/login`.

Login failures are rate-limited (10 failures per 5-minute window per IP). The packaged Android app sends a bearer token and appends `?access_token=` to file URLs.

## Chats — `/api/chats`

### `GET /api/chats`

List all chats, newest first, with message counts and previews.

**Response:** `list[{ id, title, goal, model, provider, created_at, updated_at, message_count, preview }]`

### `POST /api/chats`

Create a new chat.

**Body:** `{ title?, model?, provider? }`

**Response:** the created chat object.

### `PATCH /api/chats/{chat_id}`

Update title, goal, model, or provider.

**Body:** `{ title?, goal?, model?, provider? }`

### `GET /api/chats/{chat_id}`

Get a chat with its messages and tasks.

**Response:** `{ chat, messages[], tasks[] }`

### `PATCH /api/chats/{chat_id}`

Update title, goal, or model.

**Body:** `{ title?, goal?, model? }`

### `DELETE /api/chats/{chat_id}`

Delete a chat and its per-chat uploads, outputs, and workspace files.

## Messages — streaming

### `POST /api/chats/{chat_id}/messages`

Send a user message and stream the assistant's response as SSE.

**Body:** `{ content, attachment_ids[], model?, provider? }`

**Response:** `text/event-stream`. Events:

- `user_message` — the created user message + resolved provider/model
- `meta` — provider, model, version info for the assistant message
- `delta` — text delta
- `reasoning` — reasoning delta
- `tool_call` — a tool call the model is making (`id`, `name`, `args`)
- `tool_result` — the tool's result (`ok`, `summary`, `data`, `duration`)
- `retry` — provider retry in progress (`attempt`, `max_attempts`, `delay_ms`, `message`)
- `title` — generated chat title (first assistant turn only)
- `done` — turn complete (`content`, `reasoning`, `tool_events`, `duration_ms`, `usage`, `cancelled`, version info)
- `error` — a fatal error

### `POST /api/chats/{chat_id}/regenerate`

Regenerate the assistant's response to the last user message, appending a new version instead of duplicating the message.

### `PATCH /messages/{message_id}`

Edit a message, creating a new version. Requires `content`.

**Body:** `{ content }`

### Message versions

- `GET /api/chats/{chat_id}/messages/{message_id}/versions` — list versions
- `POST /api/chats/{chat_id}/messages/{message_id}/versions` — create an edited version (`{ content }`)
- `POST /messages/{message_id}/versions/{version_id}/activate` — switch the active version (switches the linked side of an edited turn too)

### `DELETE /messages/{message_id}/after`

Delete all messages after the given message in a chat (used when editing mid-conversation).

### `POST /chats/{chat_id}/stop`

Cancel the in-progress run for a chat.

## Tasks — `/api/tasks`

### `PATCH /tasks/{task_id}`

Update a task's status, title, or detail.

**Body:** `{ status?, title?, detail? }`

## Files — `/api/files`

### `POST /api/uploads`

Upload a file. `file` (multipart) and optional `chat_id` form field. Uploads without a `chat_id` go to a temp directory and are moved into the per-chat uploads dir when attached.

### `GET /api/files/list?kind=outputs|uploads&chat_id=...`

List files in a chat's outputs or uploads directory.

### `GET /api/files/chats/{chat_id}/{kind}/{path}`

Serve a chat file (outputs or uploads). Active content (HTML, SVG, JS, XML) is served as `text/plain` with a restrictive CSP.

## Notes — `/api/notes`

CRUD for user notes: `GET`, `GET /{key}`, `POST`, `PATCH /{key}`, `DELETE /{key}`.

## Model catalog — `/api/models/catalog`

`GET /api/models/catalog` — list all catalog entries with `id`, `provider`, `model_id`, `name`, `enabled`, `is_default`, `source`.

`POST /api/models/catalog/sync` — fetch OpenRouter's public `/models` list and upsert it into the catalog (requires an OpenRouter API key). NIM entries are added manually.

`PATCH /api/models/catalog/{catalog_id}/toggle` — `{ enabled: boolean }` enable or disable a model. Disabling the current default picks a new default from the remaining enabled models.

`PATCH /api/models/catalog/{catalog_id}/default` — set the given enabled model as the default (clears the default flag on all others). Only enabled models can be the default.

`DELETE /api/models/catalog/{catalog_id}` — remove a catalog entry.

## Custom models — `/api/models/custom`

`GET`, `POST { name, model_id }`, `DELETE /{model_id:path}`.

## Settings — `/api/settings`

### `GET /api/settings`

Snapshot: provider, providers, models (full catalog with enabled/default flags), default_model, keys, user name, temperature, custom instructions, custom model ID, custom models, sandbox status, paths, searxng URL, auth_required.

### `PUT /api/settings`

Update provider, user name, temperature, custom instructions, custom model ID, API keys.

### `POST /api/settings/test`

Test a provider connection (hits `GET /models` on the provider base URL, using that provider's default enabled model).

## Health — `/api/health`

Returns `{ ok, searxng, sandbox, version }`. The sandbox field reports availability and mode (`dedicated user ...` or `current user (development mode)`).

## Models — `/api/models`

Lists catalog entries with `id`, `provider`, `model_id`, `name`, `enabled`, `is_default`, `source`.

## SSE event types

| Event | Meaning |
|-------|---------|
| `user_message` | User message created; stream starting |
| `meta` | Provider/model/version info for the assistant message |
| `delta` | Assistant text delta |
| `reasoning` | Reasoning delta |
| `tool_call` | Model is calling a tool |
| `tool_result` | Tool result returned |
| `retry` | Provider retry in progress (backoff/wait) |
| `title` | Chat title generated (first turn) |
| `done` | Turn complete |
| `error` | Fatal error |
| `ping` | Keep-alive (comment line `: ping`) |

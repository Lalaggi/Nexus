# AGENTS.md — Nexus

This file orients agents working on **Nexus**, a self-hosted, single-user
ChatGPT replacement that works with any model on NVIDIA NIM or OpenRouter
(Nemotron 3.5 VL Super is enabled by default). It streams reasoning, calls
tools, searches the web through a local SearXNG instance, and gives the model
a disposable Linux sandbox for Python, git, curl, and file output.

Keep this file current when you change user-facing behavior, commands, or the
codebase layout.

---

## One-line summary

Single FastAPI process serving a React (TypeScript/Vite) SPA. Backend in
`src/nexus/`, frontend in `web/src/`, SQLite at `data/nexus.db`, config via
`ASSISTANT_*` env vars in `.env`.

---

## Essential commands

| Task | Command |
|------|---------|
| Install backend deps | `uv sync` |
| Install frontend deps | `npm --prefix web install` |
| Build frontend (production) | `npm --prefix web run build` |
| Run backend with reload | `uv run uvicorn nexus.main:app --reload --port 8848` or `uv run nexus` |
| Run frontend dev server | `npm --prefix web run dev` (proxies `/api` to `:8848`, port `5173`) |
| Run tests | `uv run pytest` |
| Type-check frontend | `npx tsc --noEmit` |
| Sandbox one-time host setup | `sudo ./scripts/setup-sandbox-user.sh` |
| Test the sandbox | `./scripts/test-sandbox.sh` |

The app opens at `http://127.0.0.1:8848`. It binds to loopback by default; set
`ASSISTANT_HOST=0.0.0.0` only with a password and preferably HTTPS.

---

## Stuff you need to know about the architecture

This is the short version so you spend less time exploring. Full details live
in `docs/architecture.md`, `docs/development.md`, and `docs/tools.md`.

### Components

```
React UI (web/src)  <== HTTP/SSE /api ==>  FastAPI backend (src/nexus)
                                                    |
                                          SQLite DB (data/nexus.db)
                                                    |
                                          Provider API (NIM / OpenRouter)
                                                    |
                                          SearXNG (search) / Podman (sandbox)
```

### Backend (`src/nexus/`)

| Module | Responsibility |
|--------|----------------|
| `config.py` | Runtime config + filesystem layout from `ASSISTANT_*` env vars |
| `main.py` / `__main__.py` | FastAPI app, lifespan, CORS, auth, security headers, SPA serving; CLI entry (`uv run nexus`) |
| `db.py` | SQLite persistence (aiosqlite), schema, migrations, encryption |
| `crypto.py` | Fernet at-rest encryption for sensitive DB fields |
| `agent.py` | Streaming tool-use loop: context building, tool calling, SSE emission, title generation |
| `providers.py` | Model catalog routing + provider resolution, OpenAI-compatible streaming client, retry |
| `retry.py` | `RetryPolicy`, `parse_retry_after_ms`, `is_retryable`, `next_delay` |
| `prompt.py` | System prompt |
| `media.py` | Render images/PDF pages as native visual content |
| `routes/chats.py` | Chat, message, task, version, SSE-stream endpoints |
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

### Frontend (`web/src/`)

React + TypeScript + Vite, packaged with Capacitor for Android
(`web/android/`).

| File | Responsibility |
|------|----------------|
| `App.tsx` | Composition root: boot/auth, chat loading, streaming, settings wiring |
| `api.ts` | API client (`streamRequest`, `uploadFile`, fetch helpers) |
| `server.ts` | Server URL/token storage (native + web) |
| `useGesture.ts` | Drag-follow touch gesture hook |
| `types.ts` | TypeScript interfaces (Chat, Message, ToolEvent, SettingsSnapshot, …) |
| `styles.css` | Global styles |
| `components/` | `ChatView`, `MessageView`, `Composer`, `Sidebar`, `SettingsDialog`, `TasksPanel`, `ToolTimeline`, `VersionSwitcher`, `FilePreview`, `Markdown`, `Connect`, `Login`, `Welcome`, `Brandmark` |

### One chat turn (data flow)

1. Frontend `POST /api/chats/{chat_id}/messages` with content + attachments.
2. Backend creates a user message and assistant message (version 1), starts a run, returns an SSE stream.
3. `agent.run_turn` builds context from the DB (recent window, ≤350k chars, ≤70 messages, ≤6 images), adds the system prompt (with user notes and custom instructions), and streams from the provider.
4. On tool calls, the backend executes the tool, emits `tool_call`/`tool_result` SSE events, appends tool messages, and continues the loop (up to `max_tool_steps`).
5. On completion, `update_message` writes the active version, a title is generated on the first turn, and a `done` event is emitted with version info.
6. Frontend renders deltas, reasoning, tool events, and the version switcher.

### Database & storage

- SQLite with WAL journal, foreign keys, `secure_delete`. Tables: `chats`,
  `messages`, `message_versions`, `tasks`, `uploads`, `settings`, `user_notes`,
  `custom_models`, `model_catalog`. Sensitive columns are encrypted at rest with Fernet.
- Messages are versioned (`messages.active_version_id` → `message_versions`).
  Edits/regenerates append versions; `reply_to_version_id` links an assistant
  reply to the user version it answered, so switching either side of an edited
  turn moves both together.
- Config layout: `data/nexus.db`, `data/home/useruploads/`,
  `data/home/outputs/`, `data/home/.workspaces/`,
  `~/.config/nexus/secret.key` (encryption key, if not using
  `ASSISTANT_ENCRYPTION_KEY`), `.env` (runtime config, gitignored).

### Runtime boundaries to remember

- Single-user by design: no multi-tenant isolation. Run one instance per
  person, each with its own database and encryption key.
- `data/`, `*.db`, `.env`, and key files are gitignored.
- The sandbox protects your home directory and keys from the model's code,
  **not** the app process from you.
- Back up `~/.config/nexus/secret.key` (or the `ASSISTANT_ENCRYPTION_KEY`):
  without it, the encrypted database cannot be recovered.

---

## Repository layout

```
src/nexus/          backend (FastAPI)
web/src/            frontend (React + TypeScript + Vite)
web/android/        Capacitor Android app
sandbox/            sandbox Containerfile
scripts/            setup-sandbox-user.sh, build-sandbox.sh, test-sandbox.sh
android-sdk/        vendored Android SDK
tests/              pytest tests
docs/               detailed reference and operational guides
data/               runtime data (gitignored)
.env                runtime config (gitignored)
```

## Code conventions

Follow these when touching code; they match `docs/development.md` and
`docs/contributing.md`.

### Python (`src/nexus/`, `tests/`)

- `requires-python = ">=3.13"`; Python 3.13 (see `.python-version`).
- Dependency manager: `uv` (`uv sync`, `uv run …`).
- Module docstring first, then the Apache 2.0 copyright header:

  ```python
  """Module summary."""
  # Copyright (C) 2026 Ellie Wells <elilovescomputers@gmail.com>
  #
  # Licensed under the Apache License, Version 2.0 (the "License");
  # ... (full block, see src/nexus/agent.py)
  #

  from __future__ import annotations
  ```

- Type hints on public functions; `logger = logging.getLogger(__name__)`.
- Tests: `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`), files in
  `tests/`. Run with `uv run pytest`.
- Linting/formatting are **planned, not configured** (TODO items 13–14: add
  `ruff` + `mypy` to dev dependencies). Do not introduce a new linter without
  updating `pyproject.toml` and `TODO.md`.

### TypeScript / React (`web/src/`)

- React functional components + hooks, TypeScript strict mode,
  `lucide-react` icons.
- Dev server: `npm --prefix web run dev`; build: `npm --prefix web run build`;
  type-check: `npx tsc --noEmit`.
- No ESLint/Prettier or frontend unit tests yet (TODO item 13).

### Commits

Conventional, descriptive messages (see `git log`). Branch from `main`.

---

## Documentation standards (from docs/contributing.md)

- `README.md` — project front door, quick start, feature overview.
- `CHANGELOG.md` — versioned release notes (Keep a Changelog style).
- `COMPLETED.md` — canonical record of implemented features.
- `TODO.md` — planned work / backlog.
- `CLEANUP_PLAN.md` — codebase hygiene plan (code splits, backend fixes,
  testing/tooling).
- `FUTURE_PLANS.md` / `MOBILE_APP_PLANS.md` — big features and mobile plans.
- `docs/` — detailed reference: installation, configuration, usage, tools,
  API, sandbox, security, architecture, development, mobile, contributing.

When you ship a user-facing change, update the relevant `docs/` file and the
root tracking files.

---

## How to make a change

1. Pick an item from `TODO.md` (or `CLEANUP_PLAN.md` for hygiene work).
2. Create a branch from `main`.
3. Make the change, following the coding style above.
4. Add or update tests in `tests/` where applicable.
5. Update `docs/` and root tracking files if the change affects users.
6. Open a pull request (or commit directly if you are the maintainer).

---

## License

Apache 2.0 — see `LICENSE`.

# TODO — Planned Work & Backlog

Canonical backlog for Nexus. Items here are **not yet implemented**. When an item is done, move it to `COMPLETED.md` and remove it from here.

Items are grouped roughly in suggested implementation order (lowest risk first), consistent with `CLEANUP_PLAN.md` § "Order of Implementation".

## Frontend (`web/src/`) — code hygiene

### 1. Split `App.tsx` (~844 lines) — god component
**Problem:** `App.tsx` handles boot/auth, chat loading, streaming, message draft, attachments, file listing, task updates, settings save/test, and rendering. It is hard to read, test, or modify in isolation.

**Plan:** Extract into focused modules and hooks:
- `useChats.ts` — chat list, create, delete, load, refresh.
- `useStream.ts` — `startStream`, SSE handling, abort/stop, optimistic messages.
- `useFiles.ts` — `fetchFiles`, `changeFileKind`, `refreshFiles`.
- `ChatHeader.tsx` — topbar title, provider chip, task/files buttons, settings.
- `ComposerDock.tsx` — composer wrapper + composer note text.
- Keep `App.tsx` as the composition root only (state + wiring).

### 2. Split `SettingsDialog.tsx` (~711 lines)
**Problem:** One file contains the dialog shell plus three full category panels (Provider, Personalisation, Stats).

**Plan:** Split into:
- `SettingsDialog.tsx` — dialog shell, tabs, save/test/notify wiring only.
- `ProviderPanel.tsx` — provider cards, API keys, custom models, test connection.
- `PersonalisationPanel.tsx` — name, temperature, custom instructions, notes.
- `NotesPanel.tsx` — notes list + add/remove form (split out of Personalisation).
- `StatsPanel.tsx` — sandbox status, storage, SearXNG.

### 3. Split `ToolTimeline.tsx` (662 lines)
**Problem:** Event grouping, group titles/previews, per-kind body renderers, and the top-level `WorkGroup`/`ToolTimeline` are all in one file.

**Plan:** Extract:
- `grouping.ts` — `groupEvents`, `groupTitle`, `groupPreview`, `kindOf`, `iconFor`.
- `bodies.ts` — per-kind renderers (`GoalBody`, `TasksBody`, `SearchBody`, `FetchBody`, `WriteBody`, `CodeBody`, `FileLinks`).
- Keep `ToolTimeline.tsx` for the top-level summary/worklog rendering only.

### 4. Remove duplicate `CustomModel` interface (`web/src/types.ts`)
**Problem:** `CustomModel` is declared twice. TypeScript merges them, but it is redundant and confusing.

**Plan:** Keep a single `CustomModel` interface declaration; delete the second.

### 5. Remove dead `run_python` mapping (`ToolTimeline.tsx`)
**Problem:** `KIND_ORDER` maps `run_python` → `'code'`, but no `run_python` tool is registered anywhere in the backend. Dead code.

**Plan:** Remove `run_python` from `KIND_ORDER` (or register a `run_python` tool if one is ever intended).

## Backend (`src/nexus/`)

### 6. Fix sandbox UID/GID hardcoding (`tools/sandbox.py`)
**Problem:** `run_sandbox` hardcodes `--userns=keep-id:uid=1000,gid=1000` and `--user 1000:1000`. If the dedicated sandbox account is not UID 1000, bind-mounted files are owned by the wrong user.

**Plan:** Resolve the sandbox account's actual `pw_uid`/`pw_gid` via `pwd.getpwnam(CONFIG.sandbox_account)` and pass those values to the Podman `--userns=keep-id` and `--user` flags. Fall back gracefully if the account does not exist (development mode).

### 7. Fix potential hang on sandbox timeout (`tools/sandbox.py`)
**Problem:** On `TimeoutError`, the code calls `process.kill()` then `await process.communicate()`. If the container does not terminate promptly, `communicate()` can block.

**Plan:** After `process.kill()`, await `communicate()` with a short secondary timeout, then fall back to `process.terminate()` if still alive.

### 8. Stop swallowing DB persist errors (`agent.py`)
**Problem:** The `finally` block in `run_turn` wraps `db.update_message` and `db.touch_chat` in `except Exception: pass`. A full disk or DB error silently loses the nexus's response.

**Plan:** Replace the bare `pass` with a logged error (use the module `logger`) so operators can see when persistence fails, while still not crashing the stream.

### 9. Make `delete_chat` explicit (`db.py` + `routes/chats.py`)
**Problem:** `delete_chat` deletes `uploads` and `chats` rows and relies on SQLite `ON DELETE CASCADE` for `messages`/`tasks`. `shutil.rmtree` uses `ignore_errors=True`, so leftover per-chat files are silently ignored.

**Plan:**
- Explicitly `DELETE FROM messages WHERE chat_id = ?` and `DELETE FROM tasks WHERE chat_id = ?` (do not depend solely on cascade).
- Wrap `shutil.rmtree` in a try/except that logs a warning on failure instead of silently ignoring it.

## Big features (deferred)

### 10. Clarifying questions / `ask_questions`
**Goal:** let the model pause and ask the user a structured question in an interactive GUI instead of guessing or asking in prose.

**Shape:**
- New tool, e.g. `ask_questions`, with a schema like:
  `[{ "id": "scope", "question": "...", "options": [{ "id": "a", "label": "..." }],
  "allow_multiple": false, "allow_free_text": true }]`.
- The tool persists a pending question set, emits an SSE `question` event, and ends the current turn with an `awaiting_user` state rather than continuing the tool loop.
- The UI renders question cards in the chat: radio/checkbox options, optional free-text field, and a single Submit button. Composer is disabled while questions are pending.
- Submitting posts the answers, stores them as a normal user message plus structured `answers` metadata, and starts a new run with the pending question attached to context.
- Cancelling or editing the message should discard the pending question set.
- Add a timeout/fallback: if the user never answers, the next message supersedes it.

**Work items:**
- `db.py`: pending-questions table (or a `questions` JSON column on messages).
- `tools/clarify.py`: register the tool and validate the payload.
- `agent.py`: stop the loop on a question result; surface `awaiting_user` in `done`.
- `routes/chats.py`: answer endpoint and run restart.
- Web: `QuestionCard` component, stream event handling, answer submission, mobile layout.
- Prompt: tell the model to ask only when a wrong guess would be costly, and to batch related questions into one call.

### 11. Provider backend remake ✅ (backend done, frontend pending)
**Goal:** make providers and models portable instead of hand-curated, so any model on OpenRouter, NVIDIA NIM, SiliconFlow, and similar services is easy to use.

**Done:**
- `model_catalog` DB table (`provider`, `model_id`, `name`, `enabled`, `is_default`, `source`) seeded with Nemotron 3.5 Super VL (enabled + default on NIM, enabled on OpenRouter).
- `resolve_provider(db, provider, model_id)` resolves an explicit provider + API model id; hardcoded Nemotron registry removed.
- `GET /api/models/catalog`, `POST /api/models/catalog/sync` (OpenRouter `/models`), `PATCH .../toggle`, `PATCH .../default`, `DELETE .../catalog/{id}`; `GET /api/settings` returns catalog + `default_model`.
- Chats persist `model` + `provider`; composer shows only enabled models.

**Remaining (frontend):** none — done.
- SettingsDialog model-catalog panel: flat list, default first, enabled alphabetical, "Show all models" reveals disabled, pretty names, darker toggles, manual add form.
- Composer dropdown filtered to enabled models, default pre-selected, pretty names.

**Files:** `src/nexus/providers.py`, `src/nexus/config.py`, `db.py` (`model_catalog`), `routes/settings.py`, `routes/chats.py`, `agent.py`, `web/src/components/SettingsDialog.tsx`, model picker in `App.tsx` / `Composer.tsx`.

## Testing & tooling (currently absent or partial)

### 12. Add backend tests (`tests/`)
**Problem:** `tests/` exists but coverage is thin (encryption, files, notes, prompt, retry, webfetch, message versions, version API). `pytest` and `pytest-asyncio` are dev dependencies.

**Plan:** Add tests covering:
- `db.py` — chat/message/task/upload/note CRUD, migrations.
- `tools/` — `write_file`, `read_file`, `list_files`, `search`, `webfetch` (mocked HTTP), `sandbox` (mocked subprocess).
- `routes/` — chat endpoints, settings, notes, files (with `TestClient` or `httpx.AsyncClient` against the FastAPI app).
- `providers.py` — `resolve_provider` selection logic.

### 13. Add frontend type-check and lint
**Problem:** TypeScript `tsc -b` runs as part of `build`, but there is no separate lint/format step, and no frontend unit tests.

**Plan:** Add `eslint` + `prettier` to `web/package.json` dev dependencies with `lint` and `format` scripts. Add `tsc --noEmit` as a standalone CI step (separate from `vite build`).

### 14. Add Python linting/formatting
**Problem:** No `ruff`, `mypy`, `black`, or similar configured.

**Plan:** Add `ruff` (lint + format) and `mypy` to `pyproject.toml` dev dependencies. Add `ruff check`, `ruff format --check`, and `mypy` as CI steps.

## Notes

- `CLEANUP_PLAN.md` item 6 (add public `db.get_message()`) and item 7 (move `import re` to top of `tools/notes.py`) are already done in the current code.
- The `tests/` directory now contains `test_encryption.py`, `test_files_tools.py`, `test_harness_hardening.py`, `test_message_versions.py`, `test_notes_api.py`, `test_prompt.py`, `test_retry.py`, `test_version_api.py`, `test_webfetch.py`.

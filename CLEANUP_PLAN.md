# Cleanup Plan — Assistant

**Status:** planned only, not implemented.
**Scope:** codebase hygiene, maintainability, testing, and tooling.
**Explicitly NOT included:** the bug fixes and missing features already implemented
(notes API, files-sidebar `chat_id`, mobile composer overflow, duplicate collapse
buttons, settings panel width, notes management UI) — those are done.

---

## Frontend (`web/src/`)

### 1. Split `App.tsx` (844 lines) — god component
**Problem:** `App.tsx` handles boot/auth, chat loading, streaming, message draft,
attachments, file listing, task updates, settings save/test, and rendering. It is
hard to read, test, or modify in isolation.

**Plan:** Extract into focused modules and hooks:
- `useChats.ts` — chat list, create, delete, load, refresh.
- `useStream.ts` — `startStream`, SSE handling, abort/stop, optimistic messages.
- `useFiles.ts` — `fetchFiles`, `changeFileKind`, `refreshFiles`.
- `ChatHeader.tsx` — topbar title, provider chip, task/files buttons, settings.
- `ComposerDock.tsx` — composer wrapper + composer note text.
- Keep `App.tsx` as the composition root only (state + wiring).

### 2. Split `SettingsDialog.tsx` (~711 lines)
**Problem:** One file contains the dialog shell plus three full category panels
(Provider, Personalisation, Stats).

**Plan:** Split into:
- `SettingsDialog.tsx` — dialog shell, tabs, save/test/notify wiring only.
- `ProviderPanel.tsx` — provider cards, API keys, custom models, test connection.
- `PersonalisationPanel.tsx` — name, temperature, custom instructions, notes.
- `NotesPanel.tsx` — notes list + add/remove form (split out of Personalisation).
- `StatsPanel.tsx` — sandbox status, storage, SearXNG.

### 3. Split `ToolTimeline.tsx` (662 lines)
**Problem:** Event grouping, group titles/previews, per-kind body renderers, and
the top-level `WorkGroup`/`ToolTimeline` are all in one file.

**Plan:** Extract:
- `grouping.ts` — `groupEvents`, `groupTitle`, `groupPreview`, `kindOf`, `iconFor`.
- `bodies.ts` — per-kind renderers (`GoalBody`, `TasksBody`, `SearchBody`,
  `FetchBody`, `WriteBody`, `CodeBody`, `FileLinks`).
- Keep `ToolTimeline.tsx` for the top-level summary/worklog rendering only.

### 4. Remove duplicate `CustomModel` interface (`web/src/types.ts`)
**Problem:** `CustomModel` is declared twice (lines ~132 and ~194). TypeScript
merges them, but it is redundant and confusing.

**Plan:** Keep a single `CustomModel` interface declaration; delete the second.

### 5. Remove dead `run_python` mapping (`ToolTimeline.tsx`)
**Problem:** `KIND_ORDER` maps `run_python` → `'code'`, but no `run_python` tool
is registered anywhere in the backend. Dead code.

**Plan:** Remove `run_python` from `KIND_ORDER` (or register a `run_python`
tool if one is ever intended).

---

## Backend (`src/assistant/`)

### 6. Add public `db.get_message()` and stop using private `db._fetchone`
**Problem:** `routes/chats.py` `patch_message` calls private `db._fetchone()`
directly, breaking encapsulation.

**Plan:** Add `async def get_message(self, message_id: str) -> dict | None` to
`Database` in `db.py`; update `patch_message` to use it.

### 7. Move `import re` to top of file (`tools/notes.py`)
**Problem:** `import re` sits at line 122 (after functions that use `re`), flagged
as E402. Works at runtime but is misleading.

**Plan:** Move `import re` to the top of the module with the other imports.

### 8. Fix sandbox UID/GID hardcoding (`tools/sandbox.py`)
**Problem:** `run_sandbox` hardcodes `--userns=keep-id:uid=1000,gid=1000` and
`--user 1000:1000`. If the dedicated sandbox account is not UID 1000,
bind-mounted files are owned by the wrong user.

**Plan:** Resolve the sandbox account's actual `pw_uid`/`pw_gid` via
`pwd.getpwnam(CONFIG.sandbox_account)` and pass those values to the Podman
`--userns=keep-id` and `--user` flags. Fall back gracefully if the account
does not exist (development mode).

### 9. Fix potential hang on sandbox timeout (`tools/sandbox.py`)
**Problem:** On `TimeoutError`, the code calls `process.kill()` then
`await process.communicate()`. If the container does not terminate promptly,
`communicate()` can block.

**Plan:** After `process.kill()`, await `communicate()` with a short secondary
timeout, then fall back to `process.terminate()` if still alive.

### 10. Stop swallowing DB persist errors (`agent.py`)
**Problem:** The `finally` block in `run_turn` wraps `db.update_message` and
`db.touch_chat` in `except Exception: pass`. A full disk or DB error silently
loses the assistant's response.

**Plan:** Replace the bare `pass` with a logged error (use the module `logger`)
so operators can see when persistence fails, while still not crashing the
stream.

### 11. Make `delete_chat` explicit (`db.py` + `routes/chats.py`)
**Problem:** `delete_chat` deletes `uploads` and `chats` rows and relies on
SQLite `ON DELETE CASCADE` for `messages`/`tasks`. `shutil.rmtree` uses
`ignore_errors=True`, so leftover per-chat files are silently ignored.

**Plan:**
- Explicitly `DELETE FROM messages WHERE chat_id = ?` and
  `DELETE FROM tasks WHERE chat_id = ?` (do not depend solely on cascade).
- Wrap `shutil.rmtree` in a try/except that logs a warning on failure instead
  of silently ignoring it.

---

## Testing & Tooling (currently absent)

### 12. Add backend tests (`tests/`)
**Problem:** The `tests/` directory is completely empty. `pytest` and
`pytest-asyncio` are already dev dependencies but unused.

**Plan:** Add `pytest` + `pytest-asyncio` tests covering:
- `db.py` — chat/message/task/upload/note CRUD, migrations.
- `tools/` — `write_file`, `read_file`, `list_files`, `search`, `webfetch`
  (mocked HTTP), `sandbox` (mocked subprocess).
- `routes/` — chat endpoints, settings, notes, files (with `TestClient` or
  `httpx.AsyncClient` against the FastAPI app).
- `providers.py` — `resolve_provider` selection logic.

### 13. Add frontend type-check and lint
**Problem:** TypeScript `tsc -b` runs as part of `build`, but there is no
separate lint/format step, and no frontend unit tests.

**Plan:** Add `eslint` + `prettier` to `web/package.json` dev dependencies with
`lint` and `format` scripts. Add `tsc --noEmit` as a standalone CI step
(separate from `vite build`).

### 14. Add Python linting/formatting
**Problem:** No `ruff`, `mypy`, `black`, or similar configured.

**Plan:** Add `ruff` (lint + format) and `mypy` to `pyproject.toml`
dev dependencies. Add `ruff check`, `ruff format --check`, and `mypy` as CI
steps.

---

## Order of Implementation (if executed)

1. Frontend splits (items 1–5) — lowest risk, purely internal.
2. Backend fixes (items 6–11) — correctness-oriented, small scope.
3. Testing & tooling (items 12–14) — add safety net last, after code is stable.

No items in this plan have been executed.
# Development

## Backend

### Run with reload

```bash
uv run uvicorn nexus.main:app --reload --port 8848
```

Or simply:

```bash
uv run nexus
```

### Tests

`pytest` and `pytest-asyncio` are dev dependencies. Run:

```bash
uv run pytest
```

Test files live in `tests/`:

- `test_encryption.py` — Fernet encryption
- `test_files_tools.py` — file tools (write/read/list)
- `test_harness_hardening.py` — filesystem harness hardening
- `test_message_versions.py` — message versioning
- `test_notes_api.py` — notes API
- `test_prompt.py` — system prompt
- `test_retry.py` — retry policy
- `test_version_api.py` — version API endpoints
- `test_webfetch.py` — web fetch

### Linting / formatting (planned)

No Python linter/formatter is configured yet. See [TODO.md](../TODO.md) item 7: add `ruff` (lint + format) and `mypy` to `pyproject.toml` dev dependencies, with `ruff check`, `ruff format --check`, and `mypy` as CI steps.

### Known cleanup items (backend)

See [CLEANUP_PLAN.md](../CLEANUP_PLAN.md) items 6–11. Notable remaining items:

- Fix sandbox UID/GID hardcoding (`tools/sandbox.py`) — uses `--userns=keep-id:uid=1000,gid=1000` and `--user 1000:1000`.
- Fix potential hang on sandbox timeout — `communicate()` after `kill()` has no secondary timeout.
- Stop swallowing DB persist errors (`agent.py` `finally` block) — log instead of `pass`.
- Make `delete_chat` explicit (do not rely solely on `ON DELETE CASCADE`).

## Frontend

### Dev server

```bash
npm --prefix web run dev
```

Proxies `/api` to the backend on port 5173.

### Production build

```bash
npm --prefix web run build
```

### Type-check

```bash
npx tsc --noEmit
```

### Linting / formatting (planned)

No ESLint/Prettier or frontend unit tests yet. See [TODO.md](../TODO.md) item 6.

### Known cleanup items (frontend)

See [CLEANUP_PLAN.md](../CLEANUP_PLAN.md) items 1–5:

- Split `App.tsx` (~844 lines) into hooks and smaller components.
- Split `SettingsDialog.tsx` (~711 lines) into panel components.
- Split `ToolTimeline.tsx` (662 lines) into `grouping.ts` and `bodies.ts`.
- Remove duplicate `CustomModel` interface (`types.ts`).
- Remove dead `run_python` mapping (`ToolTimeline.tsx`).

## Android (Capacitor)

See [mobile.md](./mobile.md).

## Coding style

- Python: type hints (`from __future__ import annotations`), module docstrings, Apache 2.0 copyright header on new files.
- TypeScript: React functional components, hooks, TypeScript strict mode, lucide-react icons.
- Commits: conventional, descriptive messages (see `git log`).

## Repository layout

```
src/nexus/          backend (FastAPI)
web/src/            frontend (React + TypeScript)
web/android/        Capacitor Android app
sandbox/            sandbox Containerfile
scripts/            setup-sandbox-user.sh, build-sandbox.sh, test-sandbox.sh
android-sdk/        vendored Android SDK
tests/              pytest tests
docs/               this documentation
data/               runtime data (gitignored)
.env                runtime config (gitignored)
```

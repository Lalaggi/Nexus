# Future Work Pile

Deliberately deferred work. This is the canonical backlog for big features; mobile
implementation detail for items 2 and 3 stays in `MOBILE_APP_PLANS.md`.

Current focus: native PDF/image reading in `read_file` (implemented). Item 5
(429/retry hardening) is now implemented; suggested next small win: item 3
(mobile settings) or item 2 (mobile gestures).

## Readiness snapshot

| # | Item | Size | Risk | Best first slice |
| --- | --- | --- | --- | --- |
| 1 | Clarifying questions / `ask_questions` | Large (3–5 days) | Medium–high: run lifecycle, persistence, UI state | Backend question state machine + tool, then UI card |
| 2 | Mobile gestures | Medium (1–2 days) | Medium: scroll/back-gesture conflicts | Left-edge open/close sidebar only |
| 3 | Mobile settings redesign | Medium (2–3 days) | Low–medium: visual regressions | Responsive full-screen shell + top category chips |
| 4 | Provider backend remake | XL (1–2 weeks, incremental) | High: provider quirks, metadata, picker | Adapter wrapper around today's client, then live `/models` cache |
| 5 | 429/retry handling | Done | — | `src/nexus/retry.py` policy + tests, retry status event in the UI |
| 6 | Message editing with version history | Large (4–6 days) | Medium–high: versioned message data model, UI switcher state | Version column/table + a "switch version" control on one assistant message |

---

## 1. Clarifying questions / `ask_questions`

**Goal:** let the model pause and ask the user a structured question in an interactive
GUI instead of guessing or asking in prose.

**Shape:**
- New tool, e.g. `ask_questions`, with a schema like:
  `[{ "id": "scope", "question": "...", "options": [{ "id": "a", "label": "..." }],
  "allow_multiple": false, "allow_free_text": true }]`.
- The tool persists a pending question set, emits an SSE `question` event, and ends the
  current turn with an `awaiting_user` state rather than continuing the tool loop.
- The UI renders question cards in the chat: radio/checkbox options, optional free-text
  field, and a single Submit button. Composer is disabled while questions are pending.
- Submitting posts the answers (e.g. `POST /api/chats/{chat_id}/answers`), stores them as
  a normal user message plus structured `answers` metadata, and starts a new run with the
  pending question attached to context.
- Cancelling or editing the message should discard the pending question set.
- Add a timeout/fallback: if the user never answers, the next message supersedes it.

**Work items:**
- `db.py`: pending-questions table (or a `questions` JSON column on messages).
- `tools/clarify.py`: register the tool and validate the payload.
- `agent.py`: stop the loop on a question result; surface `awaiting_user` in `done`.
- `routes/chats.py`: answer endpoint and run restart.
- Web: `QuestionCard` component, stream event handling, answer submission, mobile layout.
- Prompt: tell the model to ask only when a wrong guess would be costly, and to batch
  related questions into one call.

---

## 2. Mobile gestures

**Goal:** reduce reliance on small buttons and match common chat-app muscle memory.

**Ideas:**
- Swipe right from the left edge → open the chats sidebar; swipe left → close it.
- Swipe down on the composer or message area → dismiss tasks/files sheets.
- Swipe left/right on a message → reveal copy, edit, regenerate.
- Pull-to-refresh on the chat list and settings.
- Respect reduced-motion settings and Android back-gesture zones.

**Files:** `web/src/App.tsx`, `web/src/components/Sidebar.tsx`, sheets (`TasksPanel`,
file panel), plus a small touch/gesture hook (custom handlers or `use-gesture`).
See also `MOBILE_APP_PLANS.md` §2.

---

## 3. Mobile settings redesign

**Goal:** stop feeling like "desktop settings squeezed into a phone"; use the screen
shape properly.

**Ideas:**
- Full-screen or bottom-sheet settings on phones instead of a centered modal.
- Top category chips / segmented control, single-column scrolling content below.
- Collapsible cards per category instead of swapping whole panels.
- Group API keys, model choice, custom instructions, and notes into cards.
- Keep the two-column sidebar layout only on tablets/foldables via width breakpoints.
- Larger, thumb-friendly Save / Cancel / Change server actions.

**Files:** `web/src/components/SettingsDialog.tsx`, `web/src/styles.css`
(`.settings-layout`, `.settings-sidebar`, `.settings-content`).
See also `MOBILE_APP_PLANS.md` §1.

---

## 4. Provider backend remake

**Goal:** make providers and models portable instead of hand-curated, so any model on
OpenRouter, NVIDIA NIM, SiliconFlow, and similar services is easy to use.

**Ideas:**
- Provider adapters with a common interface: list models, fetch capabilities
  (vision/tools/context length), resolve a key, and stream completions.
- Pull real model lists from each provider's API instead of a hardcoded registry.
- Cache model metadata (especially `input_modalities`, tool support, and context size)
  and show it in the picker.
- Favorites: star models, persist them, and show only favorites in the quick model
  selector; full searchable list in settings.
- Per-provider base URLs, headers, and auth quirks (OpenRouter, NIM, SiliconFlow, custom
  OpenAI-compatible endpoints).
- Use capability metadata to drive features like native vision reading, so text-only
  models automatically fall back to text extraction.
- Graceful degradation when a provider is offline or a key is missing.

**Files:** `src/nexus/providers.py`, `src/nexus/config.py`, `db.py` (`custom_models` /
favorites), `routes/settings.py`, `web/src/components/SettingsDialog.tsx`, model picker
in `App.tsx` / `Composer.tsx`.

---

## 5. Proper retry and rate-limit handling (429) — implemented

Implemented in `src/nexus/retry.py`, `src/nexus/providers.py`, `src/nexus/agent.py`,
and the web retry status line. The notes below are kept as design context.

**Goal:** survive temporary rate limits and provider outages without failing a turn
prematurely, honor the provider's `Retry-After`, and never duplicate text that was
already shown to the user. Inspired by OpenCode's retry policy.

**Current state and gaps:**
- `StreamClient.stream` retries `429`, `500`, `502`, `503`, and `504` three times with
  fixed `1.5 × attempt` sleeps, and transport failures with the same budget.
- It ignores `Retry-After` / `retry-after-ms`, so free-tier limits that ask for 30–120
  seconds still fail after roughly 4.5 seconds of waiting.
- No jitter, no distinction between a temporary throttle and an exhausted quota or
  billing limit, and no attempt/status visibility in the UI.
- It sleeps inside the request generator without watching `RunState.cancel`, so Stop
  cannot interrupt a long rate-limit wait.
- A transport failure after some deltas have already been yielded is retried from the
  start, which can duplicate partial text in the same assistant message.
- Errors delivered inside an SSE stream (rather than as an HTTP status) are currently
  ignored as ordinary chunks.

**What OpenCode does (GitHub source):**
- `packages/ai/src/route/executor.ts`: parses `retry-after-ms` and `retry-after`
  (seconds or an HTTP date) from response headers and clamps the result.
- `packages/ai/src/schema/errors.ts`: classifies `429` as retryable `RateLimit`, treats
  `402`/quota-exhausted messages as terminal `QuotaExceeded`, honors `x-should-retry`,
  and exposes the provider delay as `retryAfterMs`.
- `packages/core/src/model-retry.ts`: jittered exponential backoff from 2s, capped at
  10s per gap for 10 retries; each gap is `max(backoff, retryAfter)`; provider-requested
  delays are capped at 15 minutes. Unreachable hosts get a separate one-hour budget, and
  timeouts are capped at three attempts so a dead provider cannot hold a call forever.
- `packages/core/src/session/runner/retry.ts`: publishes a retry-scheduled event with
  attempt, delay, and error before sleeping, so the client can show what is happening
  and Stop can interrupt the wait.

**Shape:**
- Add `src/nexus/retry.py` with pure, testable helpers:
  - `parse_retry_after_ms(headers)`: `retry-after-ms`, numeric `retry-after`, or HTTP
    date; clamp to `0..retry_after_max`.
  - `is_retryable(status, body, headers)`: `408`, `409`, `425`, `429`, `500`, `502`,
    `503`, `504`, and `529`; honor `x-should-retry`; stop on auth/invalid-request and
    obvious quota or billing exhaustion.
  - `next_delay(attempt, retry_after_ms)`: jittered exponential base 2s, cap 10s per
    gap, raised to `retry_after_ms` when the provider asks for longer.
- Add settings to `config.py`: `retry_max_attempts=10`, `retry_base_delay=2.0`,
  `retry_max_delay=10.0`, `retry_after_max=900.0`, `retry_jitter=0.2`, and a lower
  `retry_timeout_attempts=3`.
- Refactor `StreamClient.stream` to use the policy, and pass `RunState.cancel` (or a
  cancellation callback) so a wait ends immediately when the user presses Stop.
- Only retry transparently before the first chunk of a request has been yielded. Once
  text or tool-call deltas exist, fail with a clear `ProviderError` and leave the
  message/regenerate path intact. (A later enhancement can restart the whole step on a
  new assistant message, as OpenCode does.)
- Emit a new SSE event before sleeping:
  `{"type": "retry", "attempt": 3, "max_attempts": 10, "delay_ms": 8000, "message": "..."}`.
  Pass an `on_retry` callback from `agent.py` to `StreamClient`; `App.tsx` renders a
  compact status line on the assistant message and clears it on the next delta/done.
- Add tests in `tests/test_retry.py` for header parsing, HTTP-date handling, delay caps
  and jitter bounds, quota/terminal classification, no retry after partial output, and
  the retry event. Extract the response status handling enough to inject a fake
  transport, or test the pure policy first and keep `StreamClient` thin.

**Files:** `src/nexus/providers.py`, `src/nexus/config.py`, `src/nexus/agent.py`,
`src/nexus/routes/chats.py` (event plumbing only, if needed), `web/src/App.tsx`,
`web/src/types.ts`, `web/src/components/MessageView.tsx`, `tests/test_retry.py`.

**Acceptance criteria:**
- A `429` with `Retry-After: 30` waits about 30 seconds instead of failing after 4.5s.
- A `429` with no header backs off exponentially with jitter, up to the attempt limit.
- Auth errors, invalid requests, and obvious quota/billing exhaustion fail immediately
  with the provider's message.
- Stop interrupts a retry wait within about a second.
- No request is retried after any output has been streamed to the client.
- The UI shows attempt and delay while waiting, then resumes normally.

---

## 6. Message editing and regeneration with version history

**Goal:** keep every previous version of an edited or regenerated assistant message and let the
user switch between them, similar to OpenWebUI, LibreChat, or LM Studio. Today editing or
regenerating overwrites the message in place, destroying history.

**Shape:**
- Messages become versioned: each edit or regenerate creates a new version rather than replacing
  content. Store a `parent_message_id` / version relationship so versions of one message form a
  chain (a small tree later if branches are desired).
- The assistant message shows the active version by default, with a small control (a dropdown or
  `v1 / v2 / v3` chips) to switch between versions. Switching re-renders the message without
  sending anything to the model.
- Editing a message creates a new draft version pending resubmission; the user can discard it to
  fall back to the last accepted version.
- Regenerate appends a new version to the same message instead of creating a duplicate sibling
  message, keeping the chat list clean.
- Optionally show a diff when switching versions, and let the user "promote" an older version
  back to active.
- Persist versions in `db.py` (a `message_versions` table or version columns on `messages`), and
  expose endpoints: `GET /api/chats/{chat_id}/messages/{message_id}/versions`,
  `POST .../versions` (create/edit/regenerate), `POST .../versions/{version_id}/activate`.
- Web: `MessageVersionSwitcher` component, version list/drawer, diff view, composer disabled
  while a draft is pending.

**Work items:**
- `db.py`: message versions table / version columns, plus a migration.
- `routes/chats.py`: version list, create-version (edit/regenerate), and activate-version
  endpoints.
- `agent.py`: route regenerate/edit through version creation; keep the active version in context
  for subsequent turns.
- Web: version switcher UI, version drawer, diff component, draft handling, mobile layout.
- Prompt/instructions: note that regenerated replies branch from the message's context.

**Acceptance criteria:**
- Editing or regenerating an assistant message preserves the previous text as a version.
- A version switcher on the message lets the user jump between v1, v2, v3 and the content
  updates instantly.
- Switching versions does not create new messages or send anything to the model.
- The active version is what gets sent as context in later turns.
- Deleting a draft version falls back cleanly to the last active version.

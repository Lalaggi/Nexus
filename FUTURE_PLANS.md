# Future Work Pile

Deliberately deferred work. This is the canonical backlog for big features; mobile
implementation detail for items 2 and 3 stays in `MOBILE_APP_PLANS.md`.

Current focus: native PDF/image reading in `read_file` (implemented).

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

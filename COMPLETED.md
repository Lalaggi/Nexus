# Completed Work

Canonical record of features and polish items that have been implemented and shipped. Items here were previously tracked in `FUTURE_PLANS.md`, `MOBILE_APP_PLANS.md`, or the git history, and are marked "Done".

## Core features

### Message editing & regeneration with version history ✅
Every edit or regenerate appends a new version to a message instead of overwriting it, and the user can switch between versions.
- `messages` gained an `active_version_id` column; new `message_versions` table stores each version (`version`, `content`, `reasoning`, `tool_events`, `attachments`, `status`, `source`, `reply_to_version_id`, `created_at`).
- All sensitive version fields are encrypted at rest alongside the rest of the transcript.
- Existing databases are migrated on startup: each pre-versioning message gets a single version 1, and assistant replies are linked to the user version they answered.
- `db.py`: `add_message` seeds version 1; `create_message_version` appends a new version (edit/regenerate/draft) and optionally activates it; `activate_message_version` switches the active content; `list_message_versions` / `get_message_version` expose the chain; `set_message_content` / `update_message` keep the active version in sync.
- `routes/chats.py`: editing/PATCH creates a new version; regenerate appends a new version to the existing assistant message (no duplicate sibling) and removes stale trailing messages; new endpoints `GET /api/chats/{chat_id}/messages/{message_id}/versions`, `POST .../versions` (create an edited version), and `POST .../versions/{version_id}/activate` (switch version, plus the linked user/assistant side of an edited turn).
- `agent.py`: the `meta` and `done` SSE events now carry `version_id`, `version`, `version_source`, `reply_to_version_id`, and `versions`.
- Web: `VersionSwitcher` component (vN chips / dropdown with prev/next arrows and a version drawer showing source, relative time, and a preview), rendered on both user and assistant messages; switching versions re-renders the message without contacting the model; the active version is what's sent as context in later turns; composer is disabled while streaming.
- Files: `src/nexus/db.py`, `src/nexus/routes/chats.py`, `src/nexus/agent.py`, `web/src/types.ts`, `web/src/components/VersionSwitcher.tsx`, `web/src/components/MessageView.tsx`, `web/src/components/ChatView.tsx`, `web/src/App.tsx`, `web/src/styles.css`, `tests/test_message_versions.py`, `tests/test_version_api.py`.

### 429 / retry & rate-limit handling ✅
- `src/nexus/retry.py` with pure, testable helpers: `parse_retry_after_ms`, `is_retryable`, `next_delay`, and the `RetryPolicy` dataclass.
- `StreamClient.stream` retries `429`, `500`, `502`, `503`, `504` (and `408`, `409`, `425`, `529`) with jittered exponential backoff and honors provider `Retry-After` / `retry-after-ms` / HTTP-date headers, clamped to `retry_after_max` (15 min).
- Terminal classification for `402`, quota/billing exhaustion markers, auth errors, and invalid requests; `x-should-retry` header is authoritative.
- `on_retry` callback emits an SSE `retry` event so the UI can show attempt and delay while waiting; Stop interrupts a retry wait.
- No request is retried after any output has been streamed to the client.
- Settings: `retry_max_attempts`, `retry_base_delay`, `retry_max_delay`, `retry_after_max`, `retry_jitter`, `retry_timeout_attempts`.
- Tests: `tests/test_retry.py`.

### Native PDF/image reading in `read_file` ✅
- `src/nexus/media.py` renders images and PDF pages (pypdfium2 + Pillow) as base64 JPEG image parts for vision-capable models.
- PDFs also return their extracted text layer (pypdf) — one call gives both full text and visual layout.
- Per-image size budget, max dimension downscaling, `vision_max_pages`, `vision_max_file_mb`, `vision_max_total_mb`, `vision_max_images_per_turn` settings.
- Text-only models fall back to extracted text; `read_file` never converts via Python/OCR/pdftotext just to read.
- `media.py` is a pure on-demand converter — nothing rendered is written to disk.

### Custom models, notes management ✅
- Custom models (not in the curated registry) route through OpenRouter with the user's model ID.
- `custom_models` table; `/api/models/custom` CRUD endpoints.
- User notes: `note_list` / `note_get` / `note_set` / `note_delete` tools + `/api/notes` CRUD endpoints. Notes are user-level (not per-chat), key/value with validation (lowercase keys, max 60-char key, max 1000-char value).
- Notes appear in the system prompt and are referenced only when genuinely relevant.

### Model catalog ✅
- Model-agnostic provider backend: any model on NVIDIA NIM or OpenRouter can be used; the hardcoded Nemotron registry is replaced by a database-backed `model_catalog` table (`provider`, `model_id`, `name`, `enabled`, `is_default`, `source`).
- Nemotron 3.5 Super VL seeded as enabled + default on NIM and enabled on OpenRouter (works out of the box with either key).
- `GET /api/models/catalog`, `POST /api/models/catalog/sync` (OpenRouter `/models` fetch), `PATCH .../toggle`, `PATCH .../default`, `DELETE .../catalog/{id}` endpoints.
- `GET /api/settings` returns the full catalog plus `default_model`; `POST /api/settings/test` uses the provider's default enabled model.
- `resolve_provider(db, provider, model_id)` resolves an explicit provider + API model id to a `ProviderSpec` and key.
- Chats persist both `model` and `provider`; composer dropdown shows only enabled models.
- Frontend selector (flat list, no provider grouping): default model at top, enabled models alphabetical beneath, "Show all"/"Hide all models" button toggles disabled models alphabetical. Search auto-includes disabled matches. Pretty display names shown, raw API model IDs never renamed, provider label "NVIDIA" (not "NIM"), filled star for default (enabled models only), Material 3 toggle switches. Only Nemotron 3.5 Super VL enabled by default on NIM and OpenRouter; all discovered models added disabled.
- Model catalog panel includes manual "Add model" form for providers without a public model list (e.g. NIM).
- Provider settings panel reduced to just the two API key fields (NIM + OpenRouter); provider cards, description, default model ID override, custom model section, and test connection removed — all covered by the model catalog.
- Composer model dropdown: removed stale "Custom model ID" entry.
- Material 3 styling throughout: switches use colorOutline/colorPrimaryContainer track and colorOnSurface/colorPrimary handle per m3 specs (less round thumb, 18px); filled text inputs use surface-container-low with outline-variant border and primary focus state; consistent 40px height density.
- Removed redundant provider-chip from topbar (showed "Nemotron · OpenRouter", duplicated catalog provider badge).
- Removed hardcoded "Nemotron · provider" label from Sidebar footer (showed misinformation — always said Nemotron regardless of selected model).
- Removed unused `providerName` prop from Composer.
- Catalog cards use 20px border-radius (matching settings-section), not fully round (shape-full). Input boxes, dropdowns, buttons, and toggles stay round.

### Settings redesign ✅
- Collapsible category cards (Provider, Personalisation, Stats) instead of swapping whole panels.
- Mobile bottom sheet (≤900px) instead of centered modal; desktop/tablet two-column sidebar preserved (≥901px).
- Mobile-only "App Settings" card with Change Server / sign out.
- Smooth expand/collapse animation with measured `max-height` transition.
- Props contract unchanged (`SettingsPatch`, `onSave`/`onTest`/`onNotify`/`onSignOut`/`onClose`); `App.tsx` not modified.

### Mobile gestures ✅
- `web/src/useGesture.ts` — drag-follow touch gesture hook with passive listeners that never block scrolling or taps.
- Swipe right from anywhere opens the chats sidebar; swipe left closes it. The sidebar tracks the finger 1:1 while dragging, then snaps open/closed on lift with a 250ms ease transition seeded by release position and velocity (directional flick threshold).
- `prefers-reduced-motion` disables the sidebar slide animation while keeping the gesture functional.
- Sidebar positioning switched from `margin-left` to `transform: translateX()`.
- Built and installed on Android (user 0 only) via `adb install -r --user 0`.

### Clipboard ✅
- Copy code blocks and messages with a legacy fallback for plain-HTTP LAN origins.
- Copy success logged at `console.log` level.

## Mobile app (Capacitor Android) ✅

### Mixed content / networking
- `server.androidScheme: 'http'` so the local bundle loads at `http://localhost/` instead of `https://localhost/` — LAN server fetches over plain HTTP are no longer blocked as mixed content.
- `server.cleartext: true` retained for Android cleartext traffic policy.
- `android.allowMixedContent: true` as defense in depth.
- Stale `https://localhost` comment updated in `web/src/server.ts`.

### Boot flow
- Removed stale-closure early-return in `bootApp()` (`if (IS_NATIVE && !connected) return;`) that permanently blocked boot after reinstall.
- Mount `useEffect` now guards boot with `isConfigured()` so the Connect screen shows until a server URL is saved.
- Added a 15s default timeout to `api()` fetch calls in `web/src/api.ts` so boot fails over to an error screen instead of hanging indefinitely.

### Android system bars / orientation
- `android:screenOrientation="portrait"` in `AndroidManifest.xml` — locked to portrait on phone.
- `styles.xml` defines `AppTheme` / `AppTheme.NoActionBarLaunch` with `statusBarColor` / `navigationBarColor` set to `#141218` (Material 3 surface).
- `MainActivity` uses edge-to-edge mode + `WindowInsetsCompat` padding so content stays clear of status/nav bars.

### Mobile UI fixes
- Markdown tables: `white-space: nowrap` on `th`/`td` so wide tables scroll horizontally instead of stretching rows vertically.
- `.custom-model-id`: `min-width: 0` + `word-break: break-all` so long model IDs wrap cleanly.
- `.dialog-actions` buttons: `white-space: nowrap` so "Change server" / "Save changes" stay on one line.

## Process / licensing

### License updated to Apache 2.0 ✅
- To give wider opportunity for adoption.

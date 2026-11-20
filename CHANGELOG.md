# Changelog

All notable changes to Nexus are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- None yet — see [TODO.md](TODO.md) for the planned backlog.

### Changed
- None.

### Fixed
- None.

### Removed
- None.

## [0.1.0] — 2026-11-20

Current release. Highlights:

### Added
- **Message editing & regeneration with version history** — every edit or regenerate appends a new version to a message instead of overwriting it. The user can switch between versions with a `VersionSwitcher` UI component. New database tables `message_versions` and the `messages.active_version_id` column, with automatic migration for pre-existing databases. Endpoints: `GET /chats/{id}/messages/{id}/versions`, `POST .../versions`, `POST .../versions/{id}/activate`.
- **429 retry & rate-limit handling** — `src/nexus/retry.py` with jittered exponential backoff, provider `Retry-After` / `retry-after-ms` / HTTP-date honoring, terminal classification for auth failures and quota exhaustion, cancellation-interruptible waits, and an SSE `retry` event surfaced in the UI.
- **Native visual reading (images & PDFs)** — `read_file` renders images and PDF pages as native visual content for vision-capable models; PDFs also return their extracted text layer. Powered by `src/nexus/media.py` (pypdfium2 + Pillow) with per-image size budgets and page caps.
- **Custom models** — any OpenAI-compatible model ID routes through OpenRouter; stored per-user in the `custom_models` table.
- **User notes** — durable key/value memory (`note_list/get/set/delete` tools + `/api/notes` endpoints), used in the system prompt.
- **Settings redesign** — collapsible category cards, mobile bottom sheet, App Settings card, provider cards with API keys and test connection.
- **Mobile gestures** — swipe-from-anywhere to open/close the chats sidebar with drag-follow tracking and directional flick threshold.
- **Clipboard** — copy code blocks and messages with a legacy fallback for plain-HTTP LAN origins.
- **File upload refactor** — temp-directory uploads moved into per-chat dirs on attach; legacy file:// links still served.
- **Rebrand** — "Assistant" → "Nexus" across code, UI, and docs.
- **License** — changed to Apache 2.0.

### Changed
- Edit-message flow overhauled to match ChatGPT/DeepSeek/LibreChat style (single atomic version-creation action, no duplicate sibling messages).
- Sidebar positioning switched from `margin-left` to `transform: translateX()` for touch tracking.
- Settings open as a bottom sheet on phones (≤900px) instead of a centered modal.

### Fixed
- Clipboard copy on insecure plain-HTTP LAN origins.
- Sidebar flicks and drag-follow gesture stability.
- Edit-message duplicates and race conditions (editing made a single atomic action).
- User message action buttons positioning and visibility.
- Code block language label showing `hljs`.
- Legacy uploads visibility in the sandbox.

### Removed
- Hover message menu (reverted to Copy+Edit for user messages).

## [0.0.1] — 2026-11 (initial development)

### Added
- Initial commit: self-hosted Assistant with Nemotron 3.5 VL Super.
- Streaming chat, tool use, web search (SearXNG), web fetch, file tools, code sandbox.
- SQLite storage with Fernet at-rest encryption.
- Optional password login, single FastAPI process serving a React UI.
- Edit message, chat title generation, output file serving.
- 0.0.0.0 host binding documentation for remote access.

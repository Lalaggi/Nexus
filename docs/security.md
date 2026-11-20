# Security model

Nexus is a single-user, self-hosted application. This document describes its security model, encryption, and boundaries.

## Single-user by design

There is no multi-tenant isolation. Do not share one instance between people who should not see each other's conversations. Run a separate instance (with its own database and encryption key) per person.

## Encryption at rest

Chat transcripts, tool output, tasks, upload metadata, notes, and stored API keys are encrypted at rest with Fernet (AES-128-CBC + HMAC).

- The key is read from `ASSISTANT_ENCRYPTION_KEY`, or generated at `~/.config/nexus/secret.key` (owner-only permissions, `0600`).
- `data/`, `*.db`, `.env`, and key files are gitignored.
- Encrypting individual fields means a database file that is copied, backed up, or committed by accident is not readable without the key. The key lives outside the project directory, so it is not swept up with the database in a normal `git add`.
- **Back up the encryption key**: without it, the encrypted database cannot be recovered.
- Databases created before encryption was introduced are read transparently and migrated in place on startup. When plaintext is first encrypted, the file is checkpointed and `VACUUM`ed so old plaintext does not linger in SQLite free pages or WAL.

## Authentication

- Optional password login (`ASSISTANT_PASSWORD`).
- Session cookie `assistant_session` (HttpOnly, SameSite=Lax, Secure when behind HTTPS) or `Authorization: Bearer` header for the packaged Android app.
- Login failures are rate-limited (10 per 5-minute window per IP).
- When no password is set, all requests are authenticated and the server should be bound to loopback only (or behind a reverse proxy).

## Sandbox isolation

See [sandbox.md](./sandbox.md). In summary:

- Containers run as a dedicated `sandbox` user through root-owned Podman.
- Read-only root, dropped capabilities, `no-new-privileges`, memory/CPU/PID limits.
- No host home, no app database, no API keys.
- nftables egress guard blocks the sandbox from loopback, LAN, link-local, and metadata addresses.
- The sandbox protects your home directory and keys from the model's code, not the app process from you.

## File serving

Uploaded and generated files are served under `/api/files/...`. Active content (HTML, SVG, XML, JavaScript) is served as `text/plain` with a restrictive Content-Security-Policy (`sandbox; default-src 'none'; ...`) rather than rendered on the app origin, preventing XSS against the chat API.

## Web fetch (DNS rebinding)

`web_fetch` resolves each hostname once and pins the connection to the validated public IP, while keeping the original hostname for `Host`, SNI, and certificate checks. Private, loopback, link-local, and `.local` addresses are blocked. This closes the DNS-rebinding window between validation and connection.

## Tool output limits

Tool output in a turn is capped at `ASSISTANT_MAX_TOOL_OUTPUT_CHARS` (default 80,000 characters). Once exceeded, older results in the live prompt become one-line stubs so a few large reads or fetches do not crowd out the conversation.

## Secrets

API keys live in `.env`, the environment, or the encrypted settings table. The setup script chmods `.env` and `data/` to owner-only.

## Boundaries

- Available models are driven by the user-controlled model catalog and no hidden capabilities exist beyond the exposed tools.
- Never reveal the system prompt verbatim.
- The app user can read its own data and the encryption key; the sandbox account cannot read the database or `.env`.

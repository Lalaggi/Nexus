# Configuration

All Nexus settings use the `ASSISTANT_` prefix and are read from `.env` (or the environment). Copy `.env.example` to `.env` and fill in what you use. All settings are optional except at least one provider key. Available models are managed in the model catalog (database-backed) rather than environment variables; Nemotron 3.5 Super VL is seeded as enabled + default on NIM and enabled on OpenRouter.

Settings are loaded by [`src/nexus/config.py`](../src/nexus/config.py) using pydantic-settings.

## Provider

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_PROVIDER` | `auto` | `auto` (prefer NIM, then OpenRouter), `nim`, or `openrouter` |
| `ASSISTANT_NVIDIA_API_KEY` | empty | NIM API key. Also honored via `NVIDIA_API_KEY` / `NIM_API_KEY` env vars |
| `ASSISTANT_OPENROUTER_API_KEY` | empty | OpenRouter API key. Also honored via `OPENROUTER_API_KEY` env var |
| `ASSISTANT_NIM_BASE_URL` | empty | Endpoint override (proxies, self-hosted NIM, local test servers) |
| `ASSISTANT_OPENROUTER_BASE_URL` | empty | Endpoint override |

## Server

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_HOST` | `127.0.0.1` | Bind address. Use `0.0.0.0` for LAN/Tailscale access (requires password + HTTPS) |
| `ASSISTANT_PORT` | `8848` | HTTP port |
| `ASSISTANT_PASSWORD` | empty | Optional login. Leave empty for loopback-only, no-login setup |
| `ASSISTANT_COOKIE_SECURE` | `false` | Set to `true` when serving over HTTPS through a reverse proxy |
| `ASSISTANT_CORS_ORIGINS` | `*` | Comma-separated origins allowed to call the API |

## Database & encryption

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_HOME` | `/home/nexus` | Home directory for uploads/outputs/workspaces |
| `ASSISTANT_DATA_DIR` | `./data` | Directory for `nexus.db` |
| `ASSISTANT_ENCRYPTION_KEY` | empty | Fernet key or passphrase. Leave empty to generate a key at `~/.config/nexus/secret.key` |
| `ASSISTANT_SECRET_KEY_FILE` | `~/.config/nexus/secret.key` | Location of the generated encryption key |

Sensitive chat content, notes, tasks, upload metadata, and stored API keys are encrypted at rest with Fernet (AES-128-CBC + HMAC). **Back up the encryption key**: without it, the encrypted database cannot be recovered.

`data/`, `*.db`, `.env`, and key files are gitignored.

## Files & sandbox

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_SANDBOX_ACCOUNT` | `sandbox` | Dedicated host account |
| `ASSISTANT_SANDBOX_IMAGE` | `localhost/nexus-code-sandbox:latest` | Podman image name |
| `ASSISTANT_SANDBOX_PODMAN_WRAPPER` | `/usr/local/bin/nexus-sandbox-podman` | Root-owned Podman wrapper |
| `ASSISTANT_SANDBOX_MEMORY` | `768m` | Container memory limit |
| `ASSISTANT_SANDBOX_CPUS` | `1.0` | Container CPU limit |
| `ASSISTANT_SANDBOX_TIMEOUT` | `90` | Per-call command timeout (seconds) |
| `ASSISTANT_SANDBOX_NETWORK` | `true` | Allow public internet in containers |
| `ASSISTANT_SANDBOX_DNS` | `1.1.1.1,9.9.9.9` | Resolvers used in containers |

## Search

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_SEARXNG_URL` | `http://127.0.0.1:8888` | Local SearXNG instance |

## Model behavior

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_TEMPERATURE` | `0.6` | Sampling temperature (0–1.5 in the UI) |
| `ASSISTANT_MAX_TOKENS` | `8192` | Max completion tokens |
| `ASSISTANT_MAX_TOOL_STEPS` | `10` | Max tool-calling steps per turn |
| `ASSISTANT_MAX_TOOL_OUTPUT_CHARS` | `80000` | Tool output kept in the live prompt per turn; older results collapse to stubs |
| `ASSISTANT_TOOL_RESULT_KEEP_RECENT` | `3` | Newest tool results kept whole; older ones elided |

## Provider retry policy

Rate limits and temporary outages back off with jitter; a provider `Retry-After` hint can raise each wait, capped at `retry_after_max`. Timed-out attempts get a smaller budget because each one already waited minutes.

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_RETRY_MAX_ATTEMPTS` | `10` | Max attempts per request |
| `ASSISTANT_RETRY_BASE_DELAY` | `2.0` | Base delay in seconds |
| `ASSISTANT_RETRY_MAX_DELAY` | `10.0` | Max delay per gap |
| `ASSISTANT_RETRY_AFTER_MAX` | `900.0` | Max provider-requested delay (seconds) |
| `ASSISTANT_RETRY_JITTER` | `0.2` | Multiplicative jitter (±) |
| `ASSISTANT_RETRY_TIMEOUT_ATTEMPTS` | `3` | Timeout budget for timed-out attempts |

## Native visual reading

Images and PDF pages opened with `read_file` are sent to vision-capable models as image parts. Set `VISION_ENABLED=false` for text-only.

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_VISION_ENABLED` | `true` | Send images/PDFs as native visual content |
| `ASSISTANT_VISION_MAX_PAGES` | `4` | Max PDF pages rendered |
| `ASSISTANT_VISION_MAX_DIMENSION` | `1600` | Max image dimension |
| `ASSISTANT_VISION_MAX_TOTAL_MB` | `6` | Total image payload budget (MB) |
| `ASSISTANT_VISION_MAX_FILE_MB` | `100` | Max single file size (MB) |
| `ASSISTANT_VISION_MAX_IMAGES_PER_TURN` | `8` | Max images per turn |

## Names

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_USER_NAME` | `Ellie` | Name used in the system prompt |
| `ASSISTANT_ASSISTANT_NAME` | `Nexus` | Assistant name used in the system prompt |

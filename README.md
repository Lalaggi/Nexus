# Nexus

A self-hosted, single-user ChatGPT replacement built around **NVIDIA Nemotron 3.5 VL Super** (via NIM, falling back to OpenRouter). It streams reasoning, calls tools, searches the web through a local SearXNG instance, and gives the model a disposable Linux sandbox for Python, git, curl, and file output.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-blue)](https://python.org)
[![uv](https://img.shields.io/badge/uv-ready-green)](https://docs.astral.sh/uv/)

## What it does

- Streaming chat with collapsible reasoning and a grouped activity timeline.
- Curated model: `Nemotron 3.5 VL Super`, automatically preferring NIM over OpenRouter.
- Tools: `web_search` (SearXNG), `web_fetch`, `write_file`, `read_file`, `list_files`, `sandbox` (shell commands in a Linux container), plus a visible goal/task list and durable user notes.
- Native visual reading: `read_file` renders images and PDF pages from uploads, outputs, or the workspace and sends them to the vision model as image parts. PDFs also return their text layer, so one call gives both the full text and visual layout. Text-only models fall back to extracted text.
- Uploads in `useruploads/`, generated files in `outputs/`, and chat links like `[report.md](file:///mnt/outputs/report.md)` that open in the app.
- An isolated code sandbox with Python, git, curl, Node, a compiler, and scientific Python packages, but no access to your real home directory, API keys, or LAN.
- Message editing and regeneration with version history — switch between versions of any message.
- SQLite storage, optional password login, and a single FastAPI process serving the React UI.
- A Capacitor Android app that connects to your self-hosted server over LAN/Tailscale/reverse proxy.

## Requirements

- Linux (developed on EndeavourOS/Arch) with Python 3.13+, [uv](https://docs.astral.sh/uv/), Node 20+, and npm.
- For the sandbox: rootless Podman, `nftables`, `acl`, `e2fsprogs`, `shadow`, `util-linux`, and systemd.
- A SearXNG instance (default `http://127.0.0.1:8888`).
- An NVIDIA NIM or OpenRouter API key.

Install the sandbox host tools on Arch:

```bash
sudo pacman -S podman nftables acl e2fsprogs shadow util-linux
```

## Quick start

```bash
git clone <this repo> Nexus
cd Nexus

uv sync
npm --prefix web install
npm --prefix web run build

cp .env.example .env
# edit .env: add a NIM or OpenRouter key

uv run nexus
```

Open <http://127.0.0.1:8848>.

The server binds to loopback by default. If you expose it beyond loopback, set `ASSISTANT_PASSWORD`, put it behind HTTPS, and set `ASSISTANT_COOKIE_SECURE=true`.

To bind to all interfaces (e.g. for phone or Tailscale access), set `ASSISTANT_HOST=0.0.0.0`:

```bash
ASSISTANT_HOST=0.0.0.0 uv run nexus
```

⚠️ Only do this with a password set and preferably behind a reverse proxy with HTTPS.

## Sandbox setup (recommended)

The sandbox is what makes the `sandbox` tool genuinely useful while keeping your real files out of reach. Run the one-time host setup:

```bash
sudo ./scripts/setup-sandbox-user.sh
```

It creates a dedicated `sandbox` account, a 40 GB ext4 loop image, root-owned Podman wrapper, nftables egress guard, and builds the sandbox container image. Then restart the app and check:

```bash
curl -s http://127.0.0.1:8848/api/health
./scripts/test-sandbox.sh
```

`/api/health` should report `"mode": "dedicated user sandbox"`.

See [docs/sandbox.md](docs/sandbox.md) for the full isolation model and [docs/installation.md](docs/installation.md) for step-by-step install instructions.

## Documentation

| Document | Contents |
|----------|----------|
| [docs/installation.md](docs/installation.md) | Step-by-step install, sandbox host setup, first run |
| [docs/configuration.md](docs/configuration.md) | All `ASSISTANT_*` environment variables |
| [docs/usage.md](docs/usage.md) | Features, tools, chat model, files & links |
| [docs/tools.md](docs/tools.md) | Built-in tool reference (schemas, arguments, behavior) |
| [docs/api.md](docs/api.md) | HTTP API endpoints and SSE stream events |
| [docs/sandbox.md](docs/sandbox.md) | Sandbox isolation, nftables guard, Podman wrapper |
| [docs/development.md](docs/development.md) | Backend/frontend development, tests, linting |
| [docs/mobile.md](docs/mobile.md) | Capacitor Android app build and first run |
| [docs/security.md](docs/security.md) | Security model, encryption, boundaries |
| [docs/architecture.md](docs/architecture.md) | Architecture and data flow |
| [docs/contributing.md](docs/contributing.md) | How to contribute, cleanup plan, coding style |

Project tracking:
- [CHANGELOG.md](CHANGELOG.md) — version history
- [COMPLETED.md](COMPLETED.md) — implemented features
- [TODO.md](TODO.md) — backlog and planned work

## Configuration

All settings use the `ASSISTANT_` prefix. See `.env.example` for the full list. The most useful ones:

| Variable | Default | Notes |
|----------|---------|-------|
| `ASSISTANT_PROVIDER` | `auto` | `auto`, `nim`, or `openrouter` |
| `ASSISTANT_NVIDIA_API_KEY` / `ASSISTANT_OPENROUTER_API_KEY` | empty | At least one required |
| `ASSISTANT_HOST` / `ASSISTANT_PORT` | `127.0.0.1` / `8848` | Keep loopback unless proxied |
| `ASSISTANT_PASSWORD` | empty | Optional login |
| `ASSISTANT_ENCRYPTION_KEY` | empty | Fernet key/passphrase; generated key file if unset |
| `ASSISTANT_SECRET_KEY_FILE` | `~/.config/nexus/secret.key` | Location of the generated encryption key |
| `ASSISTANT_SEARXNG_URL` | `http://127.0.0.1:8888` | Local SearXNG |
| `ASSISTANT_SANDBOX_ACCOUNT` | `sandbox` | Dedicated host account |
| `ASSISTANT_SANDBOX_NETWORK` | `true` | Allow public internet in containers |
| `ASSISTANT_SANDBOX_DNS` | `1.1.1.1,9.9.9.9` | Resolvers used in containers |

Full reference: [docs/configuration.md](docs/configuration.md).

## Development

```bash
# backend with reload
uv run uvicorn nexus.main:app --reload --port 8848

# frontend dev server (proxies /api to the backend)
npm --prefix web run dev

# production build
npm --prefix web run build

# tests
uv run pytest
```

Full guide: [docs/development.md](docs/development.md).

## Android (Capacitor)

The React UI is packaged as a native Android app with Capacitor. See [docs/mobile.md](docs/mobile.md) for build instructions and first-run steps.

## Security notes

- This is a single-user app by design. There is no multi-tenant isolation, so do not share one instance between people who should not see each other's conversations. Run a separate instance (with its own database and encryption key) per person.
- Chat transcripts, tool output, tasks, upload metadata, notes, and stored API keys are encrypted at rest with Fernet (AES-128-CBC + HMAC). The key is read from `ASSISTANT_ENCRYPTION_KEY` or generated at `~/.config/nexus/secret.key` with owner-only permissions. **Back up that key**: without it, the encrypted database cannot be recovered.
- `data/`, `*.db`, `.env`, and key files are gitignored.
- The sandbox protects your home directory and keys from the model's code, not the app process from you.

Full model: [docs/security.md](docs/security.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).
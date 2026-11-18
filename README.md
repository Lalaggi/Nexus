# Assistant

A self-hosted, single-user ChatGPT replacement built around **NVIDIA Nemotron 3.5 VL Super** (via NIM, falling back to OpenRouter). It streams reasoning, calls tools, searches the web through a local SearXNG instance, and gives the model a disposable Linux sandbox for Python, git, curl, and file output.

## What it does

- Streaming chat with collapsible reasoning and a grouped activity timeline.
- Curated model: `Nemotron 3.5 VL Super`, automatically preferring NIM over OpenRouter.
- Tools: `web_search` (SearXNG), `web_fetch`, `write_file`, `read_file`, `list_files`, `sandbox` (shell commands in a Linux container), plus a visible goal/task list.
- Uploads in `useruploads/`, generated files in `outputs/`, and chat links like `[report.md](file:///mnt/outputs/report.md)` that open in the app.
- An isolated code sandbox with Python, git, curl, Node, a compiler, and scientific Python packages, but no access to your real home directory, API keys, or LAN.
- SQLite storage, optional password login, and a single FastAPI process serving the React UI.

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
git clone <this repo> Assistant
cd Assistant

uv sync
npm --prefix web install
npm --prefix web run build

cp .env.example .env
# edit .env: add a NIM or OpenRouter key

uv run assistant
```

Open <http://127.0.0.1:8848>.

The server binds to loopback by default. If you expose it beyond loopback, set `ASSISTANT_PASSWORD`, put it behind HTTPS, and set `ASSISTANT_COOKIE_SECURE=true`.

To bind to all interfaces (e.g. for phone or Tailscale access), set `ASSISTANT_HOST=0.0.0.0`:

```bash
ASSISTANT_HOST=0.0.0.0 uv run assistant
```

⚠️ Only do this with a password set and preferably behind a reverse proxy with HTTPS.

## Sandbox setup (recommended)

The sandbox is what makes the `sandbox` tool genuinely useful while keeping your real files out of reach. Run the one-time host setup:

```bash
sudo ./scripts/setup-sandbox-user.sh
```

It creates:

- a dedicated, passwordless `sandbox` account with no login shell;
- a 40 GB ext4 loop image at `/var/lib/assistant-sandbox.img`, mounted at `/srv/assistant-sandbox`;
- `/home/assistant` bind-mounted from that image, owned by you, with narrow ACLs for the sandbox account;
- a root-owned Podman wrapper plus a single sudoers rule, so the app can run containers as `sandbox` but not as root;
- an nftables egress guard that drops sandbox traffic to loopback, LAN, link-local, and metadata addresses while allowing public internet and DNS;
- the sandbox image, built as the sandbox account.

Then restart the app and check:

```bash
curl -s http://127.0.0.1:8848/api/health
./scripts/test-sandbox.sh
```

`/api/health` should report `"mode": "dedicated user sandbox"`.

The script is idempotent. It writes an fstab entry for the loop and bind mounts; make sure `/home/assistant` is not already a separately managed mount.

### How isolation works

- Containers run as the dedicated `sandbox` user through root-owned Podman, with images and layers on the size-capped loop filesystem.
- Each `sandbox` call is an ephemeral container: read-only root, dropped capabilities, `no-new-privileges`, memory/CPU/PID limits, no host home, no app database.
- Only `useruploads/` (read-only), `outputs/`, and the per-chat `.workspaces/` directory are mounted.
- Outbound internet is allowed; private ranges are dropped by nftables keyed on the sandbox UID.
- The app user owns the files. The sandbox gets `rX` on uploads and `rwX` on outputs/workspaces through ACLs.

### Development fallback

Without the setup script, the app falls back to your own rootless Podman and `data/home/` for files. This is convenient for development but does **not** isolate the sandbox from your account. `/api/health` reports `current user (development mode)` in that case.

## Files and links

- Uploads: `useruploads/` (model reads them at `/mnt/useruploads`)
- Outputs: `outputs/` (model writes them at `/mnt/outputs`)
- Per-chat scratch: `.workspaces/<chat-id>` (mounted at `/workspace`)

The model is instructed to produce `file://` links under `/mnt/outputs`. The frontend maps those to `/api/files/...`, and active content (HTML, SVG, XML, JavaScript) is served as `text/plain` with a sandbox CSP rather than rendered on the app origin.

## Configuration

All settings use the `ASSISTANT_` prefix. See `.env.example` for the full list. The most useful ones:

| Variable | Default | Notes |
| --- | --- | --- |
| `ASSISTANT_PROVIDER` | `auto` | `auto`, `nim`, or `openrouter` |
| `ASSISTANT_NVIDIA_API_KEY` / `ASSISTANT_OPENROUTER_API_KEY` | empty | At least one required |
| `ASSISTANT_HOST` / `ASSISTANT_PORT` | `127.0.0.1` / `8848` | Keep loopback unless proxied |
| `ASSISTANT_PASSWORD` | empty | Optional login |
| `ASSISTANT_ENCRYPTION_KEY` | empty | Fernet key/passphrase; generated key file if unset |
| `ASSISTANT_SECRET_KEY_FILE` | `~/.config/assistant/secret.key` | Location of the generated encryption key |
| `ASSISTANT_SEARXNG_URL` | `http://127.0.0.1:8888` | Local SearXNG |
| `ASSISTANT_SANDBOX_ACCOUNT` | `sandbox` | Dedicated host account |
| `ASSISTANT_SANDBOX_NETWORK` | `true` | Allow public internet in containers |
| `ASSISTANT_SANDBOX_DNS` | `1.1.1.1,9.9.9.9` | Resolvers used in containers |

## Development

```bash
# backend with reload
uv run uvicorn assistant.main:app --reload --port 8848

# frontend dev server (proxies /api to the backend)
npm --prefix web run dev

# production build
npm --prefix web run build

# tests
uv run pytest
```

## Android (Capacitor)

The React UI is packaged as a native Android app with [Capacitor](https://capacitorjs.com/). The web build is bundled into the APK; on first launch the app prompts for the address of your self-hosted Assistant server (LAN, Tailscale, or a reverse-proxied public URL) and remembers it. API calls use a bearer token (from login) instead of cookies, and the backend allows the `file://` WebView origin.

### Build the APK

You need the Android SDK (command-line tools, platform-tools, build-tools, and an Android platform) and a JDK (Java 17–21 for Gradle 8.14):

```bash
# install Android SDK command-line tools into ~/Android/Sdk, then:
export ANDROID_SDK_ROOT=$HOME/Android/Sdk
export ANDROID_HOME=$HOME/Android/Sdk
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk   # or java-17-openjdk

# from the repo root
npm --prefix web run cap:build   # builds the web bundle and syncs it into android/
cd web/android
./gradlew assembleDebug
```

The unsigned debug APK is output at:

```
web/android/app/build/outputs/apk/debug/app-debug.apk
```

Install on a device/emulator:

```bash
adb install web/android/app/build/outputs/apk/debug/app-debug.apk
```

For a release build, create a signing keystore (`keytool -genkey ...`) and configure `web/android/app/build.gradle` (`signingConfigs`), then run `./gradlew assembleRelease`.

### First run

1. Start your Assistant server on a machine reachable from the phone (e.g. `ASSISTANT_HOST=0.0.0.0 uv run assistant`, with `ASSISTANT_PASSWORD` set and, for public access, HTTPS).
2. Open the app and enter the server address, e.g. `http://192.168.1.20:8848`.
3. Unlock with your server password (if set). The session token is stored locally.
4. Use Settings → Change server to switch instances or clear the remembered session.

### Native plugins used

`@capacitor/app`, `@capacitor/browser`, `@capacitor/keyboard`, `@capacitor/status-bar`, `@capacitor/splash-screen`.

External links (web search results, fetched pages, images) open in the system browser; file previews/downloads go through the app with the session token in the query string.

Rebuild the sandbox image after editing `sandbox/Containerfile`:

```bash
./scripts/build-sandbox.sh
./scripts/test-sandbox.sh
```

## Security notes

- This is a single-user app by design. There is no multi-tenant isolation, so do not share one instance between people who should not see each other's conversations. Run a separate instance (with its own database and encryption key) per person.
- Chat transcripts, tool output, tasks, upload metadata, notes, and stored API keys are encrypted at rest with Fernet (AES-128-CBC + HMAC). The key is read from `ASSISTANT_ENCRYPTION_KEY` or generated at `~/.config/assistant/secret.key` with owner-only permissions. **Back up that key**: without it, the encrypted database cannot be recovered.
- `data/`, `*.db`, `.env`, and key files are gitignored. Encrypting the fields means an accidentally committed database still does not expose chat content without the separate key.
- The sandbox protects your home directory and keys from the model's code, not the app process from you. The app user can still read its own data and the encryption key.
- The nftables guard blocks private address ranges for the sandbox UID. If you later bind the app to `0.0.0.0`, it remains outside that guard's scope for non-sandbox traffic; use a firewall or reverse proxy.
- Active files are served as attachments with a restrictive CSP. Do not change that without understanding the XSS risk.
- API keys live in `.env`, the environment, or the encrypted settings table. The setup script chmods `.env` and `data/` to owner-only.
